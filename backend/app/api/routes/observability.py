from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select

from app.agents.orchestrator.repository import TraceSpanRepository
from app.core.database import get_session
from app.core.tracing import LatencySpan, summarize_latency_spans
from app.core.config import get_settings
from app.db.models import AgentRun, MessageInbox, OutboxEvent, ToolRun, TraceSpan, WorkerHeartbeat, WorkflowRun, WorkflowStep
from app.messaging.topology import QUEUE_SPECS
from app.schemas.observability import TraceSpanView, TraceWaterfallResponse

router = APIRouter()


@router.get("/runtime/metrics")
async def workflow_runtime_metrics(
    session: AsyncSession = Depends(get_session),
) -> dict:
    workflow_rows = await session.execute(
        select(WorkflowRun.status, func.count()).group_by(WorkflowRun.status)
    )
    step_rows = await session.execute(
        select(WorkflowStep.status, func.count()).group_by(WorkflowStep.status)
    )
    pending_outbox = await session.scalar(
        select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "pending")
    )
    oldest_outbox = await session.scalar(
        select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status == "pending")
    )
    dead_letters = await session.scalar(
        select(func.count()).select_from(MessageInbox).where(MessageInbox.status == "dead_lettered")
    )
    stale_leases = await session.scalar(
        select(func.count()).select_from(WorkflowStep).where(
            WorkflowStep.status == "running",
            WorkflowStep.lease_expires_at < datetime.now(UTC),
        )
    )
    oldest_age = (
        max((datetime.now(UTC) - oldest_outbox).total_seconds(), 0.0)
        if oldest_outbox is not None
        else 0.0
    )
    now = datetime.now(UTC)
    workflow_durations = [
        (completed - started).total_seconds()
        for started, completed in (await session.execute(
            select(WorkflowRun.started_at, WorkflowRun.completed_at).where(
                WorkflowRun.started_at.is_not(None), WorkflowRun.completed_at.is_not(None)
            ).limit(1000)
        )).all()
    ]
    step_durations = [
        (completed - started).total_seconds()
        for started, completed in (await session.execute(
            select(WorkflowStep.started_at, WorkflowStep.completed_at).where(
                WorkflowStep.started_at.is_not(None), WorkflowStep.completed_at.is_not(None)
            ).limit(2000)
        )).all()
    ]
    retry_count = await session.scalar(
        select(func.coalesce(func.sum(WorkflowStep.attempt_count - 1), 0)).where(WorkflowStep.attempt_count > 1)
    )
    throughput = await session.scalar(
        select(func.count()).select_from(MessageInbox).where(
            MessageInbox.status == "processed",
            MessageInbox.processed_at >= now - timedelta(minutes=1),
        )
    )
    agent_errors = dict((await session.execute(
        select(AgentRun.agent_name, func.count()).where(AgentRun.status == "failed").group_by(AgentRun.agent_name)
    )).all())
    tool_errors = dict((await session.execute(
        select(ToolRun.tool_name, func.count()).where(ToolRun.status == "failed").group_by(ToolRun.tool_name)
    )).all())
    confirm_latency = await session.scalar(
        select(func.avg(OutboxEvent.publish_latency_ms)).where(OutboxEvent.publish_latency_ms.is_not(None))
    )
    stale_heartbeats = await session.scalar(
        select(func.count()).select_from(WorkerHeartbeat).where(
            WorkerHeartbeat.last_seen_at < now - timedelta(seconds=get_settings().observability_stale_heartbeat_seconds)
        )
    )
    queues = await _rabbit_queue_metrics()
    alerts = []
    if oldest_age >= get_settings().observability_outbox_age_alert_seconds:
        alerts.append({"code": "outbox_backlog_age", "severity": "warning", "value": oldest_age})
    if dead_letters:
        alerts.append({"code": "dead_letters_present", "severity": "critical", "value": int(dead_letters)})
    if stale_leases or stale_heartbeats:
        alerts.append({"code": "worker_heartbeat_stale", "severity": "critical", "value": int(stale_leases or 0) + int(stale_heartbeats or 0)})
    deep_queues = [item for item in queues if int(item.get("ready", 0)) >= get_settings().observability_queue_depth_alert]
    if deep_queues:
        alerts.append({"code": "rabbitmq_queue_depth", "severity": "warning", "queues": deep_queues})
    return {
        "workflows_by_status": dict(workflow_rows.all()),
        "steps_by_status": dict(step_rows.all()),
        "outbox_pending": int(pending_outbox or 0),
        "outbox_oldest_age_seconds": round(oldest_age, 3),
        "dead_letters": int(dead_letters or 0),
        "stale_worker_leases": int(stale_leases or 0),
        "stale_worker_heartbeats": int(stale_heartbeats or 0),
        "workflow_duration_seconds": _duration_summary(workflow_durations),
        "step_duration_seconds": _duration_summary(step_durations),
        "publish_confirm_latency_ms_avg": round(float(confirm_latency or 0), 3),
        "processed_messages_last_minute": int(throughput or 0),
        "retry_attempts": int(retry_count or 0),
        "agent_errors": agent_errors,
        "tool_errors": tool_errors,
        "rabbitmq_queues": queues,
        "alerts": alerts,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _duration_summary(values: list[float]) -> dict:
    if not values:
        return {"count": 0, "avg": 0.0, "max": 0.0}
    return {
        "count": len(values),
        "avg": round(sum(values) / len(values), 3),
        "max": round(max(values), 3),
    }


async def _rabbit_queue_metrics() -> list[dict]:
    settings = get_settings()
    if not settings.rabbitmq_management_url:
        return []
    vhost = quote(settings.rabbitmq_vhost, safe="")
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.get(
                f"{settings.rabbitmq_management_url.rstrip('/')}/api/queues/{vhost}",
                auth=(settings.rabbitmq_management_username, settings.rabbitmq_management_password),
            )
            response.raise_for_status()
            known = {spec.name for spec in QUEUE_SPECS}
            return [
                {
                    "name": item["name"],
                    "ready": int(item.get("messages_ready", 0)),
                    "unacked": int(item.get("messages_unacknowledged", 0)),
                    "oldest_message_age_seconds": _head_message_age(item.get("head_message_timestamp")),
                    "consumers": int(item.get("consumers", 0)),
                    "publish_rate": float((item.get("message_stats") or {}).get("publish_details", {}).get("rate", 0)),
                    "deliver_rate": float((item.get("message_stats") or {}).get("deliver_get_details", {}).get("rate", 0)),
                }
                for item in response.json()
                if item.get("name") in known
            ]
    except (httpx.HTTPError, ValueError, TypeError):
        return [{"status": "unavailable"}]


def _head_message_age(timestamp) -> float | None:
    if timestamp is None:
        return None
    try:
        numeric = float(timestamp)
        if numeric > 10_000_000_000:
            numeric /= 1000
        return round(max(datetime.now(UTC).timestamp() - numeric, 0.0), 3)
    except (TypeError, ValueError):
        return None


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
