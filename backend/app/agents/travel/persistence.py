from datetime import UTC, datetime

from app.agents.planner.repository import PlannerRepository
from app.agents.planner.reminders import ReminderScheduler
from app.agents.planner.service import TaskPlannerService
from app.memory.candidates import MemoryCandidateService
from app.memory.repository import LongTermMemoryRepository
from app.schemas.planner import GlobalPlanningRequest, PlannerOutput
from app.schemas.travel import (
    TravelItineraryOutput,
    TravelMemoryCandidate,
    TravelMemoryConfirmationResult,
    TravelPlanOutput,
    TravelPlanRequest,
    TravelPlannerPersistenceResult,
)


class TravelPlannerPersistenceService:
    def __init__(
        self,
        planner_repository: PlannerRepository,
        planner_service: TaskPlannerService | None = None,
        reminder_scheduler: ReminderScheduler | None = None,
    ) -> None:
        self.planner_repository = planner_repository
        self.planner_service = planner_service or TaskPlannerService()
        self.reminder_scheduler = reminder_scheduler or ReminderScheduler()

    async def persist_plan(
        self,
        *,
        request: TravelPlanRequest,
        output: TravelPlanOutput,
    ) -> TravelPlannerPersistenceResult:
        if not request.persist_to_planner:
            return TravelPlannerPersistenceResult(status="not_requested")
        if not request.planner_confirmed:
            return TravelPlannerPersistenceResult(
                status="needs_confirmation",
                assumptions=["Travel planner handoff requires explicit user confirmation before writing tasks/events."],
            )

        plan = PlannerOutput(
            tasks=output.checklist,
            events=output.itinerary,
            reminders=self.reminder_scheduler.create_reminders(tasks=output.checklist, events=output.itinerary),
            assumptions=["Persisted from Travel Agent plan after user confirmation."],
        )
        try:
            saved = await self.planner_repository.save_plan(user_id=request.user_id, plan=plan)
        except Exception as exc:
            return TravelPlannerPersistenceResult(status="failed", error=f"{type(exc).__name__}: {exc}")
        return TravelPlannerPersistenceResult(
            status="saved",
            saved=saved,
            conflicts=plan.conflicts,
            assumptions=plan.assumptions,
        )

    async def persist_itinerary(
        self,
        *,
        request: TravelPlanRequest,
        output: TravelItineraryOutput,
    ) -> TravelPlannerPersistenceResult:
        if not request.persist_to_planner:
            return TravelPlannerPersistenceResult(status="not_requested")
        if not request.planner_confirmed:
            return TravelPlannerPersistenceResult(
                status="needs_confirmation",
                assumptions=["Travel itinerary planner handoff requires explicit user confirmation before writing tasks/events."],
            )

        existing_blocks = await self.planner_repository.list_schedule_blocks(request.user_id)
        plan = await self.planner_service.plan_global(
            GlobalPlanningRequest(
                user_id=request.user_id,
                items=output.planner_items,
                planning_horizon_days=_planning_horizon_days(request),
                existing_blocks=existing_blocks,
                memory_preferences=[candidate.content for candidate in output.memory_candidates if candidate.confirmed],
            )
        )
        try:
            saved = await self.planner_repository.save_plan(user_id=request.user_id, plan=plan)
        except Exception as exc:
            return TravelPlannerPersistenceResult(status="failed", error=f"{type(exc).__name__}: {exc}")
        return TravelPlannerPersistenceResult(
            status="saved",
            saved=saved,
            conflicts=plan.conflicts,
            assumptions=plan.assumptions,
        )


def _planning_horizon_days(request: TravelPlanRequest) -> int:
    target = request.return_at or request.depart_at
    if target is None:
        return 30
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    days = (target - datetime.now(UTC)).days + 2
    return max(1, min(days, 180))


def _travel_memory_status(status: str) -> str:
    if status in {"not_requested", "pending_confirmation", "confirmed", "failed"}:
        return status
    return "not_requested"


class TravelMemoryConfirmationService:
    def __init__(self, repository: LongTermMemoryRepository) -> None:
        self.repository = repository
        self.candidate_service = MemoryCandidateService(repository)

    async def persist_candidates(
        self,
        *,
        user_id: str,
        candidates: list[TravelMemoryCandidate],
        source_id: str | None = None,
        requested: bool = False,
        confirmed: bool = False,
    ) -> TravelMemoryConfirmationResult:
        if not requested:
            return TravelMemoryConfirmationResult(status="not_requested", candidate_count=len(candidates))
        if not candidates:
            return TravelMemoryConfirmationResult(
                status="not_requested",
                candidate_count=0,
                assumptions=["Travel Agent did not produce memory candidates for this request."],
            )

        result = await self.candidate_service.persist_candidates(
            user_id=user_id,
            candidates=candidates,
            requested=requested,
            confirmed=confirmed,
            source_id=source_id,
        )
        return TravelMemoryConfirmationResult(
            status=_travel_memory_status(result.status),
            candidate_count=result.candidate_count,
            pending_memory_ids=result.pending_memory_ids,
            confirmed_memory_ids=result.confirmed_memory_ids,
            assumptions=result.assumptions,
            error=result.error,
        )

    async def confirm(self, *, user_id: str, memory_ids: list[str]) -> TravelMemoryConfirmationResult:
        try:
            result = await self.candidate_service.confirm(user_id=user_id, memory_ids=memory_ids)
        except Exception as exc:
            return TravelMemoryConfirmationResult(
                status="failed",
                candidate_count=len(memory_ids),
                error=f"{type(exc).__name__}: {exc}",
            )
        return TravelMemoryConfirmationResult(
            status=_travel_memory_status(result.status),
            candidate_count=len(memory_ids),
            confirmed_memory_ids=result.memory_ids,
            assumptions=result.assumptions,
            error=result.error,
        )
