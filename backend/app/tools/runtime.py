from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.core.permissions import PermissionLevel
from app.schemas.chat import ChatRequest
from app.tools.decision import AgentToolDecision, ToolCallDraft, ToolDecisionAgent
from app.tools.executor import ToolExecutor
from app.tools.models import ToolCallRequest, ToolCallResult
from app.tools.registry import ToolRegistry


CancellationCheck = Callable[[], Awaitable[None]]
_RESULT_CACHE: dict[str, tuple[datetime, ToolCallResult]] = {}
_CACHE_LOCK = asyncio.Lock()


class ToolExecutionBatch(BaseModel):
    results: list[ToolCallResult] = Field(default_factory=list)
    decisions: list[AgentToolDecision] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)


class AgentToolRuntime:
    """Domain-scoped tool planning and bounded execution for one Worker run."""

    def __init__(
        self,
        *,
        agent_name: str,
        allowed_tools: list[str],
        request: ChatRequest,
        registry: ToolRegistry,
        executor: ToolExecutor | None = None,
        decision_agent: ToolDecisionAgent | None = None,
        step_slots: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        step_id: str | None = None,
        trace_id: str | None = None,
        cancellation_check: CancellationCheck | None = None,
        max_parallel_calls: int = 3,
        max_rounds: int = 3,
        max_total_calls: int = 8,
        approved_call_ids: set[str] | None = None,
    ) -> None:
        self.agent_name = agent_name
        self.allowed_tools = list(dict.fromkeys(allowed_tools))
        self.request = request
        self.registry = registry
        self.executor = executor or ToolExecutor(registry=registry)
        self.decision_agent = decision_agent or ToolDecisionAgent(agent_name)
        self.step_slots = step_slots or {}
        self.workflow_id = workflow_id
        self.step_id = step_id
        self.trace_id = trace_id
        self.cancellation_check = cancellation_check
        self.max_parallel_calls = max_parallel_calls
        self.max_rounds = max_rounds
        self.max_total_calls = max_total_calls
        self.approved_call_ids = approved_call_ids or set()
        self._batch: ToolExecutionBatch | None = None

    async def run(self, business_context: dict[str, Any]) -> ToolExecutionBatch:
        if self._batch is not None:
            return self._batch
        batch = ToolExecutionBatch()
        explicit_calls = _extract_explicit_calls(self.request, self.step_slots)
        executed_keys: set[str] = set()
        for round_index in range(1, self.max_rounds + 1):
            if round_index == 1 and explicit_calls:
                decision = AgentToolDecision(
                    action="call_tools",
                    reason="Explicit structured tool calls were supplied.",
                    tool_calls=explicit_calls,
                )
            else:
                decision = await self.decision_agent.decide(
                    message=self.request.message,
                    business_context=business_context,
                    tools=self._allowed_specs(),
                    tool_statuses=self._allowed_statuses(),
                    previous_results=batch.results,
                    round_index=round_index,
                )
            batch.decisions.append(decision)
            batch.missing_information.extend(decision.missing_information)
            if decision.action != "call_tools":
                break
            pending = []
            for call in decision.tool_calls:
                if call.tool_name not in self.allowed_tools:
                    continue
                key = _call_key(call.tool_name, call.arguments)
                if key in executed_keys:
                    continue
                executed_keys.add(key)
                pending.append(call)
                if len(executed_keys) >= self.max_total_calls:
                    break
            if not pending:
                break
            batch.results.extend(await self._execute_parallel(pending))
            if len(executed_keys) >= self.max_total_calls:
                break
        batch.missing_information = list(dict.fromkeys(batch.missing_information))
        self._batch = batch
        return batch

    def _allowed_specs(self):
        specs = []
        for name in self.allowed_tools:
            tool = self.registry.get(name)
            if tool is not None:
                specs.append(tool.spec)
        return specs

    def _allowed_statuses(self) -> dict[str, dict[str, Any]]:
        allowed = set(self.allowed_tools)
        return {
            status.name: status.model_dump(mode="json")
            for status in self.registry.list_availability()
            if status.name in allowed
        }

    async def _execute_parallel(self, calls: list[ToolCallDraft]) -> list[ToolCallResult]:
        semaphore = asyncio.Semaphore(self.max_parallel_calls)

        async def execute(call: ToolCallDraft) -> ToolCallResult:
            async with semaphore:
                if self.cancellation_check is not None:
                    await self.cancellation_check()
                return await self._execute_one(call)

        protected_levels = {PermissionLevel.SEND, PermissionLevel.DELETE, PermissionLevel.PAY}
        results: dict[int, ToolCallResult] = {}
        parallel_calls = [
            (index, call)
            for index, call in enumerate(calls)
            if self.registry.get(call.tool_name) is None
            or self.registry.get(call.tool_name).spec.permission_level not in protected_levels
        ]
        if parallel_calls:
            parallel_results = await asyncio.gather(*(execute(call) for _, call in parallel_calls))
            results.update(
                (index, result)
                for (index, _), result in zip(parallel_calls, parallel_results, strict=True)
            )
        for index, call in enumerate(calls):
            tool = self.registry.get(call.tool_name)
            if tool is None or tool.spec.permission_level not in protected_levels:
                continue
            results[index] = await execute(call)
        return [results[index] for index in sorted(results)]

    async def _execute_one(self, call: ToolCallDraft) -> ToolCallResult:
        tool = self.registry.get(call.tool_name)
        cache_key = _call_key(call.tool_name, call.arguments)
        if (
            tool is not None
            and tool.spec.cache_ttl_seconds > 0
            and tool.spec.permission_level in {PermissionLevel.READ, PermissionLevel.SEARCH}
        ):
            cached = await _cache_get(cache_key, ttl_seconds=tool.spec.cache_ttl_seconds)
            if cached is not None:
                return cached.model_copy(update={"call_id": call.call_id, "cached": True})
        request = ToolCallRequest(
            call_id=call.call_id,
            tool_name=call.tool_name,
            arguments=call.arguments,
            approved=call.approved and call.call_id in self.approved_call_ids,
            idempotency_key=_idempotency_key(
                self.workflow_id,
                self.step_id,
                call.tool_name,
                call.arguments,
            ),
            user_id=self.request.user_id,
            conversation_id=self.request.conversation_id,
            trace_id=self.trace_id,
        )
        result = await self.executor.run(request)
        if (
            tool is not None
            and result.success
            and not result.degraded
            and tool.spec.cache_ttl_seconds > 0
            and tool.spec.permission_level in {PermissionLevel.READ, PermissionLevel.SEARCH}
        ):
            await _cache_put(cache_key, result)
        return result


def _extract_explicit_calls(request: ChatRequest, slots: dict[str, Any]) -> list[ToolCallDraft]:
    calls: list[ToolCallDraft] = []
    for source in (
        request.agent_inputs.get("tool_calls", {}),
        request.agent_inputs.get("tools", {}),
        slots.get("tool_calls", {}),
        slots.get("tools", {}),
    ):
        if isinstance(source, list):
            for item in source:
                if isinstance(item, dict):
                    calls.append(ToolCallDraft.model_validate(item))
        elif isinstance(source, dict):
            for name, payload in source.items():
                if isinstance(payload, dict):
                    arguments = dict(payload)
                    approved = bool(arguments.pop("approved", False))
                    calls.append(ToolCallDraft(tool_name=name, arguments=arguments, approved=approved))
    by_key = {_call_key(call.tool_name, call.arguments): call for call in calls}
    return list(by_key.values())


def _call_key(tool_name: str, arguments: dict[str, Any]) -> str:
    encoded = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return f"{tool_name}:{encoded}"


def _idempotency_key(
    workflow_id: str | None,
    step_id: str | None,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    raw = f"{workflow_id or 'sync'}:{step_id or 'none'}:{_call_key(tool_name, arguments)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _cache_get(key: str, *, ttl_seconds: int = 60) -> ToolCallResult | None:
    async with _CACHE_LOCK:
        cached = _RESULT_CACHE.get(key)
        if cached is None:
            return None
        created_at, result = cached
        if datetime.now(UTC) - created_at > timedelta(seconds=ttl_seconds):
            _RESULT_CACHE.pop(key, None)
            return None
        return result


async def _cache_put(key: str, result: ToolCallResult) -> None:
    async with _CACHE_LOCK:
        if len(_RESULT_CACHE) >= 512:
            oldest = min(_RESULT_CACHE, key=lambda item: _RESULT_CACHE[item][0])
            _RESULT_CACHE.pop(oldest, None)
        _RESULT_CACHE[key] = (datetime.now(UTC), result)
