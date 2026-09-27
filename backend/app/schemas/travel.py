from __future__ import annotations

from datetime import date as Date
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import PlannedEvent, PlannedTask
from app.schemas.planner import SavedPlannerOutput
from app.schemas.tools import WeatherForecast
from app.schemas.action import ActionItem
from app.tools.models import ToolAvailabilityStatus

TravelPurpose = Literal[
    "airport_arrival",
    "city_trip",
    "academic_trip",
    "visa_or_immigration",
    "home_visit",
    "other",
]

TravelSourceType = Literal["user_provided", "provider_verified", "estimated", "unavailable"]


class TravelPlanRequest(BaseModel):
    user_id: str
    origin: str
    destination: str
    depart_at: datetime | None = None
    return_at: datetime | None = None
    purpose: TravelPurpose = "other"
    budget_amount: float | None = Field(default=None, ge=0)
    currency: str = "GBP"
    accommodation_needed: bool = False
    notes: str | None = None
    constraints: list[str] = Field(default_factory=list)
    persist_to_planner: bool = False
    planner_confirmed: bool = False
    save_memory_candidates: bool = False
    memory_confirmed: bool = False


class TravelPlanOutput(BaseModel):
    summary: str
    checklist: list[PlannedTask] = Field(default_factory=list)
    itinerary: list[PlannedEvent] = Field(default_factory=list)
    route_suggestions: list["RouteSuggestion"] = Field(default_factory=list)
    place_suggestions: list["TravelPlaceSuggestion"] = Field(default_factory=list)
    weather_forecasts: list[WeatherForecast] = Field(default_factory=list)
    budget_breakdown: list["TravelBudgetItem"] = Field(default_factory=list)
    information_sources: list["TravelInformationSource"] = Field(default_factory=list)
    tool_statuses: list[ToolAvailabilityStatus] = Field(default_factory=list)
    memory_candidates: list["TravelMemoryCandidate"] = Field(default_factory=list)
    planner_persistence: "TravelPlannerPersistenceResult | None" = None
    memory_confirmation: "TravelMemoryConfirmationResult | None" = None
    required_documents: list[str] = Field(default_factory=list)
    budget_notes: list[str] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    booking_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    requires_booking_approval: bool = True


class TravelBudgetItem(BaseModel):
    category: str
    estimated_amount: float | None = Field(default=None, ge=0)
    currency: str
    notes: str | None = None
    source: TravelSourceType = "estimated"
    confidence: float = Field(default=0.35, ge=0.0, le=1.0)
    estimate_basis: str | None = None


class RouteSuggestion(BaseModel):
    origin: str
    destination: str
    mode: str
    estimated_minutes: int | None = None
    distance_km: float | None = Field(default=None, ge=0)
    source: TravelSourceType = "estimated"
    confidence: float = Field(default=0.35, ge=0.0, le=1.0)
    provider_name: str | None = None
    provider_metadata: dict = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class TravelPlaceSuggestion(BaseModel):
    name: str
    category: str
    location: str
    source: TravelSourceType = "unavailable"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provider_name: str | None = None
    notes: list[str] = Field(default_factory=list)
    provider_metadata: dict = Field(default_factory=dict)


class TravelInformationSource(BaseModel):
    name: str
    source_type: TravelSourceType
    description: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    tool_name: str | None = None


class TravelMemoryCandidate(BaseModel):
    id: str | None = None
    content: str
    namespace: str = "travel"
    requires_confirmation: bool = True
    confirmed: bool = False
    source_type: str = "travel_agent"
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)


class TravelPlannerPersistenceResult(BaseModel):
    status: Literal["not_requested", "needs_confirmation", "saved", "failed"] = "not_requested"
    saved: SavedPlannerOutput | None = None
    conflicts: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    error: str | None = None


class TravelMemoryConfirmationResult(BaseModel):
    status: Literal["not_requested", "pending_confirmation", "confirmed", "failed"] = "not_requested"
    candidate_count: int = 0
    pending_memory_ids: list[str] = Field(default_factory=list)
    confirmed_memory_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    error: str | None = None


class TravelMemoryConfirmRequest(BaseModel):
    user_id: str
    memory_ids: list[str] = Field(default_factory=list)


class TravelItineraryDay(BaseModel):
    date: Date
    theme: str
    events: list[PlannedEvent] = Field(default_factory=list)
    weather: WeatherForecast | None = None
    notes: list[str] = Field(default_factory=list)


class TravelItineraryRequest(TravelPlanRequest):
    preferred_pace: Literal["relaxed", "balanced", "intensive"] = "balanced"
    weather_forecasts: list[WeatherForecast] = Field(default_factory=list)


class TravelItineraryOutput(BaseModel):
    summary: str
    days: list[TravelItineraryDay] = Field(default_factory=list)
    budget_breakdown: list[TravelBudgetItem] = Field(default_factory=list)
    route_suggestions: list[RouteSuggestion] = Field(default_factory=list)
    place_suggestions: list[TravelPlaceSuggestion] = Field(default_factory=list)
    information_sources: list[TravelInformationSource] = Field(default_factory=list)
    tool_statuses: list[ToolAvailabilityStatus] = Field(default_factory=list)
    memory_candidates: list[TravelMemoryCandidate] = Field(default_factory=list)
    planner_persistence: TravelPlannerPersistenceResult | None = None
    memory_confirmation: TravelMemoryConfirmationResult | None = None
    planner_items: list[ActionItem] = Field(default_factory=list)
    checklist: list[PlannedTask] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    requires_booking_approval: bool = True
