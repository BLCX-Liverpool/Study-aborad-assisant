from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.auth import CurrentUser, assert_user, create_access_token, verify_access_token
from app.db.models import WorkflowStep
from app.db.models import EmailSendStatus
from app.agents.email.service import EmailAgentService
from app.schemas.email import EmailSendRequest, EmailSendResult
from app.messaging.consumer import RabbitMQConsumer
from app.schemas.messages import AgentTaskCommand, CURRENT_MESSAGE_SCHEMA_VERSION
from app.workflows.repository import _safe_condition_expression
from app.workers.result_service import retry_delay_seconds


def test_signed_bearer_token_binds_the_authenticated_user() -> None:
    token = create_access_token("contract-user")
    assert verify_access_token(token) == CurrentUser(id="contract-user")
    with pytest.raises(HTTPException) as mismatch:
        assert_user("other-user", verify_access_token(token))
    assert mismatch.value.status_code == 403
    with pytest.raises(HTTPException) as tampered:
        verify_access_token(token + "x")
    assert tampered.value.status_code == 401
    with pytest.raises(HTTPException):
        verify_access_token(create_access_token("expired", expires_in=-1))


def test_message_contract_emits_v2_and_accepts_previous_v1() -> None:
    current = AgentTaskCommand(
        workflow_id="wf", step_id="step", agent="travel", trace_id="trace", input_ref="ref"
    )
    previous = AgentTaskCommand.model_validate({**current.model_dump(), "schema_version": 1})
    assert current.schema_version == CURRENT_MESSAGE_SCHEMA_VERSION == 2
    assert previous.schema_version == 1
    with pytest.raises(ValidationError):
        AgentTaskCommand.model_validate({**current.model_dump(), "schema_version": 0})


def test_default_attempt_budget_reaches_all_three_retry_tiers() -> None:
    assert WorkflowStep.__table__.c.max_attempts.default.arg == 4
    assert [retry_delay_seconds(attempt) for attempt in (1, 2, 3)] == [10, 30, 120]


def test_condition_language_is_safe_and_fails_closed() -> None:
    upstream = SimpleNamespace(status="completed", result_summary="visa result approved")
    assert _safe_condition_expression("status == 'completed'", upstream)
    assert _safe_condition_expression('result contains "approved"', upstream)
    assert not _safe_condition_expression("__import__('os').system('true')", upstream)


class _Message:
    def __init__(self) -> None:
        self.acked = False
        self.rejected = False
        self.requeued = False

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, *, requeue: bool) -> None:
        self.rejected = True
        self.requeued = requeue

    async def nack(self, *, requeue: bool) -> None:
        self.requeued = requeue


@pytest.mark.asyncio
async def test_consumer_requeues_infrastructure_errors_but_rejects_permanent_payload_errors() -> None:
    async def transient(_message) -> None:
        raise ConnectionError("database connection dropped")

    transient_message = _Message()
    await RabbitMQConsumer("study.travel.q", transient)._on_message(transient_message)  # type: ignore[arg-type]
    assert transient_message.requeued is True
    assert transient_message.rejected is False

    async def permanent(_message) -> None:
        AgentTaskCommand.model_validate({"schema_version": 999})

    permanent_message = _Message()
    await RabbitMQConsumer("study.travel.q", permanent)._on_message(permanent_message)  # type: ignore[arg-type]
    assert permanent_message.rejected is True
    assert permanent_message.requeued is False


@pytest.mark.asyncio
async def test_provider_success_followed_by_audit_failure_never_sends_twice() -> None:
    queued = SimpleNamespace(
        status=EmailSendStatus.QUEUED,
        provider="dry_run",
        to_email="student@example.com",
        subject="Reminder",
        id="audit-1",
        provider_message_id=None,
        sent_at=None,
        error=None,
        metadata_json={},
    )

    class Audit:
        existing = None

        async def find_by_idempotency_key(self, **_kwargs):
            return self.existing

        async def reserve_attempt(self, _request):
            self.existing = queued
            return queued.id

        async def update_attempt(self, **_kwargs):
            raise ConnectionError("audit database unavailable after provider success")

    class Provider:
        calls = 0

        async def send(self, request):
            self.calls += 1
            return EmailSendResult(
                status="sent", provider=request.provider, to_email=request.to_email,
                subject=request.subject, provider_message_id="provider-1"
            )

    audit = Audit()
    provider = Provider()
    service = EmailAgentService(providers={"dry_run": provider}, audit_repository=audit)
    request = EmailSendRequest(
        user_id="u", to_email="student@example.com", subject="Reminder", body="Body",
        approved=True, idempotency_key="stable"
    )
    with pytest.raises(ConnectionError):
        await service.send(request)
    replay = await service.send(request)
    assert replay.status == "queued"
    assert provider.calls == 1
