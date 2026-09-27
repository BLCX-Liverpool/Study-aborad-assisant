from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tracing import LatencySpan
from app.db.models import AgentRun, RouterObservation, RunStatus, TraceSpan
from app.schemas.router import RouterOutput


class AgentRunRecorder:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_completed_run(
        self,
        *,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        agent_name: str,
        router_output: RouterOutput,
        input_json: dict,
        output_json: dict,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> str:
        now = datetime.now(UTC)
        run = AgentRun(
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            agent_name=agent_name,
            input_json={
                "router": router_output.model_dump(),
                **input_json,
            },
            output_json=output_json,
            status=RunStatus.COMPLETED,
            started_at=started_at or now,
            completed_at=completed_at or now,
        )
        self.session.add(run)
        await self.session.commit()
        return run.id


class RouterObservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        user_id: str,
        conversation_id: str | None,
        trace_id: str,
        message: str,
        router_output: RouterOutput,
    ) -> str:
        observation = RouterObservation(
            id=str(uuid4()),
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            message=message,
            primary_intent=router_output.primary_intent,
            confidence=router_output.confidence,
            structured_intents_json=[
                intent.model_dump(mode="json") for intent in router_output.structured_intents
            ],
            fusion_metadata_json=router_output.fusion_metadata.model_dump(mode="json"),
            clarification_questions_json=router_output.clarification_questions,
        )
        self.session.add(observation)
        await self.session.flush()
        await self.session.commit()
        return observation.id


class TraceSpanRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record_many(self, spans: list[LatencySpan], *, commit: bool = True) -> int:
        for span in spans:
            self.session.add(
                TraceSpan(
                    id=span.span_id,
                    trace_id=span.trace_id,
                    parent_span_id=span.parent_span_id,
                    user_id=span.user_id,
                    conversation_id=span.conversation_id,
                    agent_run_id=span.agent_run_id,
                    span_name=span.span_name,
                    span_type=span.span_type,
                    status=span.status,
                    started_at=span.started_at,
                    completed_at=span.completed_at,
                    duration_ms=span.duration_ms,
                    input_json=span.input_json,
                    output_json=span.output_json,
                    error=span.error,
                    metadata_json=span.metadata_json,
                )
            )
        await self.session.flush()
        if commit:
            await self.session.commit()
        return len(spans)
