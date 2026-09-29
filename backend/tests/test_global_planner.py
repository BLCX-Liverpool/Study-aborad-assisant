import json
from datetime import UTC, datetime, timedelta

import pytest

from app.agents.planner.global_planner import GlobalPlanner
from app.agents.planner.reminder_worker import ReminderWorker
from app.agents.planner.service import TaskPlannerService
from app.core.llm import ChatResponse
from app.schemas.action import ActionItem
from app.schemas.email import EmailSendResult
from app.schemas.planner import DueReminder, EmailReminderQueueItem, EmailReminderSendRequest, GlobalPlanningRequest, ScheduleBlock


class FakePlannerLlm:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def chat(self, request):
        self.requests.append(request)
        return ChatResponse(content=json.dumps(self.payload), model="fake-planner")


def _planner_service(payload) -> TaskPlannerService:
    return TaskPlannerService(global_planner=GlobalPlanner(FakePlannerLlm(payload)))


@pytest.mark.asyncio
async def test_global_planner_uses_llm_tot_candidates_to_plan() -> None:
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
    payload = {
        "candidates": [
            {
                "strategy": "llm_deadline_safe",
                "rationale": "Start early, split coursework, and prepare for travel.",
                "tasks": [
                    {
                        "title": "Requirement review: COMP702 Assignment deadline",
                        "description": "Read the brief and mark constraints.",
                        "source_type": "assignment_deadline",
                        "start_time": "2026-10-02T09:00:00Z",
                        "deadline": "2026-10-10T16:00:00Z",
                        "estimated_minutes": 90,
                        "priority": "high",
                        "evidence": [],
                    },
                    {
                        "title": "Research and outline: COMP702 Assignment deadline",
                        "description": "Collect sources and outline sections.",
                        "source_type": "assignment_deadline",
                        "start_time": "2026-10-04T09:00:00Z",
                        "deadline": "2026-10-10T16:00:00Z",
                        "estimated_minutes": 120,
                        "priority": "high",
                        "evidence": [],
                    },
                    {
                        "title": "Draft: COMP702 Assignment deadline",
                        "description": "Write the first full draft.",
                        "source_type": "assignment_deadline",
                        "start_time": "2026-10-07T09:00:00Z",
                        "deadline": "2026-10-10T16:00:00Z",
                        "estimated_minutes": 180,
                        "priority": "high",
                        "evidence": [],
                    },
                    {
                        "title": "Review and submit: COMP702 Assignment deadline",
                        "description": "Check rubric alignment and submit.",
                        "source_type": "assignment_deadline",
                        "start_time": "2026-10-09T09:00:00Z",
                        "deadline": "2026-10-10T16:00:00Z",
                        "estimated_minutes": 90,
                        "priority": "urgent",
                        "evidence": [],
                    },
                    {
                        "title": "Prepare for Flight to London",
                        "description": "Check route, documents, and timing.",
                        "source_type": "travel_event",
                        "start_time": "2026-10-09T18:00:00Z",
                        "deadline": "2026-10-10T16:00:00Z",
                        "estimated_minutes": 60,
                        "priority": "high",
                        "evidence": [],
                    },
                ],
                "events": [
                    {
                        "title": "Flight to London",
                        "description": None,
                        "location": "Airport",
                        "start_time": "2026-10-10T16:00:00Z",
                        "end_time": "2026-10-10T18:00:00Z",
                        "source_type": "travel_event",
                        "evidence": [],
                    }
                ],
                "assumptions": ["LLM chose an early-start candidate."],
            },
            {
                "strategy": "llm_compact",
                "rationale": "Compress work into fewer blocks.",
                "tasks": [
                    {
                        "title": "Compact coursework block",
                        "source_type": "assignment_deadline",
                        "start_time": "2026-10-10T12:30:00Z",
                        "deadline": "2026-10-10T16:00:00Z",
                        "estimated_minutes": 180,
                        "priority": "high",
                        "evidence": [],
                    }
                ],
                "events": [],
                "assumptions": [],
            },
            {
                "strategy": "llm_balanced",
                "rationale": "Moderately spaced plan.",
                "tasks": [
                    {
                        "title": "Balanced coursework block",
                        "source_type": "assignment_deadline",
                        "start_time": "2026-10-06T09:00:00Z",
                        "deadline": "2026-10-10T16:00:00Z",
                        "estimated_minutes": 120,
                        "priority": "medium",
                        "evidence": [],
                    }
                ],
                "events": [],
                "assumptions": [],
            },
        ]
    }

    plan = await _planner_service(payload).plan_global(request)

    assert len(plan.tasks) >= 4
    assert len(plan.events) == 1
    assert plan.reminders
    assert plan.selected_strategy == "llm_deadline_safe"
    assert len(plan.planning_candidates) == 3
    assert any(step.step == "select" for step in plan.thought_trace)
    assert any(task.source_type == "assignment_deadline" for task in plan.tasks)
    assert any("Review and submit" in task.title for task in plan.tasks)


@pytest.mark.asyncio
async def test_global_planner_scores_llm_candidates_against_preferences_and_existing_blocks() -> None:
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
    payload = {
        "candidates": [
            {
                "strategy": "llm_conflicting",
                "rationale": "LLM candidate that conflicts with a shift.",
                "tasks": [
                    {
                        "title": "Pay rent",
                        "source_type": "bill_due",
                        "start_time": "2026-10-10T14:00:00Z",
                        "deadline": "2026-10-10T16:00:00Z",
                        "estimated_minutes": 30,
                        "priority": "high",
                        "evidence": [],
                    }
                ],
                "events": [],
                "assumptions": [],
            },
            {
                "strategy": "llm_preference_safe",
                "rationale": "LLM candidate that respects the 24 hour bill preference.",
                "tasks": [
                    {
                        "title": "Pay rent",
                        "source_type": "bill_due",
                        "start_time": "2026-10-09T09:00:00Z",
                        "deadline": "2026-10-10T16:00:00Z",
                        "estimated_minutes": 30,
                        "priority": "high",
                        "evidence": [],
                    }
                ],
                "events": [],
                "assumptions": ["Respects the user's reminder preference."],
            },
        ]
    }

    plan = await _planner_service(payload).plan_global(request)

    assert plan.selected_strategy == "llm_preference_safe"
    assert plan.conflicts == []
    assert any("memory preferences" in assumption.lower() for assumption in plan.assumptions)
    assert plan.tasks[0].start_time is not None
    assert deadline - plan.tasks[0].start_time >= timedelta(hours=24)
    assert plan.planning_candidates


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
