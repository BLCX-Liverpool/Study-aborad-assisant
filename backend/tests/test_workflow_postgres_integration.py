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
    Conversation,
    ConversationMessage,
    EmailSendAttempt,
    MessageInbox,
    Memory,
    OutboxEvent,
    Reminder,
    ReminderStatus,
    RunStatus,
    TraceSpan,
    WorkflowRun,
    WorkflowStep,
)
from app.memory.manager import MemoryManager
from app.memory.repository import ConversationRepository, LongTermMemoryRepository
from app.memory.short_term import InMemoryShortTermMemoryStore
from app.schemas.email import EmailSendRequest
from app.api.routes.dead_letters import replay_dead_letter
from app.schemas.chat import ChatRequest
from app.schemas.messages import AgentStepEvent, AgentTaskCommand
from app.schemas.router import RouterOutput
from app.scheduler.stale_run_recovery import StaleRunRecovery
from app.scheduler.reminder_scheduler import ReminderScheduler
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
async def test_long_term_memory_pgvector_top_k_respects_user_and_namespace() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex
    user_id = f"memory-user-{token}"
    other_user_id = f"other-memory-user-{token}"

    try:
        async with session_factory() as session:
            session.add_all(
                [
                    Memory(
                        id=f"target-{token}",
                        user_id=user_id,
                        namespace="travel",
                        memory_type="user_preference",
                        content="Prefers quiet hotels near public transport.",
                        embedding=[1.0, *([0.0] * 1535)],
                        access_policy_json={"confirmed": True, "rejected": False},
                    ),
                    Memory(
                        id=f"other-namespace-{token}",
                        user_id=user_id,
                        namespace="finance",
                        memory_type="user_preference",
                        content="Finance-only memory.",
                        embedding=[1.0, *([0.0] * 1535)],
                        access_policy_json={"confirmed": True, "rejected": False},
                    ),
                    Memory(
                        id=f"other-user-{token}",
                        user_id=other_user_id,
                        namespace="travel",
                        memory_type="user_preference",
                        content="Another user's travel memory.",
                        embedding=[1.0, *([0.0] * 1535)],
                        access_policy_json={"confirmed": True, "rejected": False},
                    ),
                ]
            )
            await session.commit()

            results = await LongTermMemoryRepository(session).search(
                user_id=user_id,
                query="quiet hotel",
                namespaces=["travel"],
                top_k=5,
                query_embedding=[1.0, *([0.0] * 1535)],
            )

            assert [item.id for item in results] == [f"target-{token}"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_async_workflow_completion_persists_conversation_messages_once() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex
    user_id = f"conversation-user-{token}"
    conversation_id = f"conversation-{token}"

    try:
        async with session_factory() as session:
            repository = WorkflowRepository(session)
            request = ChatRequest(
                user_id=user_id,
                conversation_id=conversation_id,
                message="异步用户消息",
            )
            router_output = RouterOutput(primary_intent="general_chat", confidence=0.9)
            workflow = await repository.create(
                user_id=user_id,
                conversation_id=conversation_id,
                trace_id=str(uuid4()),
                request_id=f"conversation-request-{token}",
                workflow_type="chat",
                input_json={"chat_request": request.model_dump(mode="json")},
            )
            workflow.plan_json = {"router": router_output.model_dump(mode="json")}
            await repository.transition_workflow(workflow, WorkflowStatus.PLANNING)
            step = (
                await repository.create_steps(
                    workflow.id,
                    [{"index": 0, "intent_name": "general_chat.respond", "agent_intent": "general_chat"}],
                )
            )[0]
            await repository.transition_workflow(workflow, WorkflowStatus.RUNNING)
            await repository.transition_step(step, StepStatus.QUEUED)
            await repository.transition_step(step, StepStatus.RUNNING)
            await repository.transition_step(
                step,
                StepStatus.COMPLETED,
                result_summary="异步助手回复",
            )
            await session.commit()

            event = AgentStepEvent(
                message_id=f"conversation-event-{token}",
                message_type="agent.step.completed",
                workflow_id=workflow.id,
                step_id=step.id,
                agent="general_chat",
                trace_id=workflow.trace_id,
                result_summary="异步助手回复",
            )
            memory_manager = MemoryManager(
                short_term_store=InMemoryShortTermMemoryStore(),
                conversation_repository=ConversationRepository(session),
                long_term_repository=LongTermMemoryRepository(session),
            )
            handler = WorkflowEventHandler(
                session,
                consumer_name=f"conversation-consumer-{token}",
                memory_manager=memory_manager,
            )

            await handler.handle(event)
            await handler.handle(event)

            conversation = await session.get(Conversation, conversation_id)
            messages = (
                await session.execute(
                    select(ConversationMessage)
                    .where(ConversationMessage.conversation_id == conversation_id)
                    .order_by(ConversationMessage.created_at)
                )
            ).scalars().all()
            assert conversation is not None
            assert conversation.user_id == user_id
            assert [(message.role, message.content) for message in messages] == [
                ("user", "异步用户消息"),
                ("assistant", "异步助手回复"),
            ]
    finally:
        await engine.dispose()


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
                (TraceSpan, 1),
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
async def test_conditioned_dependency_and_approved_reminder_delivery_close_the_loop() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex
    user_id = f"condition-reminder-{token}"
    try:
        async with session_factory() as session:
            repository = WorkflowRepository(session)
            workflow = await repository.create(
                user_id=user_id,
                conversation_id=f"condition-{token}",
                trace_id=str(uuid4()),
                request_id=f"condition-{token}",
                workflow_type="test",
                input_json={"chat_request": {}},
            )
            steps = await repository.create_steps(workflow.id, [
                {"index": 0, "intent_name": "source", "agent_intent": "travel"},
                {"index": 1, "intent_name": "success-branch", "agent_intent": "finance", "depends_on": [0], "condition": {"result_contains": "approved"}},
                {"index": 2, "intent_name": "closed-branch", "agent_intent": "finance", "depends_on": [0], "condition": {"result_contains": "rejected"}},
            ])
            await repository.transition_step(steps[0], StepStatus.QUEUED)
            await repository.transition_step(steps[0], StepStatus.RUNNING)
            await repository.transition_step(steps[0], StepStatus.COMPLETED, result_summary="approved route")
            ready = await repository.ready_steps(workflow.id)
            assert [item.id for item in ready] == [steps[1].id]
            assert await repository.cancel_blocked_steps(workflow.id) == 1
            await session.refresh(steps[2])
            assert steps[2].last_error_code == "dependency_condition_not_met"

            reminder = Reminder(
                user_id=user_id,
                remind_at=datetime.now(UTC) - timedelta(seconds=1),
                channel="email",
                recipient_email="student@example.com",
                delivery_approved=True,
                approved_at=datetime.now(UTC),
                idempotency_key=f"reminder:{token}",
            )
            session.add(reminder)
            await session.commit()
            assert await ReminderScheduler(session).enqueue_due() == 1
            reminder_workflow = await repository.get_by_request_id(
                user_id=user_id, request_id=f"reminder:{reminder.id}"
            )
            assert reminder_workflow is not None
            task_outbox = (
                await session.execute(select(OutboxEvent).where(
                    OutboxEvent.message_type == "agent.task.requested",
                    OutboxEvent.payload_json["workflow_id"].as_string() == reminder_workflow.id,
                ))
            ).scalars().one()
            command = AgentTaskCommand.model_validate(task_outbox.payload_json)
            await WorkerTaskHandler(session, consumer_name=f"reminder-worker-{token}").handle(command)
            await session.refresh(reminder)
            assert reminder.status == ReminderStatus.SENT
            assert reminder.sent_at is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dead_letter_replay_works_without_original_outbox_row() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    token = uuid4().hex
    message_id = f"external-dead-{token}"
    try:
        async with session_factory() as session:
            session.add(MessageInbox(
                consumer_name="study.dead.q",
                message_id=message_id,
                workflow_id=f"workflow-{token}",
                status="dead_lettered",
                received_at=datetime.now(UTC),
                processed_at=datetime.now(UTC),
                routing_key="workflow.prepare",
                message_type="workflow.prepare",
                payload_json={
                    "schema_version": 1,
                    "message_id": message_id,
                    "message_type": "workflow.prepare",
                    "workflow_id": f"workflow-{token}",
                    "trace_id": f"trace-{token}",
                    "input_ref": f"workflow-input:workflow-{token}",
                    "created_at": datetime.now(UTC).isoformat(),
                },
                headers_json={"original": True},
            ))
            await session.commit()
            result = await replay_dead_letter(message_id, session)
            assert result.status == "replay_queued"
            replay = await session.get(OutboxEvent, result.new_message_id)
            assert replay is not None
            assert replay.payload_json["causation_id"] == message_id
            assert replay.headers_json["replayed_from"] == message_id
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_completion_event_and_api_restart_are_idempotent() -> None:
    database_url = os.environ["DATABASE_URL"]
    first_engine = create_async_engine(database_url, pool_pre_ping=True)
    first_factory = async_sessionmaker(first_engine, expire_on_commit=False)
    token = uuid4().hex
    async with first_factory() as session:
        repository = WorkflowRepository(session)
        workflow = await repository.create(
            user_id=f"restart-user-{token}", conversation_id=f"restart-{token}",
            trace_id=str(uuid4()), request_id=f"restart-{token}", workflow_type="test",
            input_json={"chat_request": {}},
        )
        await repository.transition_workflow(workflow, WorkflowStatus.PLANNING)
        step = (await repository.create_steps(workflow.id, [
            {"index": 0, "intent_name": "done", "agent_intent": "travel"}
        ]))[0]
        await repository.transition_workflow(workflow, WorkflowStatus.RUNNING)
        await repository.transition_step(step, StepStatus.QUEUED)
        await repository.transition_step(step, StepStatus.RUNNING)
        await repository.transition_step(step, StepStatus.COMPLETED, result_summary="durable result")
        await session.commit()
        workflow_id, step_id, trace_id = workflow.id, step.id, workflow.trace_id
    await first_engine.dispose()

    # A brand-new engine/session represents an API/process restart.
    second_engine = create_async_engine(database_url, pool_pre_ping=True)
    second_factory = async_sessionmaker(second_engine, expire_on_commit=False)
    event = AgentStepEvent(
        message_id=f"concurrent-complete-{token}",
        message_type="agent.step.completed",
        workflow_id=workflow_id,
        step_id=step_id,
        agent="travel",
        trace_id=trace_id,
        result_summary="durable result",
    )

    async def consume() -> None:
        async with second_factory() as session:
            await WorkflowEventHandler(session, consumer_name=f"complete-consumer-{token}").handle(event)

    try:
        await asyncio.gather(consume(), consume())
        async with second_factory() as session:
            restored = await WorkflowRepository(session).get(workflow_id)
            assert restored.status == "completed"
            inbox_count = await session.scalar(select(func.count()).select_from(MessageInbox).where(
                MessageInbox.consumer_name == f"complete-consumer-{token}",
                MessageInbox.message_id == event.message_id,
            ))
            completion_count = await session.scalar(select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.aggregate_id == workflow_id,
                OutboxEvent.message_type == "workflow.completed",
            ))
            assert inbox_count == 1
            assert completion_count == 1
    finally:
        await second_engine.dispose()


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
            assert steps[1].last_error_code == "dependency_condition_not_met"
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
