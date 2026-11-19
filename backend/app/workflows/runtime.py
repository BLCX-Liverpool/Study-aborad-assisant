from __future__ import annotations

from aio_pika.abc import AbstractIncomingMessage

from app.core.database import get_session_factory
from app.core.redis import get_redis
from app.memory.manager import MemoryManager
from app.memory.repository import ConversationRepository, LongTermMemoryRepository
from app.memory.short_term import RedisShortTermMemoryStore
from app.messaging.serialization import deserialize_message
from app.schemas.messages import AgentStepEvent, WorkflowPrepareCommand
from app.workflows.event_handler import WorkflowEventHandler
from app.workflows.planner import DurableWorkflowPlanner
from app.workflows.repository import InboxRepository, WorkflowRepository


class WorkflowPrepareRuntime:
    consumer_name = "study.workflow.prepare.q"

    async def handle_message(self, message: AbstractIncomingMessage) -> None:
        command = deserialize_message(message.body, WorkflowPrepareCommand)
        async with get_session_factory()() as session:
            inbox = InboxRepository(session)
            is_new = await inbox.begin(
                consumer_name=self.consumer_name,
                message_id=command.message_id,
                workflow_id=command.workflow_id,
                step_id=None,
            )
            if not is_new:
                await session.rollback()
                return
            memory_manager = MemoryManager(
                short_term_store=RedisShortTermMemoryStore(get_redis()),
                conversation_repository=ConversationRepository(session),
                long_term_repository=LongTermMemoryRepository(session),
            )
            await DurableWorkflowPlanner(
                WorkflowRepository(session),
                memory_manager=memory_manager,
            ).prepare(command.workflow_id)
            await inbox.complete(self.consumer_name, command.message_id)
            await session.commit()


class WorkflowEventRuntime:
    consumer_name = "study.orchestrator.events.q"

    async def handle_message(self, message: AbstractIncomingMessage) -> None:
        payload_type = str(message.type or "")
        if not payload_type.startswith("agent.step."):
            return
        event = deserialize_message(message.body, AgentStepEvent)
        async with get_session_factory()() as session:
            memory_manager = MemoryManager(
                short_term_store=RedisShortTermMemoryStore(get_redis()),
                conversation_repository=None,
                long_term_repository=LongTermMemoryRepository(session),
            )
            await WorkflowEventHandler(
                session,
                consumer_name=self.consumer_name,
                memory_manager=memory_manager,
            ).handle(event)
