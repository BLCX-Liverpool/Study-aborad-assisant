from datetime import time
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import PlannedTask
from app.schemas.memory import MemoryCandidatePersistResponse

FitnessGoal = Literal[
    "general_fitness",
    "strength",
    "cardio",
    "mobility",
    "weight_management",
    "stress_relief",
]
FitnessLevel = Literal["beginner", "intermediate", "advanced"]
WorkoutIntensity = Literal["low", "moderate", "high"]


class AvailableWorkoutSlot(BaseModel):
    day_of_week: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    start_time: time | None = None
    duration_minutes: int = Field(default=45, ge=10, le=180)


class FitnessPlanRequest(BaseModel):
    user_id: str
    goal: FitnessGoal = "general_fitness"
    fitness_level: FitnessLevel = "beginner"
    available_slots: list[AvailableWorkoutSlot] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    preferred_intensity: WorkoutIntensity = "moderate"
    plan_weeks: int = Field(default=2, ge=1, le=8)
    memory_preferences: list[str] = Field(default_factory=list)
    save_memory_candidates: bool = False
    memory_confirmed: bool = False
    remember_preferences: bool = False
    notes: str | None = None


class WorkoutBlock(BaseModel):
    name: str
    duration_minutes: int
    intensity: WorkoutIntensity
    instructions: list[str] = Field(default_factory=list)


class WorkoutDay(BaseModel):
    day_of_week: str
    focus: str
    duration_minutes: int
    blocks: list[WorkoutBlock] = Field(default_factory=list)
    safety_notes: list[str] = Field(default_factory=list)


class FitnessProgressionWeek(BaseModel):
    week: int
    focus: str
    progression_rule: str
    deload_or_review: str | None = None


class FitnessMemoryCandidate(BaseModel):
    namespace: str = "fitness"
    content: str
    requires_confirmation: bool = True
    confirmed: bool = False


class FitnessPlanOutput(BaseModel):
    summary: str
    workout_days: list[WorkoutDay] = Field(default_factory=list)
    habit_tasks: list[PlannedTask] = Field(default_factory=list)
    schedule_tasks: list[PlannedTask] = Field(default_factory=list)
    progression: list[FitnessProgressionWeek] = Field(default_factory=list)
    memory_candidates: list[FitnessMemoryCandidate] = Field(default_factory=list)
    memory_confirmation: MemoryCandidatePersistResponse | None = None
    missing_information: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    disclaimer: str = "This is general fitness planning support and is not medical advice."
