from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.core.tracing import LatencyTraceSummary


class TraceSpanView(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    agent_run_id: str | None = None
    span_name: str
    span_type: str
    status: str
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    offset_ms: float
    depth: int = 0
    input_json: dict[str, Any] | None = None
    output_json: dict[str, Any] | None = None
    error: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class TraceWaterfallResponse(BaseModel):
    trace_id: str
    found: bool
    summary: LatencyTraceSummary | None = None
    spans: list[TraceSpanView] = Field(default_factory=list)
