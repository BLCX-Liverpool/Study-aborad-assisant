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
        headers = json.loads(json.dumps(dict(message.headers or {}), default=str))
        exchange_name = str(getattr(message, "exchange", "") or headers.get("x-first-death-exchange") or "")
        routing_key = str(
            headers.get("x-first-death-routing-key")
            or getattr(message, "routing_key", "")
            or ""
        )
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
                    exchange_name=exchange_name or None,
                    routing_key=routing_key or None,
                    message_type=str(payload.get("message_type") or message.type or "") or None,
                    payload_json=payload if isinstance(payload, dict) else {"payload": payload},
                    headers_json=headers,
                    causation_id=payload.get("causation_id") if isinstance(payload, dict) else None,
                )
                session.add(record)
            else:
                record.status = "dead_lettered"
                record.processed_at = datetime.now(UTC)
                record.error = error
                record.exchange_name = exchange_name or record.exchange_name
                record.routing_key = routing_key or record.routing_key
                record.message_type = str(payload.get("message_type") or message.type or "") or record.message_type
                record.payload_json = payload if isinstance(payload, dict) else {"payload": payload}
                record.headers_json = headers
            await session.commit()
