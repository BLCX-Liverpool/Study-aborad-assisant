from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import EmailSendAttempt, EmailSendStatus
from app.schemas.email import EmailSendRequest, EmailSendResult


class EmailSendAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_idempotency_key(self, *, user_id: str, key: str | None) -> EmailSendAttempt | None:
        if not key:
            return None
        result = await self.session.execute(
            select(EmailSendAttempt).where(
                EmailSendAttempt.user_id == user_id,
                EmailSendAttempt.idempotency_key == key,
            )
        )
        return result.scalars().first()

    async def create_attempt(
        self,
        *,
        request: EmailSendRequest,
        result: EmailSendResult,
    ) -> str:
        attempt = EmailSendAttempt(
            user_id=request.user_id,
            provider=request.provider,
            to_email=request.to_email,
            from_email=request.from_email,
            subject=request.subject,
            body=request.body,
            status=_db_status(result.status),
            approved=request.approved,
            source_type=request.source_type,
            source_id=request.source_id,
            idempotency_key=request.idempotency_key,
            provider_message_id=result.provider_message_id,
            sent_at=result.sent_at,
            error=result.error,
            metadata_json={
                **request.metadata,
                "dry_run": result.dry_run,
                "result_metadata": result.metadata,
            },
        )
        self.session.add(attempt)
        await self.session.flush()
        return attempt.id

    async def update_attempt(
        self,
        *,
        attempt_id: str,
        result: EmailSendResult,
    ) -> None:
        attempt = await self.session.get(EmailSendAttempt, attempt_id)
        if attempt is None:
            return
        attempt.status = _db_status(result.status)
        attempt.provider_message_id = result.provider_message_id
        attempt.sent_at = result.sent_at
        attempt.error = result.error
        attempt.metadata_json = {
            **(attempt.metadata_json or {}),
            "dry_run": result.dry_run,
            "result_metadata": result.metadata,
        }


def result_from_attempt(attempt: EmailSendAttempt) -> EmailSendResult:
    return EmailSendResult(
        status=_schema_status(attempt.status),
        provider=attempt.provider,
        to_email=attempt.to_email,
        subject=attempt.subject,
        audit_id=attempt.id,
        provider_message_id=attempt.provider_message_id,
        sent_at=attempt.sent_at,
        requires_approval=attempt.status == EmailSendStatus.REQUIRES_APPROVAL,
        error=attempt.error,
        dry_run=bool((attempt.metadata_json or {}).get("dry_run")),
        metadata={"idempotent_replay": True},
    )


def _db_status(status: str) -> EmailSendStatus:
    if status == "requires_approval":
        return EmailSendStatus.REQUIRES_APPROVAL
    if status == "sent":
        return EmailSendStatus.SENT
    if status == "skipped":
        return EmailSendStatus.SKIPPED
    return EmailSendStatus.FAILED


def _schema_status(status: EmailSendStatus) -> str:
    return status.value
