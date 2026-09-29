from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator.repository import TraceSpanRepository
from app.core.database import get_session
from app.core.tracing import LatencySpan, summarize_latency_spans
from app.db.models import TraceSpan
from app.schemas.observability import TraceSpanView, TraceWaterfallResponse

router = APIRouter()


@router.get("/traces/{trace_id}/waterfall", response_model=TraceWaterfallResponse)
async def get_trace_waterfall(
    trace_id: str,
    session: AsyncSession = Depends(get_session),
) -> TraceWaterfallResponse:
    spans = await TraceSpanRepository(session).list_by_trace_id(trace_id)
    return build_trace_waterfall(trace_id, spans)


def build_trace_waterfall(trace_id: str, spans: list[TraceSpan]) -> TraceWaterfallResponse:
    if not spans:
        return TraceWaterfallResponse(trace_id=trace_id, found=False)

    started_at = min(span.started_at for span in spans)
    depths = _span_depths(spans)
    views = [
        _span_view(span, trace_started_at=started_at, depth=depths.get(span.id, 0))
        for span in sorted(spans, key=lambda item: (item.started_at, item.completed_at, item.id))
    ]
    latency_spans = [
        LatencySpan(
            trace_id=span.trace_id,
            span_id=span.id,
            parent_span_id=span.parent_span_id,
            user_id=span.user_id,
            conversation_id=span.conversation_id,
            agent_run_id=span.agent_run_id,
            span_name=span.span_name,
            span_type=span.span_type,
            status="failed" if span.status == "failed" else "completed",
            started_at=span.started_at,
            completed_at=span.completed_at,
            duration_ms=span.duration_ms,
            input_json=span.input_json,
            output_json=span.output_json,
            error=span.error,
            metadata_json=span.metadata_json or {},
        )
        for span in spans
    ]
    return TraceWaterfallResponse(
        trace_id=trace_id,
        found=True,
        summary=summarize_latency_spans(trace_id, latency_spans, persisted=True),
        spans=views,
    )


def _span_view(span: TraceSpan, *, trace_started_at: datetime, depth: int) -> TraceSpanView:
    return TraceSpanView(
        span_id=span.id,
        trace_id=span.trace_id,
        parent_span_id=span.parent_span_id,
        user_id=span.user_id,
        conversation_id=span.conversation_id,
        agent_run_id=span.agent_run_id,
        span_name=span.span_name,
        span_type=span.span_type,
        status=span.status,
        started_at=span.started_at,
        completed_at=span.completed_at,
        duration_ms=span.duration_ms,
        offset_ms=round(max((span.started_at - trace_started_at).total_seconds() * 1000, 0.0), 3),
        depth=depth,
        input_json=span.input_json,
        output_json=span.output_json,
        error=span.error,
        metadata_json=span.metadata_json or {},
    )


def _span_depths(spans: list[TraceSpan]) -> dict[str, int]:
    by_id = {span.id: span for span in spans}
    depths: dict[str, int] = {}

    def depth_for(span: TraceSpan, seen: set[str]) -> int:
        if span.id in depths:
            return depths[span.id]
        if span.id in seen or not span.parent_span_id or span.parent_span_id not in by_id:
            depths[span.id] = 0
            return 0
        parent = by_id[span.parent_span_id]
        depths[span.id] = depth_for(parent, {*seen, span.id}) + 1
        return depths[span.id]

    for span in spans:
        depth_for(span, set())
    return depths
