from datetime import UTC, datetime
from time import perf_counter

from app.core.permissions import requires_approval
from app.tools.logging import ToolExecutionLogger
from app.tools.models import ToolCallRequest, ToolCallResult
from app.tools.registry import ToolRegistry, build_default_tool_registry


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry | None = None,
        logger: ToolExecutionLogger | None = None,
    ) -> None:
        self.registry = registry or build_default_tool_registry()
        self.logger = logger or ToolExecutionLogger()

    async def run(self, request: ToolCallRequest) -> ToolCallResult:
        started_at = datetime.now(UTC)
        started = perf_counter()
        tool = self.registry.get(request.tool_name)
        if tool is None:
            result = ToolCallResult(
                tool_name=request.tool_name,
                success=False,
                error=f"Unknown tool: {request.tool_name}",
            )
            await self._log(request, result, started_at=started_at, started=started)
            return result

        approval_needed = requires_approval(tool.spec.permission_level)
        if approval_needed and not request.approved:
            result = ToolCallResult(
                tool_name=request.tool_name,
                success=False,
                error="Tool requires explicit user approval before execution.",
                requires_approval=True,
                permission_level=tool.spec.permission_level,
            )
            await self._log(request, result, started_at=started_at, started=started)
            return result

        try:
            output = await tool.handler(request.arguments)
        except Exception as exc:
            result = ToolCallResult(
                tool_name=request.tool_name,
                success=False,
                error=str(exc),
                permission_level=tool.spec.permission_level,
            )
            await self._log(request, result, started_at=started_at, started=started)
            return result

        result = ToolCallResult(
            tool_name=request.tool_name,
            success=True,
            output=output,
            permission_level=tool.spec.permission_level,
        )
        await self._log(request, result, started_at=started_at, started=started)
        return result

    async def _log(
        self,
        request: ToolCallRequest,
        result: ToolCallResult,
        *,
        started_at: datetime,
        started: float,
    ) -> None:
        completed_at = datetime.now(UTC)
        await self.logger.log(
            request,
            result,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=(perf_counter() - started) * 1000,
        )
