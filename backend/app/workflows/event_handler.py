from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.messaging.dispatcher import OutboxDispatcher
from app.schemas.messages import AgentStepEvent, WorkflowCompletedEvent
from app.schemas.chat import ChatRequest
from app.schemas.router import RouterOutput
from app.memory.manager import MemoryManager
from app.workflows.repository import InboxRepository, WorkflowRepository
from app.workflows.service import WorkflowService
from app.workflows.state_machine import StepStatus, WorkflowStatus


TERMINAL_STEP_STATUSES = {
    StepStatus.COMPLETED.value,
    StepStatus.FAILED.value,
    StepStatus.DEAD_LETTERED.value,
    StepStatus.CANCELLED.value,
}


class WorkflowEventHandler:
    def __init__(
        self,
        session: AsyncSession,
        *,
        consumer_name: str = "study.orchestrator.events.q",
        memory_manager: MemoryManager | None = None,
    ) -> None:
        self.session = session
        self.consumer_name = consumer_name
        self.repository = WorkflowRepository(session)
        self.inbox = InboxRepository(session)
        self.dispatcher = OutboxDispatcher(session)
        self.memory_manager = memory_manager

    async def handle(self, event: AgentStepEvent) -> None:
        is_new = await self.inbox.begin(
            consumer_name=self.consumer_name,
            message_id=event.message_id,
            workflow_id=event.workflow_id,
            step_id=event.step_id,
        )
        if not is_new:
            await self.session.rollback()
            return
        workflow = await self.repository.get(event.workflow_id)

        if event.message_type == "agent.step.completed" and workflow.status == WorkflowStatus.RUNNING.value:
            await WorkflowService(self.session).queue_ready_steps(workflow)
        elif event.message_type == "agent.step.needs_input":
            if workflow.status == WorkflowStatus.RUNNING.value:
                await self.repository.transition_workflow(workflow, WorkflowStatus.WAITING_INPUT)

        await self.repository.cancel_blocked_steps(workflow.id)
        await self._finalize_if_ready(workflow)
        await self.inbox.complete(self.consumer_name, event.message_id)
        await self.session.commit()

    async def _finalize_if_ready(self, workflow) -> None:
        steps = await self.repository.list_steps(workflow.id)
        if not steps:
            return
        if any(step.status == StepStatus.NEEDS_INPUT.value for step in steps):
            if workflow.status == WorkflowStatus.RUNNING.value:
                await self.repository.transition_workflow(workflow, WorkflowStatus.WAITING_INPUT)
            return
        if any(step.status not in TERMINAL_STEP_STATUSES for step in steps):
            return
        if workflow.status == WorkflowStatus.CANCEL_REQUESTED.value:
            await self.repository.transition_workflow(workflow, WorkflowStatus.CANCELLED)
            return
        failed = [step for step in steps if step.status in {StepStatus.FAILED.value, StepStatus.DEAD_LETTERED.value}]
        completed = [step for step in steps if step.status == StepStatus.COMPLETED.value]
        workflow.final_response = "\n\n".join(
            step.result_summary for step in completed if step.result_summary
        ) or None
        if failed and completed:
            target = WorkflowStatus.PARTIAL_FAILED
        elif failed:
            target = (
                WorkflowStatus.DEAD_LETTERED
                if any(step.status == StepStatus.DEAD_LETTERED.value for step in failed)
                else WorkflowStatus.FAILED
            )
        else:
            target = WorkflowStatus.COMPLETED
        if workflow.status in {
            WorkflowStatus.RUNNING.value,
            WorkflowStatus.WAITING_INPUT.value,
        }:
            await self.repository.transition_workflow(workflow, target)
        if target == WorkflowStatus.COMPLETED:
            router_json = (workflow.plan_json or {}).get("router")
            if self.memory_manager is not None and router_json:
                request = ChatRequest.model_validate(workflow.input_json["chat_request"])
                router_output = RouterOutput.model_validate(router_json)
                await self.memory_manager.update_after_response(
                    request=request,
                    conversation_id=workflow.conversation_id,
                    response_text=workflow.final_response or "",
                    router_output=router_output,
                    topic_summary=None,
                    commit=False,
                )
            artifacts = await self.repository.list_artifacts(workflow.id)
            event = WorkflowCompletedEvent(
                workflow_id=workflow.id,
                trace_id=workflow.trace_id,
                artifact_ids=[artifact.id for artifact in artifacts],
                completed_at=datetime.now(UTC),
            )
            await self.dispatcher.dispatch(
                aggregate_type="workflow",
                aggregate_id=workflow.id,
                routing_key="workflow.completed",
                message=event,
            )
