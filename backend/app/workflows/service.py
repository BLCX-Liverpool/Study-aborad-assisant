from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.db.models import WorkflowRun, WorkflowStep
from app.messaging.dispatcher import OutboxDispatcher
from app.messaging.topology import ROUTING_KEY_BY_AGENT
from app.schemas.chat import ChatRequest
from app.schemas.email import EmailSendRequest
from app.schemas.messages import AgentTaskCommand, WorkflowPrepareCommand
from app.schemas.router import RouterOutput
from app.schemas.workflow import (
    ChatV2Request,
    WorkflowAccepted,
    WorkflowArtifactView,
    WorkflowStepView,
    WorkflowView,
)
from app.workflows.repository import WorkflowRepository
from app.workflows.state_machine import StepStatus, WorkflowStatus


SYNC_INTENTS = {
    "general_chat",
    "wellbeing",
    "clarification_required",
    "chitchat",
    "out_of_scope",
    "unsafe_request",
    "system_command",
    "unknown",
}


class ExecutionPolicy:
    def __init__(self, async_intents: set[str] | None = None) -> None:
        from app.core.config import get_settings

        self.settings = get_settings()
        self.async_intents = async_intents or set(self.settings.async_intents)

    def choose(self, router_output: RouterOutput, request: ChatV2Request) -> str:
        if not self.settings.rabbitmq_workflow_enabled:
            return "sync"
        if router_output.primary_intent in SYNC_INTENTS:
            return "sync"
        if request.execution_mode == "async":
            return "async"
        long_running = (
            bool(request.uploaded_file_ids)
            or len(router_output.structured_intents) > 1
            or router_output.needs_file_parsing
            or router_output.primary_intent in self.async_intents
        )
        if request.execution_mode == "sync" and long_running:
            return "async"
        if not long_running:
            return "sync"
        if request.user_id in self.settings.async_user_allowlist:
            return "async"
        bucket = int(hashlib.sha256(request.user_id.encode("utf-8")).hexdigest()[:8], 16) % 100
        return "async" if bucket < self.settings.async_rollout_percentage else "sync"


class WorkflowService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = WorkflowRepository(session)
        self.dispatcher = OutboxDispatcher(session)

    async def create_chat_workflow(
        self,
        request: ChatRequest,
        *,
        request_id: str,
        router_output: RouterOutput | None = None,
    ) -> WorkflowAccepted:
        existing = await self.repository.get_by_request_id(
            user_id=request.user_id,
            request_id=request_id,
        )
        if existing is not None:
            return accepted_view(existing)

        conversation_id = request.conversation_id or str(uuid4())
        trace_id = str(uuid4())
        input_json = {
            "chat_request": request.model_copy(update={"conversation_id": conversation_id}).model_dump(mode="json"),
            "router_output": router_output.model_dump(mode="json") if router_output else None,
        }
        try:
            async with self.session.begin_nested():
                workflow = await self.repository.create(
                    user_id=request.user_id,
                    conversation_id=conversation_id,
                    trace_id=trace_id,
                    request_id=request_id,
                    workflow_type="chat",
                    input_json=input_json,
                )
        except IntegrityError:
            existing = await self.repository.get_by_request_id(
                user_id=request.user_id,
                request_id=request_id,
            )
            if existing is None:
                raise
            return accepted_view(existing)
        command = WorkflowPrepareCommand(
            workflow_id=workflow.id,
            trace_id=trace_id,
            input_ref=f"workflow-input:{workflow.id}",
        )
        await self.dispatcher.dispatch(
            aggregate_type="workflow",
            aggregate_id=workflow.id,
            routing_key="workflow.prepare",
            message=command,
        )
        await self.session.commit()
        return accepted_view(workflow)

    async def create_email_send_workflow(
        self,
        request: EmailSendRequest,
        *,
        request_id: str,
    ) -> WorkflowAccepted:
        existing = await self.repository.get_by_request_id(
            user_id=request.user_id,
            request_id=request_id,
        )
        if existing is not None:
            return accepted_view(existing)
        conversation_id = f"email-send:{request_id}"
        try:
            async with self.session.begin_nested():
                workflow = await self.repository.create(
                    user_id=request.user_id,
                    conversation_id=conversation_id,
                    trace_id=str(uuid4()),
                    request_id=request_id,
                    workflow_type="email_send",
                    input_json={
                        "chat_request": ChatRequest(
                            user_id=request.user_id,
                            conversation_id=conversation_id,
                            message=f"Send approved email to {request.to_email}",
                            agent_inputs={"email_send": request.model_dump(mode="json")},
                        ).model_dump(mode="json"),
                        "router_output": None,
                    },
                )
        except IntegrityError:
            existing = await self.repository.get_by_request_id(
                user_id=request.user_id,
                request_id=request_id,
            )
            if existing is None:
                raise
            return accepted_view(existing)
        await self.repository.transition_workflow(workflow, WorkflowStatus.PLANNING)
        step = (await self.repository.create_steps(
            workflow.id,
            [
                {
                    "index": 0,
                    "intent_name": "email.send",
                    "agent_intent": "email_send",
                    "status": "planned",
                    "slots": request.model_dump(mode="json"),
                    "max_attempts": 4,
                }
            ],
        ))[0]
        stable_key = f"email:{workflow.id}:{step.id}:{request.to_email}"
        payload = request.model_copy(update={"idempotency_key": stable_key}).model_dump(mode="json")
        workflow.input_json = {
            **workflow.input_json,
            "chat_request": {
                **workflow.input_json["chat_request"],
                "agent_inputs": {"email_send": payload},
            },
        }
        step.input_json = payload
        workflow.plan_json = {
            "router": None,
            "execution_plan": {"steps": [{"step_id": step.id, "agent_intent": "email_send"}]},
            "memory_context": None,
        }
        await self.repository.transition_workflow(workflow, WorkflowStatus.RUNNING)
        await self.enqueue_step(workflow, step)
        await self.session.commit()
        return accepted_view(workflow)

    async def queue_ready_steps(self, workflow: WorkflowRun) -> list[WorkflowStep]:
        queued: list[WorkflowStep] = []
        for step in await self.repository.ready_steps(workflow.id):
            if await self.enqueue_step(workflow, step):
                queued.append(step)
        return queued

    async def enqueue_step(self, workflow: WorkflowRun, step: WorkflowStep) -> bool:
        routing_key = ROUTING_KEY_BY_AGENT.get(step.agent_intent)
        if routing_key is None:
            await self.repository.transition_step(
                step,
                StepStatus.FAILED,
                last_error_code="unsupported_agent",
                last_error_message=f"No RabbitMQ routing key for {step.agent_intent}",
            )
            return False
        changed = await self.repository.transition_step(step, StepStatus.QUEUED)
        if not changed:
            return False
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
            headers={"attempt": command.attempt},
        )
        return True

    async def view(self, workflow_id: str, *, user_id: str) -> WorkflowView:
        workflow = await self.repository.get(workflow_id, user_id=user_id)
        steps = await self.repository.list_steps(workflow.id)
        return workflow_view(workflow, steps)


def accepted_view(workflow: WorkflowRun) -> WorkflowAccepted:
    return WorkflowAccepted(
        workflow_id=workflow.id,
        trace_id=workflow.trace_id,
        status=workflow.status,
        status_url=f"/api/workflows/{workflow.id}",
        events_url=f"/api/workflows/{workflow.id}/events",
    )


def workflow_view(workflow: WorkflowRun, steps: list[WorkflowStep]) -> WorkflowView:
    terminal = {"completed", "needs_input", "failed", "dead_lettered", "cancelled"}
    progress = 0 if not steps else round(100 * len([step for step in steps if step.status in terminal]) / len(steps))
    return WorkflowView(
        id=workflow.id,
        user_id=workflow.user_id,
        conversation_id=workflow.conversation_id,
        trace_id=workflow.trace_id,
        request_id=workflow.request_id,
        workflow_type=workflow.workflow_type,
        status=workflow.status,
        final_response=workflow.final_response,
        error_code=workflow.error_code,
        error_message=workflow.error_message,
        version=workflow.version,
        progress=progress,
        created_at=workflow.created_at,
        updated_at=workflow.updated_at,
        started_at=workflow.started_at,
        completed_at=workflow.completed_at,
        steps=[
            WorkflowStepView(
                id=step.id,
                step_key=step.step_key,
                intent_name=step.intent_name,
                agent_intent=step.agent_intent,
                status=step.status,
                attempt_count=step.attempt_count,
                max_attempts=step.max_attempts,
                result_summary=step.result_summary,
                missing_information=step.missing_information_json or [],
                available_at=step.available_at,
                queued_at=step.queued_at,
                started_at=step.started_at,
                completed_at=step.completed_at,
                last_error_code=step.last_error_code,
                last_error_message=step.last_error_message,
            )
            for step in steps
        ],
    )


def artifact_view(record) -> WorkflowArtifactView:
    return WorkflowArtifactView(
        id=record.id,
        step_id=record.step_id,
        name=record.name,
        kind=record.kind,
        schema_version=record.schema_version,
        payload=record.payload_json,
        # Never expose an internal filesystem/object-store URI through the API.
        storage_uri=None,
        checksum=record.checksum,
        size_bytes=record.size_bytes,
        created_at=record.created_at,
    )
