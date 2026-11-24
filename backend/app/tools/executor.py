from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import perf_counter

import httpx
from pydantic import ValidationError

from app.core.permissions import requires_approval
from app.tools.logging import ToolExecutionLogger
from app.tools.models import RegisteredTool, ToolCallRequest, ToolCallResult
from app.tools.registry import ToolRegistry, build_default_tool_registry


SleepCallable = Callable[[float], Awaitable[None]]


class ToolExecutor:
    """Validate and execute one tool call with bounded transient retries."""

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        logger: ToolExecutionLogger | None = None,
        *,
        sleep: SleepCallable = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self.registry = registry or build_default_tool_registry()
        self.logger = logger or ToolExecutionLogger()
        self.sleep = sleep
        self.jitter = jitter

    async def run(self, request: ToolCallRequest) -> ToolCallResult:
        started_at = datetime.now(UTC)
        started = perf_counter()
        tool = self.registry.get(request.tool_name)
        if tool is None:
            result = self._failure(request, error=f"Unknown tool: {request.tool_name}", error_type="UnknownTool")
            return await self._finish(request, result, started_at, started)

        if requires_approval(tool.spec.permission_level) and not request.approved:
            result = self._failure(
                request,
                error="Tool requires explicit user approval before execution.",
                error_type="ApprovalRequired",
                permission_level=tool.spec.permission_level,
                requires_approval=True,
            )
            return await self._finish(request, result, started_at, started)
        if requires_approval(tool.spec.permission_level) and not request.idempotency_key:
            result = self._failure(
                request,
                error="Side-effecting tools require an idempotency key.",
                error_type="IdempotencyKeyRequired",
                permission_level=tool.spec.permission_level,
            )
            return await self._finish(request, result, started_at, started)

        unavailable = self._unavailable_result(request, tool)
        if unavailable is not None:
            return await self._finish(request, unavailable, started_at, started)

        try:
            arguments = self._validated_arguments(tool, request.arguments)
        except ValidationError as exc:
            result = self._failure(
                request,
                error=str(exc),
                error_type="ValidationError",
                permission_level=tool.spec.permission_level,
            )
            return await self._finish(request, result, started_at, started)

        attempts = tool.spec.max_attempts if tool.spec.external_api else 1
        for attempt in range(1, attempts + 1):
            try:
                output = await asyncio.wait_for(
                    tool.handler(arguments),
                    timeout=tool.spec.timeout_seconds,
                )
                recoverable_error = _recoverable_output_error(output)
                output_retryable = _recoverable_output_retryable(output)
                if recoverable_error and output_retryable and tool.spec.external_api and attempt < attempts:
                    await self.sleep(_retry_delay(attempt, self.jitter()))
                    continue
                result = ToolCallResult(
                    call_id=request.call_id,
                    tool_name=request.tool_name,
                    success=True,
                    output=output,
                    arguments=arguments,
                    permission_level=tool.spec.permission_level,
                    attempts=attempt,
                    degraded=bool(recoverable_error),
                    retryable=bool(recoverable_error and output_retryable),
                    error_type="RecoverableProviderError" if recoverable_error else None,
                )
                return await self._finish(request, result, started_at, started)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                retryable = _is_retryable_exception(exc)
                if not retryable or attempt >= attempts:
                    result = self._failure(
                        request,
                        error=str(exc),
                        error_type=type(exc).__name__,
                        permission_level=tool.spec.permission_level,
                        attempts=attempt,
                        retryable=retryable,
                    )
                    return await self._finish(request, result, started_at, started)
                await self.sleep(_retry_delay(attempt, self.jitter(), exc))

        raise AssertionError("bounded tool execution loop did not return")

    def _validated_arguments(self, tool: RegisteredTool, arguments: dict) -> dict:
        if tool.input_model is None:
            return dict(arguments)
        return tool.input_model.model_validate(arguments).model_dump(mode="json", exclude_none=True)

    def _unavailable_result(self, request: ToolCallRequest, tool: RegisteredTool) -> ToolCallResult | None:
        if tool.availability_checker is None:
            return None
        status = tool.availability_checker()
        if status.available:
            return None
        return self._failure(
            request,
            error=status.recoverable_error or f"Tool {request.tool_name} is unavailable.",
            error_type="ToolUnavailable",
            permission_level=tool.spec.permission_level,
        )

    def _failure(
        self,
        request: ToolCallRequest,
        *,
        error: str,
        error_type: str,
        permission_level=None,
        requires_approval: bool = False,
        attempts: int = 0,
        retryable: bool = False,
    ) -> ToolCallResult:
        return ToolCallResult(
            call_id=request.call_id,
            tool_name=request.tool_name,
            success=False,
            arguments=request.arguments,
            error=error,
            error_type=error_type,
            permission_level=permission_level,
            requires_approval=requires_approval,
            attempts=attempts,
            retryable=retryable,
        )

    async def _finish(
        self,
        request: ToolCallRequest,
        result: ToolCallResult,
        started_at: datetime,
        started: float,
    ) -> ToolCallResult:
        duration_ms = (perf_counter() - started) * 1000
        result = result.model_copy(update={"duration_ms": duration_ms})
        await self.logger.log(
            request,
            result,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            duration_ms=duration_ms,
        )
        return result


def _recoverable_output_error(output: dict) -> str | None:
    value = output.get("recoverable_error")
    if value:
        return str(value)
    provider_status = output.get("provider_status")
    if isinstance(provider_status, dict) and provider_status.get("recoverable_error"):
        return str(provider_status["recoverable_error"])
    return None


def _recoverable_output_retryable(output: dict) -> bool:
    if "retryable" in output:
        return bool(output["retryable"])
    return bool(_recoverable_output_error(output))


def _is_retryable_exception(error: Exception) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code in {408, 429} or error.response.status_code >= 500
    return False


def _retry_delay(attempt: int, jitter: float, error: Exception | None = None) -> float:
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 429:
        retry_after = error.response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), 0.0)
            except ValueError:
                pass
    base = min(0.5 * (2 ** (attempt - 1)), 2.0)
    return base + max(0.0, min(jitter, 1.0)) * base * 0.3
