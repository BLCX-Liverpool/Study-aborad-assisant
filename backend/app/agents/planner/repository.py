from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event, Reminder, Task
from app.schemas.planner import PlannerOutput, SavedPlannerOutput, ScheduleBlock


class PlannerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save_plan(self, user_id: str, plan: PlannerOutput) -> SavedPlannerOutput:
        task_ids_by_title: dict[str, str] = {}
        event_ids_by_title: dict[str, str] = {}
        task_ids: list[str] = []
        event_ids: list[str] = []
        reminder_ids: list[str] = []

        for planned_task in plan.tasks:
            task = Task(
                user_id=user_id,
                title=planned_task.title,
                description=planned_task.description,
                source_type=planned_task.source_type,
                source_id=planned_task.source_id,
                start_time=planned_task.start_time,
                deadline=planned_task.deadline,
                estimated_minutes=planned_task.estimated_minutes,
                priority=planned_task.priority,
                status=planned_task.status,
                created_by_agent="task_planner",
                evidence_json=[evidence.model_dump() for evidence in planned_task.evidence],
            )
            self.session.add(task)
            await self.session.flush()
            task_ids.append(task.id)
            task_ids_by_title[task.title] = task.id

        for planned_event in plan.events:
            event = Event(
                user_id=user_id,
                title=planned_event.title,
                description=planned_event.description,
                location=planned_event.location,
                start_time=planned_event.start_time,
                end_time=planned_event.end_time,
                source_type=planned_event.source_type,
                source_id=planned_event.source_id,
                evidence_json=[evidence.model_dump() for evidence in planned_event.evidence],
            )
            self.session.add(event)
            await self.session.flush()
            event_ids.append(event.id)
            event_ids_by_title[event.title] = event.id

        for reminder_draft in plan.reminders:
            reminder = Reminder(
                user_id=user_id,
                task_id=task_ids_by_title.get(reminder_draft.task_title or ""),
                event_id=event_ids_by_title.get(reminder_draft.event_title or ""),
                remind_at=reminder_draft.remind_at,
                channel=reminder_draft.channel,
            )
            self.session.add(reminder)
            await self.session.flush()
            reminder_ids.append(reminder.id)

        await self.session.commit()
        return SavedPlannerOutput(
            task_ids=task_ids,
            event_ids=event_ids,
            reminder_ids=reminder_ids,
        )

    async def list_schedule_blocks(self, user_id: str, limit: int = 100) -> list[ScheduleBlock]:
        blocks: list[ScheduleBlock] = []
        task_result = await self.session.execute(
            select(Task)
            .where(Task.user_id == user_id, Task.start_time.is_not(None), Task.deadline.is_not(None))
            .limit(limit)
        )
        for task in task_result.scalars().all():
            blocks.append(
                ScheduleBlock(
                    title=task.title,
                    start_time=task.start_time,
                    end_time=task.deadline,
                    source_type=task.source_type,
                    source_id=task.source_id,
                )
            )
        event_result = await self.session.execute(
            select(Event)
            .where(Event.user_id == user_id, Event.start_time.is_not(None), Event.end_time.is_not(None))
            .limit(limit)
        )
        for event in event_result.scalars().all():
            blocks.append(
                ScheduleBlock(
                    title=event.title,
                    start_time=event.start_time,
                    end_time=event.end_time,
                    source_type=event.source_type,
                    source_id=event.source_id,
                )
            )
        return blocks[:limit]
