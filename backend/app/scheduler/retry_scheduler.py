from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WorkflowStep
from app.messaging.dispatcher import OutboxDispatcher
from app.messaging.topology import ROUTING_KEY_BY_AGENT
from app.schemas.messages import AgentTaskCommand
from app.workflows.repository import WorkflowRepository
from app.workflows.state_machine import StepStatus


class RetryScheduler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = WorkflowRepository(session)
        self.dispatcher = OutboxDispatcher(session)

    async def dispatch_due(self, *, limit: int = 100) -> int:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(WorkflowStep)
            .where(
                WorkflowStep.status == StepStatus.RETRY_WAIT.value,
                WorkflowStep.available_at <= now,
            )
            .order_by(WorkflowStep.available_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        count = 0
        for step in result.scalars().all():
            workflow = await self.repository.get(step.workflow_id)
            routing_key = ROUTING_KEY_BY_AGENT.get(step.agent_intent)
            if routing_key is None:
                await self.repository.transition_step(step, StepStatus.DEAD_LETTERED)
                continue
            changed = await self.repository.transition_step(
                step,
                StepStatus.QUEUED,
                available_at=None,
            )
            if not changed:
                continue
            command = AgentTaskCommand(
                workflow_id=workflow.id,
                step_id=step.id,
                agent=step.agent_intent,
                trace_id=workflow.trace_id,
                input_ref=step.input_ref or f"workflow-input:{workflow.id}",
                dependency_artifact_ids=await self.repository.dependency_artifact_ids(step.id),
                attempt=step.attempt_count + 1,
            )
            await self.dispatcher.dispatch(
                aggregate_type="workflow_step",
                aggregate_id=step.id,
                routing_key=routing_key,
                message=command,
            )
            count += 1
        await self.session.commit()
        return count
