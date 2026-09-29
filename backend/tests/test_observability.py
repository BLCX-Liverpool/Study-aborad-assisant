from datetime import UTC, datetime, timedelta

from app.api.routes.observability import build_trace_waterfall
from app.db.models import TraceSpan


def test_build_trace_waterfall_returns_depth_offsets_and_summary() -> None:
    started = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    root = TraceSpan(
        id="root",
        trace_id="trace_1",
        span_name="worker.travel.step_0",
        span_type="worker",
        status="completed",
        started_at=started,
        completed_at=started + timedelta(milliseconds=120),
        duration_ms=120,
        metadata_json={},
    )
    child = TraceSpan(
        id="child",
        trace_id="trace_1",
        parent_span_id="root",
        span_name="llm.chat",
        span_type="llm",
        status="completed",
        started_at=started + timedelta(milliseconds=20),
        completed_at=started + timedelta(milliseconds=70),
        duration_ms=50,
        metadata_json={},
    )

    response = build_trace_waterfall("trace_1", [child, root])

    assert response.found is True
    assert response.summary is not None
    assert response.summary.span_count == 2
    assert response.summary.by_type["worker"] == 120
    assert response.summary.by_type["llm"] == 50
    assert [span.span_id for span in response.spans] == ["root", "child"]
    assert response.spans[0].depth == 0
    assert response.spans[1].depth == 1
    assert response.spans[1].offset_ms == 20


def test_build_trace_waterfall_returns_not_found_for_empty_trace() -> None:
    response = build_trace_waterfall("missing", [])

    assert response.found is False
    assert response.spans == []
    assert response.summary is None
