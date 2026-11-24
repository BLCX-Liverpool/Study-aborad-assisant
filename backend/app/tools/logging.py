import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, RunStatus, ToolRun, TraceSpan
from app.tools.models import ToolCallRequest, ToolCallResult


class ToolExecutionLogger:
    def __init__(self, session: AsyncSession | None = None, *, agent_run_id: str | None = None) -> None:
        self.session = session
        self.agent_run_id = agent_run_id

    async def log(
        self,
        request: ToolCallRequest,
        result: ToolCallResult,
        *,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        duration_ms: float | None = None,
    ) -> str | None:
        if self.session is None:
            return None
        now = datetime.now(UTC)
        started_at = started_at or now
        completed_at = completed_at or now
        if duration_ms is None:
            duration_ms = max((completed_at - started_at).total_seconds() * 1000, 0.0)
        trace_id = request.trace_id or str(uuid4())
        logged_output = _logged_output(request.tool_name, result.output)
        result_count = _result_count(result.output)
        output_size_bytes = len(json.dumps(result.output, ensure_ascii=False, default=str).encode("utf-8"))
        agent_run = None
        agent_run_id = self.agent_run_id
        if agent_run_id is None:
            agent_run = AgentRun(
                id=str(uuid4()),
                user_id=request.user_id or "anonymous",
                conversation_id=request.conversation_id,
                trace_id=trace_id,
                agent_name="tool_executor",
                input_json={"tool_name": request.tool_name, "arguments": request.arguments},
                output_json={
                    **result.model_dump(mode="json", exclude={"output"}),
                    "output": logged_output,
                },
                status=RunStatus.COMPLETED if result.success else RunStatus.FAILED,
                started_at=started_at,
                completed_at=completed_at,
                idempotency_key=request.idempotency_key,
            )
            self.session.add(agent_run)
            agent_run_id = agent_run.id
        tool_run = ToolRun(
            agent_run_id=agent_run_id,
            tool_name=request.tool_name,
            permission_level=str(result.permission_level or ""),
            input_json=request.arguments,
            output_json=logged_output,
            status=RunStatus.COMPLETED if result.success else RunStatus.FAILED,
            started_at=started_at,
            completed_at=completed_at,
            error=result.error,
        )
        self.session.add(tool_run)
        self.session.add(
            TraceSpan(
                trace_id=trace_id,
                user_id=request.user_id,
                conversation_id=request.conversation_id,
                agent_run_id=agent_run_id,
                span_name=f"tool.{request.tool_name}",
                span_type="tool",
                status="completed" if result.success else "failed",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round(duration_ms, 3),
                input_json=request.arguments,
                output_json=logged_output,
                error=result.error,
                metadata_json={
                    "permission_level": str(result.permission_level or ""),
                    "requires_approval": result.requires_approval,
                    "call_id": request.call_id,
                    "idempotency_key": request.idempotency_key,
                    "attempts": result.attempts,
                    "degraded": result.degraded,
                    "cached": result.cached,
                    "provider": result.output.get("provider"),
                    "remote_tool": result.output.get("remote_tool"),
                    "result_count": result_count,
                    "output_size_bytes": output_size_bytes,
                },
            )
        )
        await self.session.flush()
        return tool_run.id


def _logged_output(tool_name: str, output: dict[str, Any]) -> dict[str, Any]:
    if not tool_name.startswith("browser.mcp."):
        return output
    keys = {
        "provider_status",
        "provider",
        "source",
        "remote_tool",
        "provider_metadata",
        "query",
        "base_url",
        "recoverable_error",
        "retryable",
        "retry_after_seconds",
        "deprecated",
        "compatibility_tool",
    }
    return {
        **{key: value for key, value in output.items() if key in keys},
        "result_count": _result_count(output),
        "content_omitted_from_log": True,
    }


def _result_count(output: dict[str, Any]) -> int:
    for key in ("results", "pages", "urls"):
        value = output.get(key)
        if isinstance(value, list):
            return len(value)
    return 0
