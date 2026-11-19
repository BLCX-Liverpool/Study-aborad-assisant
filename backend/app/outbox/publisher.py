from __future__ import annotations

from app.core.config import get_settings
from app.messaging.publisher import RabbitMQPublisher
from app.outbox.repository import OutboxRepository


class OutboxPublisher:
    def __init__(self, repository: OutboxRepository, publisher: RabbitMQPublisher | None = None) -> None:
        self.repository = repository
        self.publisher = publisher or RabbitMQPublisher()

    async def publish_once(self) -> int:
        events = await self.repository.claim_batch(limit=get_settings().workflow_outbox_batch_size)
        published = 0
        for event in events:
            try:
                await self.publisher.publish(
                    routing_key=event.routing_key,
                    message=event.payload_json,
                    headers=event.headers_json,
                )
            except Exception as exc:
                await self.repository.mark_failed(
                    event.id,
                    str(exc),
                    attempt_count=event.attempt_count,
                )
            else:
                await self.repository.mark_published(event.id)
                published += 1
        return published
