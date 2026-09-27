from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class TraceEvent(BaseModel):
    trace_id: str
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


LatencySpanStatus = Literal["completed", "failed"]


class LatencySpan(BaseModel):
    trace_id: str
    span_id: str = Field(default_factory=lambda: str(uuid4()))
    parent_span_id: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    agent_run_id: str | None = None
    span_name: str
    span_type: str
    status: LatencySpanStatus = "completed"
    started_at: datetime
    completed_at: datetime
    duration_ms: float
    input_json: dict[str, Any] | None = None
    output_json: dict[str, Any] | None = None
    error: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class LatencySpanSummaryItem(BaseModel):
    span_name: str
    span_type: str
    duration_ms: float
    status: LatencySpanStatus


class LatencyTraceSummary(BaseModel):
    trace_id: str
    total_duration_ms: float
    span_count: int
    failed_span_count: int = 0
    by_type: dict[str, float] = Field(default_factory=dict)
    slowest_spans: list[LatencySpanSummaryItem] = Field(default_factory=list)
    persisted: bool = False


@dataclass
class LatencyTraceContext:
    trace_id: str
    spans: list[LatencySpan]
    user_id: str | None = None
    conversation_id: str | None = None
    parent_span_id: str | None = None


_current_latency_context: ContextVar[LatencyTraceContext | None] = ContextVar(
    "current_latency_context",
    default=None,
)


def summarize_latency_spans(
    trace_id: str,
    spans: list[LatencySpan],
    *,
    persisted: bool = False,
    slowest_limit: int = 5,
) -> LatencyTraceSummary:
    by_type: defaultdict[str, float] = defaultdict(float)
    failed_count = 0
    for span in spans:
        by_type[span.span_type] += span.duration_ms
        if span.status == "failed":
            failed_count += 1
    slowest = sorted(spans, key=lambda item: item.duration_ms, reverse=True)[:slowest_limit]
    return LatencyTraceSummary(
        trace_id=trace_id,
        total_duration_ms=round(sum(span.duration_ms for span in spans), 3),
        span_count=len(spans),
        failed_span_count=failed_count,
        by_type={key: round(value, 3) for key, value in sorted(by_type.items())},
        slowest_spans=[
            LatencySpanSummaryItem(
                span_name=span.span_name,
                span_type=span.span_type,
                duration_ms=round(span.duration_ms, 3),
                status=span.status,
            )
            for span in slowest
        ],
        persisted=persisted,
    )


@asynccontextmanager
async def capture_latency_span(
    spans: list[LatencySpan],
    *,
    trace_id: str,
    span_name: str,
    span_type: str,
    user_id: str | None = None,
    conversation_id: str | None = None,
    agent_run_id: str | None = None,
    parent_span_id: str | None = None,
    input_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    span_id = str(uuid4())
    started_at = datetime.now(UTC)
    started = perf_counter()
    output_json: dict[str, Any] = {}
    status: LatencySpanStatus = "completed"
    error: str | None = None
    context = LatencyTraceContext(
        trace_id=trace_id,
        spans=spans,
        user_id=user_id,
        conversation_id=conversation_id,
        parent_span_id=span_id,
    )
    token = _current_latency_context.set(context)
    try:
        yield output_json
    except Exception as exc:
        status = "failed"
        error = str(exc)
        raise
    finally:
        _current_latency_context.reset(token)
        completed_at = datetime.now(UTC)
        spans.append(
            LatencySpan(
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                user_id=user_id,
                conversation_id=conversation_id,
                agent_run_id=agent_run_id,
                span_name=span_name,
                span_type=span_type,
                status=status,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=round((perf_counter() - started) * 1000, 3),
                input_json=input_json,
                output_json=output_json or None,
                error=error,
                metadata_json=metadata_json or {},
            )
        )


@asynccontextmanager
async def capture_current_latency_span(
    *,
    span_name: str,
    span_type: str,
    input_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    context = _current_latency_context.get()
    if context is None:
        yield {}
        return
    async with capture_latency_span(
        context.spans,
        trace_id=context.trace_id,
        user_id=context.user_id,
        conversation_id=context.conversation_id,
        parent_span_id=context.parent_span_id,
        span_name=span_name,
        span_type=span_type,
        input_json=input_json,
        metadata_json=metadata_json,
    ) as output:
        yield output
