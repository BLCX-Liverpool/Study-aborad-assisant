from datetime import UTC, datetime

import pytest

from app.agents.planner.reminder_worker import ReminderWorker
from app.agents.planner.service import TaskPlannerService
from app.schemas.action import ActionItem
from app.schemas.email import EmailSendResult
from app.schemas.planner import DueReminder, EmailReminderQueueItem, EmailReminderSendRequest, GlobalPlanningRequest, ScheduleBlock


def test_global_planner_converts_action_items_to_plan() -> None:
    deadline = datetime(2026, 10, 10, 16, 0, tzinfo=UTC)
    request = GlobalPlanningRequest(
        user_id="user_1",
        planning_horizon_days=180,
        items=[
            ActionItem(
                title="COMP702 Assignment deadline",
                action_type="assignment_deadline",
                source_type="notice",
                deadline=deadline,
                priority="high",
            ),
            ActionItem(
                title="Flight to London",
                action_type="travel_event",
                source_type="flight_confirmation",
                start_time=deadline,
                location="Airport",
            ),
        ],
    )

    plan = TaskPlannerService().plan_global(request)

    assert len(plan.tasks) == 2
    assert len(plan.events) == 1
    assert plan.reminders
    assert plan.tasks[0].source_type == "assignment_deadline"


def test_global_planner_uses_memory_preferences_and_existing_blocks() -> None:
    deadline = datetime(2026, 10, 10, 16, 0, tzinfo=UTC)
    request = GlobalPlanningRequest(
        user_id="user_1",
        items=[
            ActionItem(
                title="Pay rent",
                action_type="bill_due",
                source_type="bill",
                deadline=deadline,
                priority="high",
            )
        ],
        existing_blocks=[
            ScheduleBlock(
                title="Part-time shift",
                start_time=datetime(2026, 10, 10, 13, 0, tzinfo=UTC),
                end_time=datetime(2026, 10, 10, 17, 0, tzinfo=UTC),
                source_type="calendar",
            )
        ],
        memory_preferences=["Prefers reminders at least 24 hours before bills."],
    )

    plan = TaskPlannerService().plan_global(request)

    assert plan.conflicts
    assert any("memory preferences" in assumption.lower() for assumption in plan.assumptions)


@pytest.mark.asyncio
async def test_reminder_worker_email_queue_returns_draft_only_items() -> None:
    class FakeReminderWorker(ReminderWorker):
        async def due_reminders(self, now=None, limit=50):
            return [
                DueReminder(
                    id="reminder_email",
                    user_id="user_1",
                    title="Council tax bill",
                    channel="email",
                    remind_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
                ),
                DueReminder(
                    id="reminder_app",
                    user_id="user_1",
                    title="Coursework",
                    channel="in_app",
                    remind_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
                ),
            ]

    queue = await FakeReminderWorker(None).email_queue()

    assert len(queue) == 1
    assert queue[0].reminder_id == "reminder_email"
    assert "no email has been sent" in queue[0].body


@pytest.mark.asyncio
async def test_reminder_worker_sends_email_queue_after_approval() -> None:
    class FakeReminderWorker(ReminderWorker):
        async def email_queue(self, now=None, limit=50):
            return [
                EmailReminderQueueItem(
                    reminder_id="reminder_email",
                    user_id="user_1",
                    subject="Reminder due",
                    body="Reminder body",
                    remind_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
                )
            ]

        async def mark_sent(self, reminder_ids):
            self.marked = reminder_ids
            return len(reminder_ids)

    class FakeEmailService:
        async def send(self, request):
            return EmailSendResult(
                status="sent",
                provider=request.provider,
                to_email=request.to_email,
                subject=request.subject,
                dry_run=True,
            )

    worker = FakeReminderWorker(None)
    response = await worker.send_email_reminders(
        EmailReminderSendRequest(
            user_id="user_1",
            provider="dry_run",
            to_email="student@example.com",
            approved=True,
        ),
        email_service=FakeEmailService(),
    )

    assert len(response.sent) == 1
    assert response.marked_sent_count == 1
    assert worker.marked == ["reminder_email"]


@pytest.mark.asyncio
async def test_reminder_worker_does_not_mark_unapproved_email_as_sent() -> None:
    class FakeReminderWorker(ReminderWorker):
        async def email_queue(self, now=None, limit=50):
            return [
                EmailReminderQueueItem(
                    reminder_id="reminder_email",
                    user_id="user_1",
                    subject="Reminder due",
                    body="Reminder body",
                    remind_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
                )
            ]

        async def mark_sent(self, reminder_ids):
            raise AssertionError("Unapproved reminders must not be marked sent")

    class FakeEmailService:
        async def send(self, request):
            return EmailSendResult(
                status="requires_approval",
                provider=request.provider,
                to_email=request.to_email,
                subject=request.subject,
                requires_approval=True,
            )

    response = await FakeReminderWorker(None).send_email_reminders(
        EmailReminderSendRequest(
            user_id="user_1",
            provider="dry_run",
            to_email="student@example.com",
            approved=False,
        ),
        email_service=FakeEmailService(),
    )

    assert response.sent == []
    assert response.skipped[0].requires_approval is True
    assert response.marked_sent_count == 0
