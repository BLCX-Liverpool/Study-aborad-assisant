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


class FitnessAgentService:
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
    candidates = [
        FitnessMemoryCandidate(
            content=f"Fitness goal preference: {request.goal}; preferred intensity: {request.preferred_intensity}.",
            requires_confirmation=True,
            confirmed=request.remember_preferences,
        )
    ]
    if request.equipment:
        candidates.append(
            FitnessMemoryCandidate(
                content=f"Available fitness equipment: {', '.join(request.equipment)}.",
                requires_confirmation=True,
                confirmed=request.remember_preferences,
            )
        )
    for preference in request.memory_preferences:
        candidates.append(
            FitnessMemoryCandidate(
                content=preference,
                requires_confirmation=True,
                confirmed=request.remember_preferences,
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
