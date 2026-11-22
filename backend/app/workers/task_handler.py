from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import openai
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator.workers import WorkerRegistry
from app.agents.orchestrator.workers import WorkerRunResult
from app.agents.email.repository import EmailSendAuditRepository
from app.agents.email.service import EmailAgentService
from app.db.models import AgentRun, Reminder, ReminderStatus, RunStatus, User, WorkflowRun
from app.schemas.email import EmailSendRequest
from app.schemas.chat import AgentArtifact
from app.core.config import get_settings
from app.schemas.messages import AgentTaskCommand
from app.schemas.messages import AgentStepEvent
from app.messaging.dispatcher import OutboxDispatcher
from app.workflows.repository import InboxRepository, WorkflowRepository
from app.workflows.state_machine import StepStatus, WorkflowStatus
from app.workers.context_loader import WorkerContextLoader
from app.workers.result_service import WorkerResultService
from app.workers.heartbeat import StepLeaseHeartbeat


class WorkerTaskHandler:
    def __init__(
        self,
        session: AsyncSession,
        *,
        consumer_name: str,
        registry: WorkerRegistry | None = None,
        worker_id: str | None = None,
    ) -> None:
        self.session = session
        self.consumer_name = consumer_name
        self.registry = registry or WorkerRegistry()
        self.worker_id = worker_id or f"{consumer_name}:{uuid4()}"
        self.repository = WorkflowRepository(session)
        self.inbox = InboxRepository(session)

    async def handle(self, command: AgentTaskCommand) -> None:
        is_new = await self.inbox.begin(
            consumer_name=self.consumer_name,
            message_id=command.message_id,
            workflow_id=command.workflow_id,
            step_id=command.step_id,
        )
        if not is_new:
            await self.session.rollback()
            return
        workflow = await self.repository.get(command.workflow_id)
        step = await self.repository.get_step(command.step_id, workflow_id=workflow.id)
        if workflow.status in {WorkflowStatus.CANCEL_REQUESTED.value, WorkflowStatus.CANCELLED.value}:
            if step.status in {StepStatus.QUEUED.value, StepStatus.PENDING.value, StepStatus.RETRY_WAIT.value}:
                await self.repository.transition_step(step, StepStatus.CANCELLED)
            await self.inbox.complete(self.consumer_name, command.message_id)
            await self.session.commit()
            return
        if step.status != StepStatus.QUEUED.value:
            await self.inbox.complete(self.consumer_name, command.message_id)
            await self.session.commit()
            return
        claimed = await self.repository.claim_step(
            step,
            worker_id=self.worker_id,
            lease_seconds=get_settings().workflow_lease_seconds,
        )
        if not claimed:
            await self.session.rollback()
            return
        self.session.add(
            AgentRun(
                user_id=workflow.user_id,
                conversation_id=workflow.conversation_id,
                trace_id=workflow.trace_id,
                workflow_id=workflow.id,
                step_id=step.id,
                attempt=step.attempt_count,
                idempotency_key=f"{workflow.id}:{step.id}:{step.attempt_count}",
                agent_name=step.agent_intent,
                input_json={"command": command.model_dump(mode="json")},
                status=RunStatus.IN_PROGRESS,
                started_at=step.started_at,
            )
        )
        started_event = AgentStepEvent(
            message_type="agent.step.started",
            workflow_id=workflow.id,
            step_id=step.id,
            agent=step.agent_intent,
            trace_id=workflow.trace_id,
            causation_id=command.message_id,
            attempt=step.attempt_count,
            worker_instance_id=self.worker_id,
        )
        await OutboxDispatcher(self.session).dispatch(
            aggregate_type="workflow_step",
            aggregate_id=step.id,
            routing_key="agent.step.started",
            message=started_event,
        )
        await self.session.commit()

        heartbeat = StepLeaseHeartbeat(step_id=step.id, worker_id=self.worker_id)
        await heartbeat.start()
        worker = self.registry.get(command.agent)
        result_service = WorkerResultService(
            self.session,
            consumer_name=self.consumer_name,
            worker_id=self.worker_id,
        )
        if command.agent == "email_send":
            try:
                await self._raise_if_cancelled(workflow.id, "email send")
                request_payload = workflow.input_json["chat_request"]["agent_inputs"]["email_send"]
                send_request = EmailSendRequest.model_validate(request_payload)
                reminder = await self._validated_reminder(send_request)
                if reminder is not None and reminder.status == ReminderStatus.SENT:
                    send_result = None
                    result = WorkerRunResult(
                        final_response="提醒邮件此前已发送；本次消息按幂等规则跳过。",
                    )
                else:
                    send_result = await EmailAgentService(
                        audit_repository=EmailSendAuditRepository(self.session)
                    ).send(send_request)
                if send_result is None:
                    pass
                elif send_result.status == "requires_approval":
                    result = WorkerRunResult(
                        final_response="邮件发送仍需要用户显式审批。",
                        missing_information=["email.approval"],
                        next_actions=["Approve the email before sending."],
                    )
                elif send_result.status != "sent":
                    raise ConnectionError(send_result.error or "Email provider did not confirm delivery")
                else:
                    if reminder is not None:
                        reminder.status = ReminderStatus.SENT
                        reminder.sent_at = send_result.sent_at or datetime.now(UTC)
                    result = WorkerRunResult(
                        final_response="邮件已按批准内容发送。",
                        artifacts=[
                            AgentArtifact(
                                name="Email Send Result",
                                kind="email_send_result",
                                payload=send_result.model_dump(mode="json"),
                            )
                        ],
                    )
            except asyncio.CancelledError:
                await heartbeat.stop()
                await result_service.persist_cancelled(
                    command=command,
                    workflow=workflow,
                    step=step,
                )
            except OperationalError:
                await heartbeat.stop()
                await self.session.rollback()
                raise
            except Exception as exc:
                await heartbeat.stop()
                await result_service.persist_failure(
                    command=command,
                    workflow=workflow,
                    step=step,
                    error=exc,
                    retryable=is_retryable_error(exc),
                )
            else:
                await heartbeat.stop()
                await result_service.persist_success(
                    command=command,
                    workflow=workflow,
                    step=step,
                    result=result,
                )
            return
        if worker is None:
            await heartbeat.stop()
            await result_service.persist_failure(
                command=command,
                workflow=workflow,
                step=step,
                error=LookupError(f"No worker registered for {command.agent}"),
                retryable=False,
            )
            return
        try:
            context, _tool_results = await WorkerContextLoader(self.session).load(command, worker)
            await self._raise_if_cancelled(workflow.id, "worker execution")
            result = await worker.run(context)
            await self.session.refresh(workflow)
            if workflow.status == WorkflowStatus.CANCEL_REQUESTED.value:
                raise asyncio.CancelledError("Workflow cancellation requested")
        except asyncio.CancelledError:
            await heartbeat.stop()
            await result_service.persist_cancelled(
                command=command,
                workflow=workflow,
                step=step,
            )
        except OperationalError:
            await heartbeat.stop()
            await self.session.rollback()
            raise
        except Exception as exc:
            await heartbeat.stop()
            await result_service.persist_failure(
                command=command,
                workflow=workflow,
                step=step,
                error=exc,
                retryable=is_retryable_error(exc),
            )
        else:
            await heartbeat.stop()
            await result_service.persist_success(
                command=command,
                workflow=workflow,
                step=step,
                result=result,
            )

    async def _raise_if_cancelled(self, workflow_id: str, boundary: str) -> None:
        status = await self.session.scalar(
            select(WorkflowRun.status).where(WorkflowRun.id == workflow_id)
        )
        if status in {WorkflowStatus.CANCEL_REQUESTED.value, WorkflowStatus.CANCELLED.value}:
            raise asyncio.CancelledError(f"Workflow cancellation requested before {boundary}")

    async def _validated_reminder(self, request: EmailSendRequest) -> Reminder | None:
        if request.source_type != "reminder":
            return None
        if not request.source_id:
            raise PermissionError("Reminder email has no source reminder")
        reminder = await self.session.get(Reminder, request.source_id)
        if reminder is None or reminder.user_id != request.user_id:
            raise PermissionError("Reminder no longer exists or belongs to another user")
        user = await self.session.get(User, reminder.user_id)
        expected_recipient = reminder.recipient_email or (user.email if user else None)
        if not reminder.delivery_approved or reminder.approved_at is None:
            raise PermissionError("Reminder delivery has not been explicitly approved")
        if expected_recipient != request.to_email:
            raise PermissionError("Reminder recipient changed after approval")
        if reminder.status not in {ReminderStatus.PENDING, ReminderStatus.SENT}:
            raise PermissionError(f"Reminder is no longer deliverable: {reminder.status}")
        if reminder.status == ReminderStatus.PENDING and reminder.remind_at > datetime.now(UTC):
            raise PermissionError("Reminder is not due yet")
        return reminder


def is_retryable_error(error: Exception) -> bool:
    if isinstance(error, (ValidationError, PermissionError, LookupError)):
        return False
    if isinstance(error, (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.TransportError, OperationalError)):
        return True
    if isinstance(
        error,
        (
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
            openai.InternalServerError,
        ),
    ):
        return True
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code == 429 or error.response.status_code >= 500
    return False
