from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentRun, RunStatus, WorkflowStep
from app.workflows.repository import WorkflowRepository
from app.workflows.state_machine import StepStatus
from app.messaging.dispatcher import OutboxDispatcher
from app.schemas.messages import AgentStepEvent


class StaleRunRecovery:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = WorkflowRepository(session)

    async def recover(self, *, limit: int = 100) -> int:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(WorkflowStep)
            .where(
                WorkflowStep.status == StepStatus.RUNNING.value,
                WorkflowStep.lease_expires_at < now,
            )
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        count = 0
        for step in result.scalars().all():
            target = (
                StepStatus.DEAD_LETTERED
                if step.attempt_count >= step.max_attempts
                else StepStatus.RETRY_WAIT
            )
            changed = await self.repository.transition_step(
                step,
                target,
                available_at=now,
                last_error_code="worker_lease_expired",
                last_error_message="Worker lease expired before the task was acknowledged.",
            )
            if changed:
                attempt_result = await self.session.execute(
                    select(AgentRun).where(
                        AgentRun.workflow_id == step.workflow_id,
                        AgentRun.step_id == step.id,
                        AgentRun.attempt == step.attempt_count,
                    )
                )
                attempt = attempt_result.scalars().first()
                if attempt is not None:
                    attempt.status = RunStatus.FAILED
                    attempt.completed_at = now
                    attempt.error = "Worker lease expired before the task was acknowledged."
                workflow = await self.repository.get(step.workflow_id)
                event_type = (
                    "agent.step.dead_lettered"
                    if target == StepStatus.DEAD_LETTERED
                    else "agent.step.retry_scheduled"
                )
                event = AgentStepEvent(
                    message_type=event_type,
                    workflow_id=workflow.id,
                    step_id=step.id,
                    agent=step.agent_intent,
                    trace_id=workflow.trace_id,
                    attempt=step.attempt_count,
                    error_code="worker_lease_expired",
                    error_message="Worker lease expired before the task was acknowledged.",
                )
                await OutboxDispatcher(self.session).dispatch(
                    aggregate_type="workflow_step",
                    aggregate_id=step.id,
                    routing_key=event_type,
                    message=event,
                )
            count += int(changed)
        await self.session.commit()
        return count
