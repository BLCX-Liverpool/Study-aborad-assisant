from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, RunStatus, ToolRun, TraceSpan
from app.tools.models import ToolCallRequest, ToolCallResult


class ToolExecutionLogger:
    def __init__(self, session: AsyncSession | None = None) -> None:
        self.session = session

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
        agent_run = AgentRun(
            id=str(uuid4()),
            user_id=request.user_id or "anonymous",
            conversation_id=request.conversation_id,
            trace_id=trace_id,
            agent_name="tool_executor",
            input_json={"tool_name": request.tool_name, "arguments": request.arguments},
            output_json=result.model_dump(mode="json"),
            status=RunStatus.COMPLETED if result.success else RunStatus.FAILED,
            started_at=started_at,
            completed_at=completed_at,
        )
        self.session.add(agent_run)
        tool_run = ToolRun(
            agent_run_id=agent_run.id,
            tool_name=request.tool_name,
            permission_level=str(result.permission_level or ""),
            input_json=request.arguments,
            output_json=result.output,
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
                agent_run_id=agent_run.id,
                span_name=f"tool.{request.tool_name}",
                span_type="tool",
                status="completed" if result.success else "failed",
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round(duration_ms, 3),
                input_json=request.arguments,
                output_json=result.output,
                error=result.error,
                metadata_json={
                    "permission_level": str(result.permission_level or ""),
                    "requires_approval": result.requires_approval,
                },
            )
        )
        await self.session.flush()
        return tool_run.id
