from datetime import datetime, timedelta

from app.schemas.common import PlannedEvent, PlannedTask
from app.schemas.planner import ReminderDraft


TASK_REMINDER_OFFSETS = [
    timedelta(days=3),
    timedelta(days=1),
]

EVENT_REMINDER_OFFSETS = [
    timedelta(days=1),
    timedelta(hours=2),
]


class ReminderScheduler:
    def create_reminders(
        self,
        tasks: list[PlannedTask],
        events: list[PlannedEvent],
    ) -> list[ReminderDraft]:
        reminders: list[ReminderDraft] = []

        for task in tasks:
            if task.deadline is None:
                continue
            for offset in TASK_REMINDER_OFFSETS:
                remind_at = task.deadline - offset
                if _is_before(remind_at, task.deadline):
                    reminders.append(
                        ReminderDraft(
                            title=f"Reminder: {task.title}",
                            task_title=task.title,
                            remind_at=remind_at,
                        )
                    )

        for event in events:
            if event.start_time is None:
                continue
            for offset in EVENT_REMINDER_OFFSETS:
                remind_at = event.start_time - offset
                if _is_before(remind_at, event.start_time):
                    reminders.append(
                        ReminderDraft(
                            title=f"Reminder: {event.title}",
                            event_title=event.title,
                            remind_at=remind_at,
                        )
                    )

        return reminders


def _is_before(candidate: datetime, target: datetime) -> bool:
    return candidate < target

