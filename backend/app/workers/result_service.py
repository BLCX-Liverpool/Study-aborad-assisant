from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator.workers import WorkerRunResult
from app.db.models import AgentRun, RunStatus, TraceSpan, WorkflowRun, WorkflowStep
from app.messaging.dispatcher import OutboxDispatcher
from app.schemas.messages import AgentStepEvent, AgentTaskCommand, ArtifactCreatedEvent
from app.workflows.repository import InboxRepository, WorkflowRepository
from app.workflows.state_machine import StepStatus, WorkflowStatus


RETRY_DELAYS_SECONDS = (10, 30, 120)


def retry_delay_seconds(attempt_count: int) -> int:
    return RETRY_DELAYS_SECONDS[min(max(attempt_count - 1, 0), len(RETRY_DELAYS_SECONDS) - 1)]


class WorkerResultService:
    def __init__(self, session: AsyncSession, *, consumer_name: str, worker_id: str | None = None) -> None:
        self.session = session
        self.consumer_name = consumer_name
        self.repository = WorkflowRepository(session)
        self.inbox = InboxRepository(session)
        self.dispatcher = OutboxDispatcher(session)
        self.worker_id = worker_id

    async def persist_success(
        self,
        *,
        command: AgentTaskCommand,
        workflow: WorkflowRun,
        step: WorkflowStep,
        result: WorkerRunResult,
    ) -> None:
        artifacts = await self.repository.add_artifacts(
            workflow=workflow,
            step=step,
            artifacts=result.artifacts,
        )
        for artifact in artifacts:
            artifact_event = ArtifactCreatedEvent(
                workflow_id=workflow.id,
                step_id=step.id,
                artifact_id=artifact.id,
                artifact_kind=artifact.kind,
                trace_id=workflow.trace_id,
                causation_id=command.message_id,
            )
            await self.dispatcher.dispatch(
                aggregate_type="artifact",
                aggregate_id=artifact.id,
                routing_key="artifact.created",
                message=artifact_event,
            )
        if result.missing_information:
            target = StepStatus.NEEDS_INPUT
            event_type = "agent.step.needs_input"
            await self.repository.transition_step(
                step,
                target,
                result_summary=result.final_response,
                missing_information_json=result.missing_information,
            )
            if workflow.status == WorkflowStatus.RUNNING.value:
                await self.repository.transition_workflow(workflow, WorkflowStatus.WAITING_INPUT)
        else:
            target = StepStatus.COMPLETED
            event_type = "agent.step.completed"
            await self.repository.transition_step(
                step,
                target,
                result_summary=result.final_response,
                missing_information_json=[],
            )
        await self._finish_attempt(
            command=command,
            workflow=workflow,
            step=step,
            status=RunStatus.COMPLETED,
            output_json={
                "final_response": result.final_response,
                "artifact_ids": [artifact.id for artifact in artifacts],
                "missing_information": result.missing_information,
                "next_actions": result.next_actions,
                "trace_events": result.trace_events,
            },
        )
        event = AgentStepEvent(
            message_type=event_type,
            workflow_id=workflow.id,
            step_id=step.id,
            agent=step.agent_intent,
            artifact_ids=[artifact.id for artifact in artifacts],
            trace_id=workflow.trace_id,
            causation_id=command.message_id,
            attempt=step.attempt_count,
            result_summary=result.final_response,
            missing_information=result.missing_information,
            completed_at=datetime.now(UTC),
            worker_instance_id=self.worker_id,
        )
        await self.dispatcher.dispatch(
            aggregate_type="workflow_step",
            aggregate_id=step.id,
            routing_key=event_type,
            message=event,
        )
        await self.inbox.complete(self.consumer_name, command.message_id)
        await self.session.commit()

    async def persist_failure(
        self,
        *,
        command: AgentTaskCommand,
        workflow: WorkflowRun,
        step: WorkflowStep,
        error: Exception,
        retryable: bool,
    ) -> None:
        exhausted = step.attempt_count >= step.max_attempts
        if retryable and not exhausted:
            delay = retry_delay_seconds(step.attempt_count)
            target = StepStatus.RETRY_WAIT
            event_type = "agent.step.retry_scheduled"
            await self.repository.transition_step(
                step,
                target,
                available_at=datetime.now(UTC) + timedelta(seconds=delay),
                last_error_code=type(error).__name__,
                last_error_message=str(error)[:4000],
            )
        else:
            target = StepStatus.DEAD_LETTERED if exhausted else StepStatus.FAILED
            event_type = "agent.step.dead_lettered" if exhausted else "agent.step.failed"
            await self.repository.transition_step(
                step,
                target,
                last_error_code=type(error).__name__,
                last_error_message=str(error)[:4000],
            )
        await self._finish_attempt(
            command=command,
            workflow=workflow,
            step=step,
            status=RunStatus.FAILED,
            error=str(error)[:4000],
        )
        event = AgentStepEvent(
            message_type=event_type,
            workflow_id=workflow.id,
            step_id=step.id,
            agent=step.agent_intent,
            trace_id=workflow.trace_id,
            causation_id=command.message_id,
            attempt=step.attempt_count,
            error_code=type(error).__name__,
            error_message=str(error)[:4000],
            worker_instance_id=self.worker_id,
        )
        await self.dispatcher.dispatch(
            aggregate_type="workflow_step",
            aggregate_id=step.id,
            routing_key=event_type,
            message=event,
        )
        await self.inbox.complete(self.consumer_name, command.message_id)
        await self.session.commit()

    async def persist_cancelled(
        self,
        *,
        command: AgentTaskCommand,
        workflow: WorkflowRun,
        step: WorkflowStep,
    ) -> None:
        if step.status == StepStatus.RUNNING.value:
            await self.repository.transition_step(step, StepStatus.CANCELLED)
        await self._finish_attempt(
            command=command,
            workflow=workflow,
            step=step,
            status=RunStatus.CANCELLED,
            error="Workflow cancellation requested",
        )
        event = AgentStepEvent(
            message_type="agent.step.cancelled",
            workflow_id=workflow.id,
            step_id=step.id,
            agent=step.agent_intent,
            trace_id=workflow.trace_id,
            causation_id=command.message_id,
            attempt=step.attempt_count,
            error_code="workflow_cancelled",
            error_message="Workflow cancellation requested",
            completed_at=datetime.now(UTC),
            worker_instance_id=self.worker_id,
        )
        await self.dispatcher.dispatch(
            aggregate_type="workflow_step",
            aggregate_id=step.id,
            routing_key="agent.step.cancelled",
            message=event,
        )
        await self.inbox.complete(self.consumer_name, command.message_id)
        await self.session.commit()

    async def _finish_attempt(
        self,
        *,
        command: AgentTaskCommand,
        workflow: WorkflowRun,
        step: WorkflowStep,
        status: RunStatus,
        output_json: dict | None = None,
        error: str | None = None,
    ) -> None:
        result = await self.session.execute(
            select(AgentRun).where(
                AgentRun.workflow_id == workflow.id,
                AgentRun.step_id == step.id,
                AgentRun.attempt == step.attempt_count,
            )
        )
        attempt = result.scalars().first()
        if attempt is None:
            attempt = AgentRun(
                user_id=workflow.user_id,
                conversation_id=workflow.conversation_id,
                trace_id=workflow.trace_id,
                workflow_id=workflow.id,
                step_id=step.id,
                attempt=step.attempt_count,
                idempotency_key=f"{workflow.id}:{step.id}:{step.attempt_count}",
                agent_name=step.agent_intent,
                input_json={"command": command.model_dump(mode="json")},
                started_at=step.started_at,
            )
            self.session.add(attempt)
        attempt.status = status
        attempt.output_json = output_json
        attempt.error = error
        attempt.completed_at = datetime.now(UTC)
        started_at = attempt.started_at or step.started_at or attempt.completed_at
        self.session.add(
            TraceSpan(
                trace_id=workflow.trace_id,
                parent_span_id=command.parent_span_id,
                user_id=workflow.user_id,
                conversation_id=workflow.conversation_id,
                agent_run_id=attempt.id,
                span_name=f"worker.{step.agent_intent}.attempt.{step.attempt_count}",
                span_type="agent_worker",
                status="failed" if status == RunStatus.FAILED else "completed",
                started_at=started_at,
                completed_at=attempt.completed_at,
                duration_ms=max((attempt.completed_at - started_at).total_seconds() * 1000, 0.0),
                input_json={"message_id": command.message_id, "schema_version": command.schema_version},
                output_json=output_json,
                error=error,
                metadata_json={"agent": step.agent_intent, "attempt": step.attempt_count},
            )
        )
