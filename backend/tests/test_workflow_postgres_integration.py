import os
import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.models import (
    AgentArtifactRecord,
    AgentRun,
    EmailSendAttempt,
    MessageInbox,
    OutboxEvent,
    RunStatus,
    WorkflowRun,
    WorkflowStep,
)
from app.schemas.email import EmailSendRequest
from app.schemas.messages import AgentStepEvent, AgentTaskCommand
from app.scheduler.stale_run_recovery import StaleRunRecovery
from app.workers.result_service import WorkerResultService
from app.workers.task_handler import WorkerTaskHandler
from app.workflows.event_handler import WorkflowEventHandler
from app.workflows.repository import InboxRepository, WorkflowRepository
from app.workflows.service import WorkflowService
from app.workflows.state_machine import StepStatus, WorkflowStatus


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_WORKFLOW_INTEGRATION") != "1",
    reason="Set RUN_WORKFLOW_INTEGRATION=1 with the migrated PostgreSQL database running",
)


@pytest.mark.asyncio
async def test_email_workflow_is_durable_and_idempotent() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex
    user_id = f"integration-user-{token}"
    request_id = f"integration-request-{token}"

    try:
        async with session_factory() as session:
            service = WorkflowService(session)
            accepted = await service.create_email_send_workflow(
                EmailSendRequest(
                    user_id=user_id,
                    provider="dry_run",
                    to_email="integration@example.com",
                    subject="RabbitMQ integration",
                    body="Durable workflow test",
                    approved=True,
                ),
                request_id=request_id,
            )
            repeated = await service.create_email_send_workflow(
                EmailSendRequest(
                    user_id=user_id,
                    provider="dry_run",
                    to_email="integration@example.com",
                    subject="RabbitMQ integration",
                    body="Durable workflow test",
                    approved=True,
                ),
                request_id=request_id,
            )
            assert repeated.workflow_id == accepted.workflow_id

            task_outbox = (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_type == "workflow_step",
                        OutboxEvent.message_type == "agent.task.requested",
                        OutboxEvent.payload_json["workflow_id"].as_string() == accepted.workflow_id,
                    )
                )
            ).scalars().one()
            command = AgentTaskCommand.model_validate(task_outbox.payload_json)

            handler = WorkerTaskHandler(session, consumer_name="integration.email.worker")
            await handler.handle(command)
            await handler.handle(command)

            completed_outbox = (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == command.step_id,
                        OutboxEvent.message_type == "agent.step.completed",
                    )
                )
            ).scalars().one()
            event = AgentStepEvent.model_validate(completed_outbox.payload_json)
            event_handler = WorkflowEventHandler(session, consumer_name="integration.orchestrator")
            await event_handler.handle(event)
            await event_handler.handle(event)

            workflow = await WorkflowRepository(session).get(accepted.workflow_id)
            assert workflow.status == "completed"
            assert workflow.final_response == "邮件已按批准内容发送。"

            for model, expected in (
                (AgentArtifactRecord, 1),
                (AgentRun, 1),
                (EmailSendAttempt, 1),
            ):
                count = await session.scalar(
                    select(func.count()).select_from(model).where(model.user_id == user_id)
                )
                assert count == expected

            inbox_count = await session.scalar(
                select(func.count())
                .select_from(MessageInbox)
                .where(MessageInbox.workflow_id == accepted.workflow_id)
            )
            assert inbox_count == 2
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failed_dependency_cancels_blocked_branch_and_yields_partial_failure() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex

    try:
        async with session_factory() as session:
            repository = WorkflowRepository(session)
            workflow = await repository.create(
                user_id=f"dag-user-{token}",
                conversation_id=f"dag-conversation-{token}",
                trace_id=str(uuid4()),
                request_id=f"dag-request-{token}",
                workflow_type="chat",
                input_json={"chat_request": {}},
            )
            await repository.transition_workflow(workflow, WorkflowStatus.PLANNING)
            steps = await repository.create_steps(
                workflow.id,
                [
                    {"index": 0, "intent_name": "upstream", "agent_intent": "travel"},
                    {
                        "index": 1,
                        "intent_name": "blocked",
                        "agent_intent": "finance",
                        "depends_on": [0],
                    },
                    {"index": 2, "intent_name": "independent", "agent_intent": "task_planning"},
                ],
            )
            await repository.transition_workflow(workflow, WorkflowStatus.RUNNING)
            for step in (steps[0], steps[2]):
                await repository.transition_step(step, StepStatus.QUEUED)
                await repository.transition_step(step, StepStatus.RUNNING)
            await repository.transition_step(steps[0], StepStatus.FAILED)
            await repository.transition_step(
                steps[2],
                StepStatus.COMPLETED,
                result_summary="Independent branch completed.",
            )
            await session.commit()

            failed_event = AgentStepEvent(
                message_type="agent.step.failed",
                workflow_id=workflow.id,
                step_id=steps[0].id,
                agent=steps[0].agent_intent,
                trace_id=workflow.trace_id,
                error_code="test_failure",
                error_message="Injected permanent failure",
            )
            await WorkflowEventHandler(
                session,
                consumer_name="integration.dag.orchestrator",
            ).handle(failed_event)

            await session.refresh(workflow)
            await session.refresh(steps[1])
            assert steps[1].status == "cancelled"
            assert steps[1].last_error_code == "dependency_failed"
            assert workflow.status == "partial_failed"
            assert workflow.final_response == "Independent branch completed."
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_expired_worker_lease_reaches_dlq_and_finalizes_workflow() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex

    try:
        async with session_factory() as session:
            accepted = await WorkflowService(session).create_email_send_workflow(
                EmailSendRequest(
                    user_id=f"lease-user-{token}",
                    provider="dry_run",
                    to_email="lease@example.com",
                    subject="Expired lease",
                    body="Simulate worker crash",
                    approved=True,
                ),
                request_id=f"lease-request-{token}",
            )
            repository = WorkflowRepository(session)
            workflow = await repository.get(accepted.workflow_id)
            step = (await repository.list_steps(workflow.id))[0]
            step.max_attempts = 1
            assert await repository.claim_step(step, worker_id="crashed-worker", lease_seconds=60)
            attempt = AgentRun(
                user_id=workflow.user_id,
                conversation_id=workflow.conversation_id,
                trace_id=workflow.trace_id,
                workflow_id=workflow.id,
                step_id=step.id,
                attempt=step.attempt_count,
                idempotency_key=f"{workflow.id}:{step.id}:{step.attempt_count}",
                agent_name=step.agent_intent,
                status=RunStatus.IN_PROGRESS,
                started_at=step.started_at,
            )
            session.add(attempt)
            step.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()

            assert await StaleRunRecovery(session).recover() >= 1
            await session.refresh(step)
            await session.refresh(attempt)
            assert step.status == "dead_lettered"
            assert attempt.status == RunStatus.FAILED
            assert attempt.completed_at is not None
            dead_outbox = (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == step.id,
                        OutboxEvent.message_type == "agent.step.dead_lettered",
                    )
                )
            ).scalars().one()
            await WorkflowEventHandler(
                session,
                consumer_name="integration.lease.orchestrator",
            ).handle(AgentStepEvent.model_validate(dead_outbox.payload_json))
            await session.refresh(workflow)
            assert workflow.status == "dead_lettered"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_request_and_inbox_idempotency() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex
    user_id = f"concurrent-user-{token}"
    request_id = f"concurrent-request-{token}"
    request = EmailSendRequest(
        user_id=user_id,
        provider="dry_run",
        to_email="concurrent@example.com",
        subject="Concurrent request",
        body="Only one workflow",
        approved=True,
    )

    async def submit():
        async with session_factory() as session:
            return await WorkflowService(session).create_email_send_workflow(
                request,
                request_id=request_id,
            )

    async def claim(consumer_name: str, message_id: str) -> bool:
        async with session_factory() as session:
            created = await InboxRepository(session).begin(
                consumer_name=consumer_name,
                message_id=message_id,
                workflow_id=None,
                step_id=None,
            )
            await session.commit()
            return created

    try:
        first, second = await asyncio.gather(submit(), submit())
        assert first.workflow_id == second.workflow_id
        async with session_factory() as session:
            workflow_count = await session.scalar(
                select(func.count())
                .select_from(WorkflowRun)
                .where(WorkflowRun.user_id == user_id, WorkflowRun.request_id == request_id)
            )
            step_count = await session.scalar(
                select(func.count())
                .select_from(WorkflowStep)
                .where(WorkflowStep.workflow_id == first.workflow_id)
            )
            assert workflow_count == 1
            assert step_count == 1

        consumer_name = f"concurrent-consumer-{token}"
        message_id = f"concurrent-message-{token}"
        claims = await asyncio.gather(
            claim(consumer_name, message_id),
            claim(consumer_name, message_id),
        )
        assert sorted(claims) == [False, True]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_running_step_cancellation_converges_workflow() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex

    try:
        async with session_factory() as session:
            accepted = await WorkflowService(session).create_email_send_workflow(
                EmailSendRequest(
                    user_id=f"cancel-user-{token}",
                    provider="dry_run",
                    to_email="cancel@example.com",
                    subject="Cancellation",
                    body="Do not send",
                    approved=True,
                ),
                request_id=f"cancel-request-{token}",
            )
            task_outbox = (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.message_type == "agent.task.requested",
                        OutboxEvent.payload_json["workflow_id"].as_string() == accepted.workflow_id,
                    )
                )
            ).scalars().one()
            command = AgentTaskCommand.model_validate(task_outbox.payload_json)
            repository = WorkflowRepository(session)
            workflow = await repository.get(command.workflow_id)
            step = await repository.get_step(command.step_id)
            await InboxRepository(session).begin(
                consumer_name="integration.cancel.worker",
                message_id=command.message_id,
                workflow_id=workflow.id,
                step_id=step.id,
            )
            assert await repository.claim_step(step, worker_id="integration-worker", lease_seconds=60)
            await repository.transition_workflow(workflow, WorkflowStatus.CANCEL_REQUESTED)
            await session.commit()

            await WorkerResultService(
                session,
                consumer_name="integration.cancel.worker",
                worker_id="integration-worker",
            ).persist_cancelled(command=command, workflow=workflow, step=step)
            cancelled_outbox = (
                await session.execute(
                    select(OutboxEvent).where(
                        OutboxEvent.aggregate_id == step.id,
                        OutboxEvent.message_type == "agent.step.cancelled",
                    )
                )
            ).scalars().one()
            await WorkflowEventHandler(
                session,
                consumer_name="integration.cancel.orchestrator",
            ).handle(AgentStepEvent.model_validate(cancelled_outbox.payload_json))

            await session.refresh(workflow)
            assert workflow.status == "cancelled"
            assert step.status == "cancelled"
    finally:
        await engine.dispose()
