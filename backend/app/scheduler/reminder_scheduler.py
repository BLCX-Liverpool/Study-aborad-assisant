from datetime import UTC, datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Reminder, ReminderStatus
from app.schemas.email import EmailSendRequest
from app.workflows.repository import WorkflowRepository
from app.workflows.service import WorkflowService


class ReminderScheduler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = WorkflowRepository(session)

    async def enqueue_due(self, *, limit: int = 50) -> int:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(Reminder)
            .where(
                Reminder.remind_at <= now,
                Reminder.status == ReminderStatus.PENDING,
                Reminder.channel == "email",
                Reminder.delivery_approved.is_(True),
                Reminder.recipient_email.is_not(None),
            )
            .order_by(Reminder.remind_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        count = 0
        for reminder in result.scalars().all():
            request_id = f"reminder:{reminder.id}"
            if await self.repository.get_by_request_id(user_id=reminder.user_id, request_id=request_id):
                continue
            await WorkflowService(self.session).create_email_send_workflow(
                EmailSendRequest(
                    user_id=reminder.user_id,
                    to_email=str(reminder.recipient_email),
                    subject="Study Abroad Assistant reminder",
                    body=f"Reminder scheduled for {reminder.remind_at.isoformat()}.",
                    approved=True,
                    source_type="reminder",
                    source_id=reminder.id,
                    idempotency_key=reminder.idempotency_key or f"email-reminder:{reminder.id}",
                    metadata={"reminder_id": reminder.id, "remind_at": reminder.remind_at.isoformat()},
                ),
                request_id=request_id,
            )
            count += 1
        await self.session.commit()
        return count
