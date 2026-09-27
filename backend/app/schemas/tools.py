from __future__ import annotations

from datetime import date as Date

from pydantic import BaseModel, Field

from app.tools.models import ToolAvailabilityStatus, ToolCallRequest, ToolCallResult, ToolSpec


class ToolListResponse(BaseModel):
    tools: list[ToolSpec] = Field(default_factory=list)


class ToolStatusResponse(BaseModel):
    tools: list[ToolAvailabilityStatus] = Field(default_factory=list)


class WeatherForecast(BaseModel):
    date: Date | None = None
    location: str
    condition: str | None = None
    temperature_min_c: float | None = None
    temperature_max_c: float | None = None
    precipitation_probability: int | None = None
    notes: list[str] = Field(default_factory=list)


class WeatherLookupRequest(BaseModel):
    location: str
    start_date: Date | None = None
    days: int = Field(default=3, ge=1, le=7)


class WeatherLookupResponse(BaseModel):
    location: str
    forecasts: list[WeatherForecast] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    source: str = "open-meteo"
    recoverable_error: str | None = None


__all__ = [
    "ToolCallRequest",
    "ToolCallResult",
    "ToolListResponse",
    "ToolStatusResponse",
    "ToolSpec",
    "WeatherForecast",
    "WeatherLookupRequest",
    "WeatherLookupResponse",
]
