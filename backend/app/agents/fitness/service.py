import json

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.common import PlannedTask
from app.schemas.fitness import (
    AvailableWorkoutSlot,
    FitnessMemoryCandidate,
    FitnessPlanOutput,
    FitnessPlanRequest,
    FitnessProgressionWeek,
    WorkoutBlock,
    WorkoutDay,
)
from app.skills import LoadedSkill, SkillLoader


class FitnessAgentService:
    def __init__(self, llm: OpenAICompatibleLLM | None = None, skill_loader: SkillLoader | None = None) -> None:
        self.llm = llm
        self.skill_loader = skill_loader or SkillLoader()

    def create_plan(self, request: FitnessPlanRequest) -> FitnessPlanOutput:
        slots = request.available_slots or _default_slots()
        risk_notes = _risk_notes(request)
        workout_days = [_workout_day(request, slot) for slot in slots[:5]]
        return FitnessPlanOutput(
            summary=f"Generated a {request.plan_weeks}-week {request.goal.replace('_', ' ')} fitness plan.",
            workout_days=workout_days,
            habit_tasks=_habit_tasks(request),
            schedule_tasks=_schedule_tasks(request, workout_days),
            progression=_progression(request),
            memory_candidates=_memory_candidates(request),
            missing_information=_missing_information(request),
            risk_notes=risk_notes,
            assumptions=_assumptions(request),
        )

    async def create_plan_async(self, request: FitnessPlanRequest) -> FitnessPlanOutput:
        baseline = self.create_plan(request)
        if self.llm is None:
            return baseline
        skill = self.skill_loader.load("tanchengyi-fitness", include_references=True) or self.skill_loader.load(
            "fitness-planning", include_references=True
        )
        if skill is None:
            return baseline
        skill_plan = await self._create_skill_plan(request, baseline, skill)
        if skill_plan is None:
            return baseline
        return _merge_with_fitness_baseline(skill_plan, baseline, request, skill)

    async def _create_skill_plan(
        self,
        request: FitnessPlanRequest,
        baseline: FitnessPlanOutput,
        skill: LoadedSkill,
    ) -> FitnessPlanOutput | None:
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=_skill_system_prompt(skill),
                        ),
                        ChatMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "request": request.model_dump(mode="json"),
                                    "baseline_plan": baseline.model_dump(mode="json"),
                                    "required_output_schema": "FitnessPlanOutput",
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                    temperature=0.35,
                    response_format={"type": "json_object"},
                )
            )
            payload = json.loads(response.content)
            if isinstance(payload.get("plan"), dict):
                payload = payload["plan"]
            return FitnessPlanOutput.model_validate(payload)
        except Exception:
            return None


def _default_slots() -> list[AvailableWorkoutSlot]:
    return [
        AvailableWorkoutSlot(day_of_week="mon", duration_minutes=35),
        AvailableWorkoutSlot(day_of_week="wed", duration_minutes=35),
        AvailableWorkoutSlot(day_of_week="sat", duration_minutes=45),
    ]


def _workout_day(request: FitnessPlanRequest, slot: AvailableWorkoutSlot) -> WorkoutDay:
    duration = slot.duration_minutes
    warmup = max(5, min(10, duration // 5))
    cooldown = max(5, min(10, duration // 6))
    main_duration = max(10, duration - warmup - cooldown)
    focus = _focus_for_goal(request.goal, request.fitness_level)
    intensity = "low" if _has_safety_constraint(request) else request.preferred_intensity

    return WorkoutDay(
        day_of_week=slot.day_of_week,
        focus=focus,
        duration_minutes=duration,
        blocks=[
            WorkoutBlock(
                name="Warm-up",
                duration_minutes=warmup,
                intensity="low",
                instructions=["Easy walk or cycle", "Dynamic mobility for hips, shoulders, and ankles"],
            ),
            WorkoutBlock(
                name=focus,
                duration_minutes=main_duration,
                intensity=intensity,
                instructions=_main_instructions(request),
            ),
            WorkoutBlock(
                name="Cool-down",
                duration_minutes=cooldown,
                intensity="low",
                instructions=["Slow breathing", "Gentle stretching without pushing into pain"],
            ),
        ],
        safety_notes=_day_safety_notes(request),
    )


def _focus_for_goal(goal: str, level: str) -> str:
    if goal == "strength":
        return "Full-body strength basics" if level == "beginner" else "Progressive strength session"
    if goal == "cardio":
        return "Low-impact cardio base" if level == "beginner" else "Cardio intervals"
    if goal == "mobility":
        return "Mobility and posture reset"
    if goal == "weight_management":
        return "Mixed cardio and resistance"
    if goal == "stress_relief":
        return "Gentle movement and stress relief"
    return "Balanced fitness session"


def _main_instructions(request: FitnessPlanRequest) -> list[str]:
    equipment = {item.lower() for item in request.equipment}
    if request.goal == "strength":
        if equipment & {"dumbbell", "dumbbells", "barbell", "gym"}:
            return ["Squat or leg press", "Push movement", "Pull movement", "Hip hinge", "Core stability"]
        return ["Bodyweight squat", "Incline push-up", "Backpack row", "Glute bridge", "Dead bug"]
    if request.goal == "cardio":
        return ["Alternate easy pace and brisk pace", "Keep effort conversational", "Stop if dizzy or in pain"]
    if request.goal == "mobility":
        return ["Thoracic rotations", "Hip flexor stretch", "Hamstring mobility", "Shoulder controlled circles"]
    if request.goal == "stress_relief":
        return ["Easy walk", "Light mobility flow", "Breathing reset", "Short stretch sequence"]
    return ["Cardio warm segment", "Bodyweight strength circuit", "Core stability", "Mobility finish"]


def _habit_tasks(request: FitnessPlanRequest) -> list[PlannedTask]:
    tasks = [
        PlannedTask(
            title="Prepare workout clothes and water",
            description="Set up simple friction-reduction before the next planned workout.",
            source_type="fitness",
            estimated_minutes=10,
            priority="medium",
        ),
        PlannedTask(
            title="Log energy and soreness after workouts",
            description="Track how the plan feels so intensity can be adjusted conservatively.",
            source_type="fitness",
            estimated_minutes=5,
            priority="low",
        ),
    ]
    if not request.available_slots:
        tasks.append(
            PlannedTask(
                title="Choose weekly workout times",
                description="Add 2-3 realistic training slots around classes, commuting, and meals.",
                source_type="fitness",
                estimated_minutes=15,
                priority="high",
            )
        )
    return tasks


def _schedule_tasks(request: FitnessPlanRequest, workout_days: list[WorkoutDay]) -> list[PlannedTask]:
    tasks: list[PlannedTask] = []
    slots = request.available_slots or _default_slots()
    for index, day in enumerate(workout_days):
        slot = slots[index]
        start_time = None
        if slot.start_time:
            # PlannedTask requires a concrete datetime; until the planner chooses a
            # calendar date, keep this as a scheduler-ready floating task.
            description_time = f" preferred start {slot.start_time.strftime('%H:%M')}"
        else:
            description_time = " preferred time not specified"
        tasks.append(
            PlannedTask(
                title=f"Fitness session: {day.focus}",
                description=(
                    f"{day.day_of_week} workout, {day.duration_minutes} minutes,"
                    f"{description_time}. Task Planner should place this on the next matching weekday."
                ),
                source_type="fitness",
                source_id=f"{request.user_id}:{day.day_of_week}:{index}",
                start_time=start_time,
                estimated_minutes=day.duration_minutes,
                priority="medium",
            )
        )
    return tasks


def _progression(request: FitnessPlanRequest) -> list[FitnessProgressionWeek]:
    progression = []
    safety_limited = _has_safety_constraint(request)
    for week in range(1, request.plan_weeks + 1):
        if safety_limited:
            rule = "Keep intensity low; progress only by comfort, not by load or speed."
            review = "Review symptoms weekly and stop any aggravating movement."
        elif week == 1:
            rule = "Use baseline volume and keep effort controlled."
            review = "Record energy, soreness, and skipped sessions."
        elif week % 4 == 0:
            rule = "Hold volume steady and focus on form quality."
            review = "Deload or repeat the previous week if sleep or coursework pressure is high."
        else:
            rule = _progression_rule_for_goal(request.goal, request.fitness_level)
            review = "Increase only one variable: duration, reps, sets, or pace."
        progression.append(
            FitnessProgressionWeek(
                week=week,
                focus=_focus_for_goal(request.goal, request.fitness_level),
                progression_rule=rule,
                deload_or_review=review,
            )
        )
    return progression


def _progression_rule_for_goal(goal: str, level: str) -> str:
    if goal == "strength":
        return "Add 1-2 reps per set or one small load increase when all sets feel controlled."
    if goal == "cardio":
        return "Add 5-10 minutes total weekly duration or one short brisk interval."
    if goal == "mobility":
        return "Add one mobility drill or extend holds by 10-15 seconds."
    if goal == "weight_management":
        return "Add consistency first; then add a small cardio or resistance volume increase."
    if goal == "stress_relief":
        return "Protect consistency; increase duration only if it improves recovery."
    return "Progress gradually based on completion rate and perceived effort." if level != "beginner" else "Repeat until the schedule feels easy, then add small volume."


def _memory_candidates(request: FitnessPlanRequest) -> list[FitnessMemoryCandidate]:
    confirmed = request.memory_confirmed or request.remember_preferences
    candidates = [
        FitnessMemoryCandidate(
            content=f"Fitness goal preference: {request.goal}; preferred intensity: {request.preferred_intensity}.",
            requires_confirmation=True,
            confirmed=confirmed,
        )
    ]
    if request.equipment:
        candidates.append(
            FitnessMemoryCandidate(
                content=f"Available fitness equipment: {', '.join(request.equipment)}.",
                requires_confirmation=True,
                confirmed=confirmed,
            )
        )
    for preference in request.memory_preferences:
        candidates.append(
            FitnessMemoryCandidate(
                content=preference,
                requires_confirmation=True,
                confirmed=confirmed,
            )
        )
    return candidates


def _missing_information(request: FitnessPlanRequest) -> list[str]:
    missing = []
    if not request.available_slots:
        missing.append("available_slots")
    if not request.equipment:
        missing.append("equipment")
    return missing


def _risk_notes(request: FitnessPlanRequest) -> list[str]:
    notes = ["Stop exercise and seek qualified support if pain, dizziness, chest pain, or unusual symptoms occur."]
    if _has_safety_constraint(request):
        notes.append("Health or injury constraints were detected; the plan keeps intensity low and should be checked with a professional.")
    return notes


def _day_safety_notes(request: FitnessPlanRequest) -> list[str]:
    notes = ["Use controlled form and leave at least 1-2 reps in reserve."]
    if request.fitness_level == "beginner":
        notes.append("Start easier than expected for the first week.")
    if _has_safety_constraint(request):
        notes.append("Avoid movements that aggravate the stated constraint.")
    return notes


def _assumptions(request: FitnessPlanRequest) -> list[str]:
    assumptions = [
        "Plan is built from user-provided availability and preferences.",
        "No medical diagnosis, treatment, or nutrition prescription is provided.",
    ]
    if request.notes:
        assumptions.append("User notes were treated as context, not verified medical information.")
    if request.memory_preferences and not request.remember_preferences:
        assumptions.append("Fitness memory candidates require explicit user confirmation before long-term storage.")
    return assumptions


def _has_safety_constraint(request: FitnessPlanRequest) -> bool:
    text = " ".join([*request.constraints, request.notes or ""]).lower()
    return any(keyword in text for keyword in ("injury", "pain", "medical", "doctor", "hurt", "受伤", "疼", "医生"))


def _skill_system_prompt(skill: LoadedSkill) -> str:
    return (
        "你是留学生活助手中的 Fitness Agent。你可以使用下方 Skill 文档和 references 生成训练计划，"
        "但必须严格输出符合 FitnessPlanOutput schema 的 JSON，不要输出自由文本。"
        "保持一般健身建议边界：不做医疗诊断、不做康复处方、不做极端减重或药物建议。"
        "如果用户有疼痛、受伤、医疗限制或医生相关信息，训练强度必须保守，并加入 risk_notes。"
        "所有 workout_days 必须包含 day_of_week、focus、duration_minutes、blocks、safety_notes。"
        "每个 block 必须包含 name、duration_minutes、intensity、instructions。"
        "必须保留 habit_tasks、schedule_tasks、progression、memory_candidates、missing_information、risk_notes、assumptions、disclaimer。"
        "如果信息不足，可使用 baseline_plan 的保守结构补齐。"
        f"\n\n{skill.as_prompt_context(max_chars=22000)}"
    )


def _merge_with_fitness_baseline(
    skill_plan: FitnessPlanOutput,
    baseline: FitnessPlanOutput,
    request: FitnessPlanRequest,
    skill: LoadedSkill,
) -> FitnessPlanOutput:
    risk_notes = list(dict.fromkeys([*skill_plan.risk_notes, *baseline.risk_notes]))
    assumptions = list(
        dict.fromkeys(
            [
                *skill_plan.assumptions,
                f"Fitness plan used skill context: {skill.name}.",
                "Skill guidance was constrained by the app's non-medical safety boundary and structured output schema.",
            ]
        )
    )
    if _has_safety_constraint(request):
        skill_plan = _lower_intensity_for_safety(skill_plan)
    return skill_plan.model_copy(
        update={
            "habit_tasks": skill_plan.habit_tasks or baseline.habit_tasks,
            "schedule_tasks": skill_plan.schedule_tasks or baseline.schedule_tasks,
            "progression": skill_plan.progression or baseline.progression,
            "memory_candidates": skill_plan.memory_candidates or baseline.memory_candidates,
            "missing_information": skill_plan.missing_information or baseline.missing_information,
            "risk_notes": risk_notes,
            "assumptions": assumptions,
        }
    )


def _lower_intensity_for_safety(output: FitnessPlanOutput) -> FitnessPlanOutput:
    workout_days = []
    for day in output.workout_days:
        blocks = [block.model_copy(update={"intensity": "low"}) for block in day.blocks]
        safety_notes = list(dict.fromkeys([*day.safety_notes, "Avoid movements that aggravate the stated constraint."]))
        workout_days.append(day.model_copy(update={"blocks": blocks, "safety_notes": safety_notes}))
    return output.model_copy(update={"workout_days": workout_days})
