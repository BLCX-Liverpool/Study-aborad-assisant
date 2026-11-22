from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.messaging.topology import (
    COMMAND_EXCHANGE,
    DEAD_LETTER_EXCHANGE,
    EVENT_EXCHANGE,
    QUEUE_SPECS,
)

if TYPE_CHECKING:
    import aio_pika


class RabbitMQConnectionManager:
    def __init__(self) -> None:
        self._connection: aio_pika.abc.AbstractRobustConnection | None = None

    async def connection(self) -> aio_pika.abc.AbstractRobustConnection:
        if self._connection is None or self._connection.is_closed:
            import aio_pika

            settings = get_settings()
            self._connection = await aio_pika.connect_robust(
                settings.rabbitmq_url,
                heartbeat=settings.rabbitmq_heartbeat_seconds,
                timeout=settings.rabbitmq_connection_timeout_seconds,
            )
        return self._connection

    async def channel(
        self,
        *,
        publisher_confirms: bool = True,
        on_return_raises: bool = True,
    ) -> aio_pika.abc.AbstractChannel:
        connection = await self.connection()
        return await connection.channel(
            publisher_confirms=publisher_confirms,
            on_return_raises=on_return_raises,
        )

    async def declare_topology(self) -> None:
        import aio_pika

        settings = get_settings()
        channel = await self.channel()
        exchanges = {
            COMMAND_EXCHANGE: await channel.declare_exchange(
                COMMAND_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
            ),
            EVENT_EXCHANGE: await channel.declare_exchange(
                EVENT_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
            ),
            DEAD_LETTER_EXCHANGE: await channel.declare_exchange(
                DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
            ),
        }
        for spec in QUEUE_SPECS:
            queue_arguments: dict[str, str | int] = {}
            if settings.rabbitmq_queue_type:
                queue_arguments["x-queue-type"] = settings.rabbitmq_queue_type
            if spec.name in settings.rabbitmq_single_active_consumer_queues:
                queue_arguments["x-single-active-consumer"] = True
            if spec.name != "study.dead.q":
                queue_arguments.update(
                    {
                        "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
                        "x-delivery-limit": 4,
                    }
                )
            queue = await channel.declare_queue(
                spec.name,
                durable=True,
                arguments=queue_arguments or None,
            )
            for routing_key in spec.routing_keys:
                await queue.bind(exchanges[spec.exchange], routing_key=routing_key)
        await channel.close()

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None


rabbitmq_manager = RabbitMQConnectionManager()
