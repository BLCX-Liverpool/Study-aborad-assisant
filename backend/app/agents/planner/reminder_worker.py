from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.email.repository import EmailSendAuditRepository
from app.agents.email.service import EmailAgentService
from app.db.models import Reminder, ReminderStatus
from app.schemas.email import EmailSendRequest
from app.schemas.planner import DueReminder, EmailReminderQueueItem, EmailReminderSendRequest, EmailReminderSendResponse


class ReminderWorker:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def due_reminders(self, now: datetime | None = None, limit: int = 50) -> list[DueReminder]:
        now = now or datetime.now(UTC)
        statement = (
            select(Reminder)
            .where(Reminder.remind_at <= now, Reminder.status == ReminderStatus.PENDING)
            .order_by(Reminder.remind_at)
            .limit(limit)
        )
        result = await self.session.execute(statement)
        reminders = list(result.scalars().all())
        return [
            DueReminder(
                id=reminder.id,
                user_id=reminder.user_id,
                title=f"Reminder due at {reminder.remind_at.isoformat()}",
                channel=reminder.channel,
                remind_at=reminder.remind_at,
                task_id=reminder.task_id,
                event_id=reminder.event_id,
            )
            for reminder in reminders
        ]

    async def mark_sent(self, reminder_ids: list[str]) -> int:
        if not reminder_ids:
            return 0
        count = 0
        for reminder_id in reminder_ids:
            reminder = await self.session.get(Reminder, reminder_id)
            if reminder is None or reminder.status != ReminderStatus.PENDING:
                continue
            reminder.status = ReminderStatus.SENT
            count += 1
        await self.session.commit()
        return count

    async def email_queue(self, now: datetime | None = None, limit: int = 50) -> list[EmailReminderQueueItem]:
        due = await self.due_reminders(now=now, limit=limit)
        return [
            EmailReminderQueueItem(
                reminder_id=reminder.id,
                user_id=reminder.user_id,
                subject=reminder.title,
                body=(
                    f"Reminder: {reminder.title}\n\n"
                    f"Scheduled for {reminder.remind_at.isoformat()}.\n"
                    "This queue item is a draft and no email has been sent."
                ),
                remind_at=reminder.remind_at,
            )
            for reminder in due
            if reminder.channel == "email"
        ]

    async def send_email_reminders(
        self,
        request: EmailReminderSendRequest,
        now: datetime | None = None,
        limit: int = 50,
        email_service: EmailAgentService | None = None,
    ) -> EmailReminderSendResponse:
        queue = await self.email_queue(now=now, limit=limit)
        selected = [
            item
            for item in queue
            if item.user_id == request.user_id and (not request.reminder_ids or item.reminder_id in request.reminder_ids)
        ]
        service = email_service or EmailAgentService(audit_repository=EmailSendAuditRepository(self.session))
        sent = []
        skipped = []
        sent_reminder_ids = []
        for item in selected:
            result = await service.send(
                EmailSendRequest(
                    user_id=item.user_id,
                    provider=request.provider,
                    to_email=request.to_email,
                    subject=item.subject,
                    body=item.body,
                    approved=request.approved,
                    idempotency_key=_reminder_idempotency_key(request, item),
                    source_type="reminder",
                    source_id=item.reminder_id,
                    metadata={"remind_at": item.remind_at.isoformat()},
                )
            )
            if result.status == "sent":
                sent.append(result)
                sent_reminder_ids.append(item.reminder_id)
            else:
                skipped.append(result)
        marked = await self.mark_sent(sent_reminder_ids) if sent_reminder_ids else 0
        return EmailReminderSendResponse(sent=sent, skipped=skipped, marked_sent_count=marked)


def _reminder_idempotency_key(request: EmailReminderSendRequest, item: EmailReminderQueueItem) -> str:
    prefix = request.idempotency_prefix or "email-reminder"
    return f"{prefix}:{item.reminder_id}:{request.provider}:{request.to_email}"
