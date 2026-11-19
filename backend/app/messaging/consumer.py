from __future__ import annotations

from collections.abc import Awaitable, Callable

from aio_pika.abc import AbstractIncomingMessage

from app.messaging.connection import rabbitmq_manager
from app.messaging.topology import queue_spec


MessageHandler = Callable[[AbstractIncomingMessage], Awaitable[None]]


class RabbitMQConsumer:
    def __init__(self, queue_name: str, handler: MessageHandler) -> None:
        self.queue_name = queue_name
        self.handler = handler
        self._channel = None
        self._queue = None
        self._consumer_tag: str | None = None

    async def start(self) -> None:
        spec = queue_spec(self.queue_name)
        self._channel = await rabbitmq_manager.channel(
            publisher_confirms=False,
            on_return_raises=False,
        )
        await self._channel.set_qos(prefetch_count=spec.prefetch)
        self._queue = await self._channel.get_queue(spec.name, ensure=True)
        self._consumer_tag = await self._queue.consume(self._on_message, no_ack=False)

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        try:
            await self.handler(message)
        except Exception:
            await message.reject(requeue=False)
            raise
        else:
            await message.ack()

    async def stop(self) -> None:
        if self._queue is not None and self._consumer_tag is not None:
            await self._queue.cancel(self._consumer_tag)
        if self._channel is not None and not self._channel.is_closed:
            await self._channel.close()
