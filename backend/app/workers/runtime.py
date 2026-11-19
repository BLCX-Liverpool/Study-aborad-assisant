from __future__ import annotations

from aio_pika.abc import AbstractIncomingMessage

from app.core.database import get_session_factory
from app.messaging.serialization import deserialize_message
from app.schemas.messages import AgentTaskCommand
from app.workers.task_handler import WorkerTaskHandler


class AgentWorkerRuntime:
    def __init__(self, *, consumer_name: str) -> None:
        self.consumer_name = consumer_name

    async def handle_message(self, message: AbstractIncomingMessage) -> None:
        command = deserialize_message(message.body, AgentTaskCommand)
        async with get_session_factory()() as session:
            await WorkerTaskHandler(
                session,
                consumer_name=self.consumer_name,
            ).handle(command)
