from __future__ import annotations

import json
from datetime import UTC, datetime

from aio_pika.abc import AbstractIncomingMessage

from app.core.database import get_session_factory
from app.db.models import MessageInbox


class DeadLetterRuntime:
    consumer_name = "study.dead.q"

    async def handle_message(self, message: AbstractIncomingMessage) -> None:
        try:
            payload = json.loads(message.body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = {}
        message_id = str(payload.get("message_id") or message.message_id or f"dead:{message.delivery_tag}")
        x_death = (message.headers or {}).get("x-death")
        error = f"Dead-lettered by RabbitMQ; x-death={x_death!r}"
        async with get_session_factory()() as session:
            record = await session.get(MessageInbox, (self.consumer_name, message_id))
            if record is None:
                record = MessageInbox(
                    consumer_name=self.consumer_name,
                    message_id=message_id,
                    workflow_id=payload.get("workflow_id"),
                    step_id=payload.get("step_id"),
                    status="dead_lettered",
                    received_at=datetime.now(UTC),
                    processed_at=datetime.now(UTC),
                    error=error,
                )
                session.add(record)
            else:
                record.status = "dead_lettered"
                record.processed_at = datetime.now(UTC)
                record.error = error
            await session.commit()
