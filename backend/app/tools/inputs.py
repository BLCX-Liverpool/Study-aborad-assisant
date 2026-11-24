from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrictToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinanceExchangeRateInput(StrictToolInput):
    base_currency: str = Field(min_length=3, max_length=3)
    quote_currency: str = Field(min_length=3, max_length=3)


class ReminderDraftInput(StrictToolInput):
    title: str = Field(min_length=1)
    remind_at: datetime
    channel: str = "in_app"


class CalendarDraftInput(StrictToolInput):
    title: str = Field(min_length=1)
    start_time: datetime
    end_time: datetime | None = None
    location: str | None = None


class BrowserSearchExtractInput(StrictToolInput):
    task: str = Field(min_length=1)
    url: str | None = None
    extraction_goal: str | None = None
    max_results: int = Field(default=5, ge=1, le=10)
    include_screenshot: bool = False


class MapsDirectionsInput(StrictToolInput):
    origin: str = Field(min_length=1)
    destination: str = Field(min_length=1)
    mode: str = "transit"
    depart_at: str | None = None
    alternatives: bool = True


class MapsPlacesInput(StrictToolInput):
    location: str = Field(min_length=1)
    query: str = Field(min_length=1)
    category: str | None = None
    max_results: int = Field(default=3, ge=1, le=10)
