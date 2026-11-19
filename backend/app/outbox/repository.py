from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import OutboxEvent


OUTBOX_BACKOFF_SECONDS = (10, 30, 120, 300)


class OutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_batch(self, *, limit: int = 100) -> list[OutboxEvent]:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "pending",
                OutboxEvent.available_at <= now,
            )
            .order_by(OutboxEvent.created_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        events = list(result.scalars().all())
        for event in events:
            event.status = "publishing"
            event.attempt_count += 1
        await self.session.commit()
        return events

    async def mark_published(self, event_id: str) -> None:
        await self.session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id, OutboxEvent.status == "publishing")
            .values(
                status="published",
                published_at=datetime.now(UTC),
                last_error=None,
                updated_at=datetime.now(UTC),
            )
        )
        await self.session.commit()

    async def mark_failed(self, event_id: str, error: str, *, attempt_count: int) -> None:
        delay_index = min(max(attempt_count - 1, 0), len(OUTBOX_BACKOFF_SECONDS) - 1)
        await self.session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.id == event_id)
            .values(
                status="pending",
                available_at=datetime.now(UTC) + timedelta(seconds=OUTBOX_BACKOFF_SECONDS[delay_index]),
                last_error=error[:4000],
                updated_at=datetime.now(UTC),
            )
        )
        await self.session.commit()

    async def recover_stale_claims(self, *, older_than_seconds: int = 300) -> int:
        threshold = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        result = await self.session.execute(
            update(OutboxEvent)
            .where(OutboxEvent.status == "publishing", OutboxEvent.updated_at < threshold)
            .values(status="pending", available_at=datetime.now(UTC), updated_at=datetime.now(UTC))
        )
        await self.session.commit()
        return int(result.rowcount or 0)
