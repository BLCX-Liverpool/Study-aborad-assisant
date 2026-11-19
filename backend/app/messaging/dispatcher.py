from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent


class Dispatcher(Protocol):
    async def dispatch(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        routing_key: str,
        message: BaseModel,
        headers: dict | None = None,
    ) -> str:
        ...


class OutboxDispatcher:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def dispatch(
        self,
        *,
        aggregate_type: str,
        aggregate_id: str,
        routing_key: str,
        message: BaseModel,
        headers: dict | None = None,
    ) -> str:
        event = OutboxEvent(
            id=str(message.model_dump().get("message_id")),
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            message_type=str(message.model_dump().get("message_type")),
            routing_key=routing_key,
            payload_json=message.model_dump(mode="json"),
            headers_json=headers or {},
        )
        self.session.add(event)
        await self.session.flush()
        return event.id
