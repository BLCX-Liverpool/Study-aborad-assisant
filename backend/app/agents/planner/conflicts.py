from datetime import datetime, timedelta

from app.schemas.common import PlannedEvent, PlannedTask
from app.schemas.planner import ConflictFinding, ScheduleBlock


class ConflictChecker:
    def check(
        self,
        tasks: list[PlannedTask],
        events: list[PlannedEvent],
        existing_blocks: list[ScheduleBlock],
    ) -> list[ConflictFinding]:
        planned_blocks = [
            *[_block_from_task(task) for task in tasks],
            *[_block_from_event(event) for event in events],
        ]
        planned_blocks = [block for block in planned_blocks if block is not None]

        findings: list[ConflictFinding] = []
        for planned in planned_blocks:
            for existing in existing_blocks:
                if _overlaps(planned.start_time, planned.end_time, existing.start_time, existing.end_time):
                    findings.append(
                        ConflictFinding(
                            message=f"{planned.title} overlaps with {existing.title}.",
                            planned_title=planned.title,
                            existing_title=existing.title,
                            planned_start=planned.start_time,
                            planned_end=planned.end_time,
                            existing_start=existing.start_time,
                            existing_end=existing.end_time,
                        )
                    )
        return findings


def _block_from_task(task: PlannedTask) -> ScheduleBlock | None:
    if task.start_time and task.estimated_minutes:
        return ScheduleBlock(
            title=task.title,
            start_time=task.start_time,
            end_time=task.start_time + timedelta(minutes=task.estimated_minutes),
            source_type=task.source_type,
            source_id=task.source_id,
        )
    if task.start_time and task.deadline:
        return ScheduleBlock(
            title=task.title,
            start_time=task.start_time,
            end_time=task.deadline,
            source_type=task.source_type,
            source_id=task.source_id,
        )
    return None


def _block_from_event(event: PlannedEvent) -> ScheduleBlock | None:
    if event.start_time and event.end_time:
        return ScheduleBlock(
            title=event.title,
            start_time=event.start_time,
            end_time=event.end_time,
            source_type=event.source_type,
            source_id=event.source_id,
        )
    return None


def _overlaps(
    start_a: datetime,
    end_a: datetime,
    start_b: datetime,
    end_b: datetime,
) -> bool:
    return start_a < end_b and start_b < end_a

