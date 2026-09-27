from datetime import UTC, datetime, timedelta

from app.schemas.action import ActionItem
from app.schemas.common import PlannedEvent, PlannedTask
from app.schemas.planner import GlobalPlanningRequest, PlannerOutput


class GlobalPlanner:
    def plan(self, request: GlobalPlanningRequest) -> PlannerOutput:
        horizon_end = datetime.now(UTC) + timedelta(days=request.planning_horizon_days)
        tasks: list[PlannedTask] = []
        events: list[PlannedEvent] = []
        assumptions = [
            f"Planned action items within a {request.planning_horizon_days}-day horizon when dated.",
        ]
        if request.existing_blocks:
            assumptions.append(f"Considered {len(request.existing_blocks)} existing schedule blocks.")
        if request.memory_preferences:
            assumptions.append("Applied memory preferences: " + "; ".join(request.memory_preferences[:3]))

        for item in request.items:
            if not _within_horizon(item, horizon_end):
                assumptions.append(f"Skipped outside planning horizon: {item.title}")
                continue
            if item.action_type in {"travel_event", "appointment"}:
                events.append(_event_from_action(item))
                prep_task = _prep_task_for_event(item)
                if prep_task is not None:
                    tasks.append(prep_task)
                continue
            tasks.append(_task_from_action(item))

        conflicts = _conflicts(tasks, events, request.existing_blocks)
        return PlannerOutput(tasks=tasks, events=events, conflicts=conflicts, assumptions=assumptions)


def _within_horizon(item: ActionItem, horizon_end: datetime) -> bool:
    when = item.deadline or item.start_time
    if when is None:
        return True
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when <= horizon_end


def _task_from_action(item: ActionItem) -> PlannedTask:
    return PlannedTask(
        title=item.title,
        description=item.description,
        source_type=item.action_type,
        source_id=item.source_id,
        start_time=_default_start_time(item.deadline),
        deadline=item.deadline,
        estimated_minutes=_estimated_minutes(item),
        priority=item.priority,
        evidence=item.evidence,
    )


def _event_from_action(item: ActionItem) -> PlannedEvent:
    start_time = item.start_time or item.deadline
    return PlannedEvent(
        title=item.title,
        description=item.description,
        location=item.location,
        start_time=start_time,
        end_time=item.end_time or (start_time + timedelta(hours=2) if start_time else None),
        source_type=item.action_type,
        source_id=item.source_id,
        evidence=item.evidence,
    )


def _prep_task_for_event(item: ActionItem) -> PlannedTask | None:
    start_time = item.start_time or item.deadline
    if start_time is None:
        return None
    return PlannedTask(
        title=f"Prepare for {item.title}",
        description="Check documents, route, timing, and any required confirmation before the event.",
        source_type=item.action_type,
        source_id=item.source_id,
        start_time=start_time - timedelta(days=1, hours=1),
        deadline=start_time - timedelta(days=1),
        estimated_minutes=60,
        priority="medium",
        evidence=item.evidence,
    )


def _default_start_time(deadline: datetime | None) -> datetime | None:
    if deadline is None:
        return None
    return deadline - timedelta(hours=2)


def _estimated_minutes(item: ActionItem) -> int:
    if item.action_type == "assignment_deadline":
        return 90
    if item.action_type == "bill_due":
        return 30
    if item.action_type == "tenancy_action":
        return 45
    if item.action_type == "email_follow_up":
        return 30
    return 45


def _conflicts(
    tasks: list[PlannedTask],
    events: list[PlannedEvent],
    existing_blocks,
) -> list[str]:
    conflicts: list[str] = []
    planned = [
        (task.title, task.start_time, task.deadline)
        for task in tasks
        if task.start_time and task.deadline
    ] + [
        (event.title, event.start_time, event.end_time)
        for event in events
        if event.start_time and event.end_time
    ]
    for title, start, end in planned:
        for block in existing_blocks:
            if start < block.end_time and end > block.start_time:
                conflicts.append(f"{title} overlaps with existing block {block.title}.")
    return conflicts
