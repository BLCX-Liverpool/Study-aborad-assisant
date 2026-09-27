from datetime import UTC, datetime, timedelta

from app.agents.planner.conflicts import ConflictChecker
from app.agents.planner.deadline_planner import AssignmentDeadlinePlanner
from app.agents.planner.reminders import ReminderScheduler
from app.agents.planner.service import TaskPlannerService
from app.schemas.assignment import AssignmentAnalysis
from app.schemas.common import PlannedTask
from app.schemas.planner import AssignmentPlanningRequest, ScheduleBlock


def test_assignment_deadline_planner_generates_default_timeline() -> None:
    deadline = datetime(2026, 10, 10, 16, 0, tzinfo=UTC)
    assignment = AssignmentAnalysis(
        course_code="COMP702",
        objective="Write a report.",
        deliverables=["Report"],
        deadline=deadline,
    )

    plan = AssignmentDeadlinePlanner().plan(assignment, source_id="file_1")

    assert len(plan.tasks) == 6
    assert plan.tasks[-1].deadline == deadline
    assert plan.tasks[-1].priority == "urgent"


def test_conflict_checker_detects_overlap() -> None:
    start = datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    task = PlannedTask(
        title="Draft report",
        source_type="assignment",
        start_time=start,
        estimated_minutes=120,
        priority="high",
    )
    existing = ScheduleBlock(
        title="Lecture",
        start_time=start + timedelta(minutes=30),
        end_time=start + timedelta(minutes=90),
    )

    conflicts = ConflictChecker().check(tasks=[task], events=[], existing_blocks=[existing])

    assert len(conflicts) == 1
    assert "overlaps" in conflicts[0].message


def test_reminder_scheduler_creates_task_reminders() -> None:
    deadline = datetime(2026, 10, 10, 16, 0, tzinfo=UTC)
    task = PlannedTask(
        title="Submit report",
        source_type="assignment",
        deadline=deadline,
        priority="urgent",
    )

    reminders = ReminderScheduler().create_reminders(tasks=[task], events=[])

    assert len(reminders) == 2
    assert reminders[0].task_title == "Submit report"


def test_task_planner_service_returns_conflicts_and_reminders() -> None:
    deadline = datetime(2026, 10, 10, 16, 0, tzinfo=UTC)
    assignment = AssignmentAnalysis(
        course_code="COMP702",
        objective="Write a report.",
        deliverables=["Report"],
        deadline=deadline,
    )
    request = AssignmentPlanningRequest(
        user_id="user_1",
        source_id="file_1",
        assignment=assignment,
        existing_blocks=[
            ScheduleBlock(
                title="Seminar",
                start_time=deadline - timedelta(days=1, hours=1),
                end_time=deadline - timedelta(days=1) + timedelta(hours=1),
            )
        ],
    )

    plan = TaskPlannerService().plan_assignment(request)

    assert plan.tasks
    assert plan.reminders
    assert plan.conflicts

