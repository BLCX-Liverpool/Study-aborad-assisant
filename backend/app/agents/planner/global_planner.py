import json
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field, ValidationError

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.common import PlannedEvent, PlannedTask
from app.schemas.planner import (
    GlobalPlanningRequest,
    PlannerCandidateScore,
    PlannerCandidateSummary,
    PlannerOutput,
    PlannerThoughtStep,
    ScheduleBlock,
)


class LlmPlannerCandidate(BaseModel):
    strategy: str
    rationale: str
    tasks: list[PlannedTask] = Field(default_factory=list)
    events: list[PlannedEvent] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class LlmPlannerResponse(BaseModel):
    candidates: list[LlmPlannerCandidate] = Field(default_factory=list)


class CandidatePlan(BaseModel):
    strategy: str
    rationale: str
    tasks: list[PlannedTask] = Field(default_factory=list)
    events: list[PlannedEvent] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    score: PlannerCandidateScore = Field(default_factory=PlannerCandidateScore)


class GlobalPlanner:
    """LLM Tree-of-Thought global planner.

    The LLM must generate multiple candidate plans. Local code validates,
    scores, and selects; it does not generate fallback candidate plans.
    """

    def __init__(self, llm: OpenAICompatibleLLM) -> None:
        self.llm = llm

    async def plan(self, request: GlobalPlanningRequest) -> PlannerOutput:
        horizon_start = datetime.now(UTC)
        horizon_end = horizon_start + timedelta(days=request.planning_horizon_days)
        skipped = _outside_horizon(request, horizon_end)
        candidates = await self._generate_candidates(request, horizon_start=horizon_start, horizon_end=horizon_end)
        if not candidates:
            raise RuntimeError("Planner LLM did not return any valid planning candidates.")

        thought_trace = [
            PlannerThoughtStep(
                step="generate",
                strategy="llm_tot",
                rationale=f"LLM generated {len(candidates)} candidate plan(s) for Tree-of-Thought evaluation.",
            )
        ]
        for candidate in candidates:
            candidate.conflicts = _conflicts(candidate.tasks, candidate.events, request.existing_blocks)
            candidate.score = _score_candidate(candidate, request)
            thought_trace.append(
                PlannerThoughtStep(
                    step="evaluate",
                    strategy=candidate.strategy,
                    rationale=candidate.rationale,
                    score=candidate.score,
                )
            )

        selected = max(candidates, key=lambda candidate: candidate.score.total)
        thought_trace.append(
            PlannerThoughtStep(
                step="select",
                strategy=selected.strategy,
                rationale=f"Selected LLM candidate {selected.strategy!r} after deterministic validation and scoring.",
                score=selected.score,
            )
        )

        assumptions = [
            "Used LLM Tree-of-Thought planning: the LLM generated candidate plans; local validation/scoring selected the final plan.",
            f"Planning horizon: {request.planning_horizon_days} day(s).",
            f"Selected strategy: {selected.strategy}.",
        ]
        if request.existing_blocks:
            assumptions.append(f"Considered {len(request.existing_blocks)} existing schedule block(s).")
        if request.memory_preferences:
            assumptions.append("Applied memory preferences: " + "; ".join(request.memory_preferences[:3]))
        assumptions.extend(f"Skipped outside planning horizon: {title}" for title in skipped)
        assumptions.extend(selected.assumptions)

        return PlannerOutput(
            tasks=selected.tasks,
            events=selected.events,
            conflicts=selected.conflicts,
            assumptions=assumptions,
            selected_strategy=selected.strategy,
            planning_candidates=[_candidate_summary(candidate) for candidate in candidates],
            thought_trace=thought_trace,
        )

    async def _generate_candidates(
        self,
        request: GlobalPlanningRequest,
        *,
        horizon_start: datetime,
        horizon_end: datetime,
    ) -> list[CandidatePlan]:
        response = await self.llm.chat(
            ChatRequest(
                messages=[
                    ChatMessage(
                        role="system",
                        content=(
                            "You are the Task Planner Agent for a study abroad assistant. "
                            "Use Tree-of-Thought planning: create multiple distinct candidate schedules, "
                            "then return them as JSON only. Do not send email, write calendars, book travel, "
                            "or claim external actions were executed. Every candidate must respect existing_blocks, "
                            "deadline safety, user memory preferences, and the planning horizon. "
                            "Return JSON with shape: {\"candidates\":[{\"strategy\":\"...\","
                            "\"rationale\":\"...\",\"tasks\":[PlannedTask...],\"events\":[PlannedEvent...],"
                            "\"assumptions\":[\"...\"]}]}. Include ISO datetimes with timezone."
                        ),
                    ),
                    ChatMessage(
                        role="user",
                        content=json.dumps(
                            {
                                "request": request.model_dump(mode="json"),
                                "planning_horizon_start": horizon_start.isoformat(),
                                "planning_horizon_end": horizon_end.isoformat(),
                                "max_candidates": request.max_candidates,
                                "candidate_strategies_requested": request.candidate_strategies,
                                "planned_task_schema": PlannedTask.model_json_schema(),
                                "planned_event_schema": PlannedEvent.model_json_schema(),
                            },
                            ensure_ascii=False,
                        ),
                    ),
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        )
        try:
            parsed = LlmPlannerResponse.model_validate(json.loads(response.content))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError("Planner LLM returned invalid candidate JSON.") from exc

        candidates: list[CandidatePlan] = []
        for candidate in parsed.candidates[: request.max_candidates]:
            sanitized = _sanitize_candidate(candidate, request=request, horizon_end=horizon_end)
            if sanitized.tasks or sanitized.events:
                candidates.append(sanitized)
        return candidates


def _sanitize_candidate(
    candidate: LlmPlannerCandidate,
    *,
    request: GlobalPlanningRequest,
    horizon_end: datetime,
) -> CandidatePlan:
    valid_tasks = []
    valid_events = []
    assumptions = list(candidate.assumptions)

    for task in candidate.tasks:
        when = task.deadline or task.start_time
        if when and _aware(when) > horizon_end:
            assumptions.append(f"Dropped task outside planning horizon: {task.title}")
            continue
        if task.source_type not in _allowed_source_types(request):
            assumptions.append(f"Dropped task with unsupported source_type {task.source_type}: {task.title}")
            continue
        valid_tasks.append(task)

    for event in candidate.events:
        when = event.start_time or event.end_time
        if when and _aware(when) > horizon_end:
            assumptions.append(f"Dropped event outside planning horizon: {event.title}")
            continue
        if event.source_type and event.source_type not in _allowed_source_types(request):
            assumptions.append(f"Dropped event with unsupported source_type {event.source_type}: {event.title}")
            continue
        valid_events.append(event)

    return CandidatePlan(
        strategy=candidate.strategy.strip() or "llm_candidate",
        rationale=candidate.rationale.strip() or "LLM-generated candidate plan.",
        tasks=valid_tasks,
        events=valid_events,
        assumptions=assumptions,
    )


def _allowed_source_types(request: GlobalPlanningRequest) -> set[str]:
    return {item.action_type for item in request.items} | {item.source_type for item in request.items}


def _outside_horizon(request: GlobalPlanningRequest, horizon_end: datetime) -> list[str]:
    skipped = []
    for item in request.items:
        when = item.deadline or item.start_time
        if when is not None and _aware(when) > horizon_end:
            skipped.append(item.title)
    return skipped


def _score_candidate(candidate: CandidatePlan, request: GlobalPlanningRequest) -> PlannerCandidateScore:
    conflict_count = len(candidate.conflicts)
    conflict_penalty = -25.0 * conflict_count
    deadline_safety = _deadline_safety(candidate.tasks)
    priority_alignment = _priority_alignment(candidate.tasks)
    preference_alignment = _preference_alignment(candidate.tasks, request.memory_preferences)
    workload_balance = _workload_balance(candidate.tasks)
    evidence_alignment = _evidence_alignment(candidate.tasks, candidate.events)
    total = round(
        conflict_penalty
        + deadline_safety
        + priority_alignment
        + preference_alignment
        + workload_balance
        + evidence_alignment,
        3,
    )
    return PlannerCandidateScore(
        conflict_penalty=conflict_penalty,
        deadline_safety=deadline_safety,
        priority_alignment=priority_alignment,
        preference_alignment=preference_alignment,
        workload_balance=workload_balance,
        evidence_alignment=evidence_alignment,
        total=total,
    )


def _deadline_safety(tasks: list[PlannedTask]) -> float:
    scores = []
    for task in tasks:
        if not task.start_time or not task.deadline:
            scores.append(2.0)
            continue
        lead_hours = max((_aware(task.deadline) - _aware(task.start_time)).total_seconds() / 3600, 0)
        required = max((task.estimated_minutes or 60) / 60, 1)
        scores.append(min(lead_hours / required, 8.0))
    return round(sum(scores) / max(len(scores), 1), 3)


def _priority_alignment(tasks: list[PlannedTask]) -> float:
    score = 0.0
    for task in tasks:
        if task.priority in {"urgent", "high"} and task.start_time and task.deadline:
            lead_hours = (_aware(task.deadline) - _aware(task.start_time)).total_seconds() / 3600
            score += 4.0 if lead_hours >= 24 else 1.5
        elif task.priority == "medium":
            score += 1.0
    return round(score, 3)


def _preference_alignment(tasks: list[PlannedTask], preferences: list[str]) -> float:
    if not preferences:
        return 0.0
    text = " ".join(preferences).lower()
    score = 0.0
    for task in tasks:
        if not task.start_time:
            continue
        start = _aware(task.start_time)
        if "24 hour" in text or "24 hours" in text:
            if task.deadline and (_aware(task.deadline) - start) >= timedelta(hours=24):
                score += 2.0
        if "morning" in text and start.hour < 12:
            score += 1.0
        if ("avoid evening" in text or "not evening" in text) and start.hour < 18:
            score += 1.0
    return round(score, 3)


def _workload_balance(tasks: list[PlannedTask]) -> float:
    minutes_by_day: dict[str, int] = {}
    for task in tasks:
        if not task.start_time:
            continue
        key = _aware(task.start_time).date().isoformat()
        minutes_by_day[key] = minutes_by_day.get(key, 0) + (task.estimated_minutes or 60)
    if not minutes_by_day:
        return 0.0
    max_minutes = max(minutes_by_day.values())
    overloaded = max(max_minutes - 300, 0)
    return round(max(0.0, 8.0 - overloaded / 60), 3)


def _evidence_alignment(tasks: list[PlannedTask], events: list[PlannedEvent]) -> float:
    planned = [*tasks, *events]
    if not planned:
        return 0.0
    with_evidence = sum(1 for item in planned if item.evidence)
    return round(3.0 * with_evidence / len(planned), 3)


def _candidate_summary(candidate: CandidatePlan) -> PlannerCandidateSummary:
    return PlannerCandidateSummary(
        strategy=candidate.strategy,
        task_count=len(candidate.tasks),
        event_count=len(candidate.events),
        conflict_count=len(candidate.conflicts),
        score=candidate.score,
        assumptions=candidate.assumptions,
    )


def _conflicts(
    tasks: list[PlannedTask],
    events: list[PlannedEvent],
    existing_blocks: list[ScheduleBlock],
) -> list[str]:
    planned = [
        block
        for block in [
            *[_block_from_task(task) for task in tasks],
            *[_block_from_event(event) for event in events],
        ]
        if block is not None
    ]
    conflicts: list[str] = []
    for block in planned:
        for existing in existing_blocks:
            if _overlaps(block.start_time, block.end_time, _aware(existing.start_time), _aware(existing.end_time)):
                conflicts.append(f"{block.title} overlaps with existing block {existing.title}.")
    return conflicts


def _block_from_task(task: PlannedTask) -> ScheduleBlock | None:
    if not task.start_time:
        return None
    duration = timedelta(minutes=task.estimated_minutes or 60)
    return ScheduleBlock(
        title=task.title,
        start_time=_aware(task.start_time),
        end_time=_aware(task.start_time) + duration,
        source_type=task.source_type,
        source_id=task.source_id,
    )


def _block_from_event(event: PlannedEvent) -> ScheduleBlock | None:
    if not event.start_time or not event.end_time:
        return None
    return ScheduleBlock(
        title=event.title,
        start_time=_aware(event.start_time),
        end_time=_aware(event.end_time),
        source_type=event.source_type,
        source_id=event.source_id,
    )


def _overlaps(start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime) -> bool:
    return start_a < end_b and start_b < end_a


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
