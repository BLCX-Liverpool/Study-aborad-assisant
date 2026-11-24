from __future__ import annotations

import ipaddress
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("url")
    @classmethod
    def validate_optional_url(cls, value: str | None) -> str | None:
        return _safe_public_url(value) if value else None


class BrowserMcpSearchInput(StrictToolInput):
    query: str = Field(min_length=1, max_length=1000)
    search_depth: Literal["basic", "advanced", "fast", "ultra-fast"] = "basic"
    topic: Literal["general", "news"] = "general"
    max_results: int = Field(default=5, ge=5, le=10)
    include_domains: list[str] = Field(default_factory=list, max_length=10)
    exclude_domains: list[str] = Field(default_factory=list, max_length=10)
    country: str | None = Field(default=None, max_length=100)


class BrowserMcpExtractInput(StrictToolInput):
    urls: list[str] = Field(min_length=1, max_length=5)
    extraction_goal: str | None = Field(default=None, max_length=1000)
    extract_depth: Literal["basic", "advanced"] = "basic"
    format: Literal["markdown", "text"] = "markdown"
    include_images: bool = False

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, values: list[str]) -> list[str]:
        return [_safe_public_url(value) for value in values]


class BrowserMcpMapInput(StrictToolInput):
    url: str
    max_depth: int = Field(default=1, ge=1, le=2)
    max_breadth: int = Field(default=10, ge=1, le=10)
    limit: int = Field(default=30, ge=1, le=30)
    instructions: str | None = Field(default=None, max_length=1000)
    select_paths: list[str] = Field(default_factory=list, max_length=10)
    select_domains: list[str] = Field(default_factory=list, max_length=10)
    allow_external: bool = False

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _safe_public_url(value)


class BrowserMcpCrawlInput(BrowserMcpMapInput):
    limit: int = Field(default=20, ge=1, le=30)
    extract_depth: Literal["basic", "advanced"] = "basic"
    format: Literal["markdown", "text"] = "markdown"


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


def _safe_public_url(value: str) -> str:
    if len(value) > 2048:
        raise ValueError("URL exceeds 2048 characters.")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute http/https URLs are allowed.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded credentials are not allowed.")

    hostname = parsed.hostname.rstrip(".").lower()
    blocked_names = {"localhost", "metadata.google.internal", "instance-data"}
    if hostname in blocked_names or hostname.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Local, metadata, and internal hostnames are not allowed.")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return value
    if not address.is_global:
        raise ValueError("Private, loopback, link-local, and reserved IP addresses are not allowed.")
    return value
