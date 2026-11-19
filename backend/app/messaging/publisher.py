from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from app.messaging.connection import rabbitmq_manager
from app.messaging.serialization import serialize_message
from app.messaging.topology import COMMAND_EXCHANGE, EVENT_EXCHANGE


class RabbitMQPublisher:
    async def publish(
        self,
        *,
        routing_key: str,
        message: BaseModel | dict,
        exchange_name: str | None = None,
        headers: dict | None = None,
    ) -> None:
        import aio_pika

        payload = message.model_dump(mode="json") if isinstance(message, BaseModel) else message

        resolved_exchange = exchange_name or (
            EVENT_EXCHANGE if routing_key.startswith(("agent.step.", "artifact.", "workflow.completed"))
            else COMMAND_EXCHANGE
        )
        channel = await rabbitmq_manager.channel(
            publisher_confirms=True,
            on_return_raises=True,
        )
        try:
            exchange = await channel.get_exchange(resolved_exchange, ensure=True)
            await exchange.publish(
                aio_pika.Message(
                    body=serialize_message(message),
                    content_type="application/json",
                    content_encoding="utf-8",
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    message_id=str(payload.get("message_id", "")) or None,
                    correlation_id=str(payload.get("workflow_id", "")) or None,
                    type=str(payload.get("message_type", "")) or None,
                    timestamp=datetime.now(UTC),
                    headers=headers or {},
                ),
                routing_key=routing_key,
                mandatory=True,
            )
        finally:
            await channel.close()
