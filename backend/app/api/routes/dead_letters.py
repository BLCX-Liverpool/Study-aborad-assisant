from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session
from app.db.models import MessageInbox, OutboxEvent
from app.schemas.workflow import DeadLetterActionResult, DeadLetterView


router = APIRouter()


def require_admin(x_admin_key: str | None = Header(None, alias="X-Admin-Key")) -> None:
    configured = get_settings().admin_api_key
    if not configured:
        raise HTTPException(status_code=503, detail="Admin API is disabled")
    if x_admin_key != configured:
        raise HTTPException(status_code=403, detail="Invalid admin key")


@router.get("", response_model=list[DeadLetterView], dependencies=[Depends(require_admin)])
async def list_dead_letters(session: AsyncSession = Depends(get_session)) -> list[DeadLetterView]:
    result = await session.execute(
        select(MessageInbox)
        .where(MessageInbox.status == "dead_lettered")
        .order_by(MessageInbox.received_at.desc())
        .limit(200)
    )
    return [
        DeadLetterView(
            message_id=item.message_id,
            workflow_id=item.workflow_id,
            step_id=item.step_id,
            status=item.status,
            error=item.error,
            received_at=item.received_at,
        )
        for item in result.scalars().all()
    ]


@router.post("/{message_id}/replay", response_model=DeadLetterActionResult, dependencies=[Depends(require_admin)])
async def replay_dead_letter(
    message_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeadLetterActionResult:
    original = await session.get(OutboxEvent, message_id)
    dead_record = None
    if original is None:
        dead_record = await session.scalar(
            select(MessageInbox).where(
                MessageInbox.message_id == message_id,
                MessageInbox.status == "dead_lettered",
            ).order_by(MessageInbox.received_at.desc()).limit(1)
        )
        if dead_record is None or not dead_record.payload_json or not dead_record.routing_key:
            raise HTTPException(status_code=404, detail="Dead-letter payload is unavailable")
    new_id = str(uuid4())
    payload = {
        **(original.payload_json if original is not None else dead_record.payload_json),
        "message_id": new_id,
        "causation_id": message_id,
    }
    workflow_id = str(payload.get("workflow_id") or "dead-letter")
    session.add(
        OutboxEvent(
            id=new_id,
            aggregate_type=original.aggregate_type if original is not None else "dead_letter_replay",
            aggregate_id=original.aggregate_id if original is not None else workflow_id,
            message_type=original.message_type if original is not None else str(dead_record.message_type or payload.get("message_type") or "unknown"),
            routing_key=original.routing_key if original is not None else str(dead_record.routing_key),
            payload_json=payload,
            headers_json={
                **((original.headers_json if original is not None else dead_record.headers_json) or {}),
                "replayed_from": message_id,
            },
            status="pending",
        )
    )
    await session.commit()
    return DeadLetterActionResult(
        original_message_id=message_id,
        new_message_id=new_id,
        status="replay_queued",
    )


@router.post("/{message_id}/discard", response_model=DeadLetterActionResult, dependencies=[Depends(require_admin)])
async def discard_dead_letter(
    message_id: str,
    session: AsyncSession = Depends(get_session),
) -> DeadLetterActionResult:
    result = await session.execute(
        select(MessageInbox).where(
            MessageInbox.message_id == message_id,
            MessageInbox.status == "dead_lettered",
        )
    )
    records = list(result.scalars().all())
    if not records:
        raise HTTPException(status_code=404, detail="Dead letter not found")
    for record in records:
        record.status = "discarded"
    await session.commit()
    return DeadLetterActionResult(original_message_id=message_id, status="discarded")
