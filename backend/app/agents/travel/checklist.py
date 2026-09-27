from datetime import UTC, datetime, timedelta

from app.schemas.common import PlannedEvent, PlannedTask
from app.schemas.travel import TravelPlanRequest


class TravelChecklistBuilder:
    def build_tasks(self, request: TravelPlanRequest) -> list[PlannedTask]:
        tasks = [
            PlannedTask(
                title="Confirm route and travel time",
                description=f"Check practical travel options from {request.origin} to {request.destination}.",
                source_type="travel",
                deadline=_task_deadline(request.depart_at, days_before=14),
                estimated_minutes=45,
                priority="high",
            ),
            PlannedTask(
                title="Prepare travel documents",
                description="Confirm passport, visa/BRP, student ID, ticket details, and insurance documents.",
                source_type="travel",
                deadline=_task_deadline(request.depart_at, days_before=10),
                estimated_minutes=60,
                priority="high",
            ),
            PlannedTask(
                title="Check arrival logistics",
                description="Plan local transport from station or airport to the final address.",
                source_type="travel",
                deadline=_task_deadline(request.depart_at, days_before=3),
                estimated_minutes=45,
                priority="medium",
            ),
        ]

        if request.accommodation_needed:
            tasks.append(
                PlannedTask(
                    title="Shortlist accommodation options",
                    description="Compare location, cancellation policy, deposit, and check-in time.",
                    source_type="travel",
                    deadline=_task_deadline(request.depart_at, days_before=12),
                    estimated_minutes=90,
                    priority="high",
                )
            )

        if request.purpose == "visa_or_immigration":
            tasks.append(
                PlannedTask(
                    title="Verify immigration appointment requirements",
                    description="Check appointment confirmation, required originals, copies, and travel buffer.",
                    source_type="travel",
                    deadline=_task_deadline(request.depart_at, days_before=7),
                    estimated_minutes=60,
                    priority="urgent",
                )
            )

        return tasks

    def build_itinerary(self, request: TravelPlanRequest) -> list[PlannedEvent]:
        if request.depart_at is None:
            return []

        depart_at = _ensure_aware(request.depart_at)
        events = [
            PlannedEvent(
                title=f"Travel to {request.destination}",
                description=f"Depart from {request.origin}. Booking is not performed by the agent.",
                location=request.origin,
                start_time=depart_at,
                end_time=depart_at + timedelta(hours=3),
                source_type="travel",
            )
        ]

        if request.return_at is not None:
            return_at = _ensure_aware(request.return_at)
            events.append(
                PlannedEvent(
                    title=f"Return to {request.origin}",
                    description=f"Return from {request.destination}.",
                    location=request.destination,
                    start_time=return_at,
                    end_time=return_at + timedelta(hours=3),
                    source_type="travel",
                )
            )

        return events


def _task_deadline(value: datetime | None, days_before: int) -> datetime | None:
    if value is None:
        return None
    return _ensure_aware(value) - timedelta(days=days_before)


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
