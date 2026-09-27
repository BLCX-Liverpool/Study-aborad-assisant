from app.agents.email.approval import EmailApprovalGate
from app.agents.email.providers import DryRunEmailProvider, SmtpEmailProvider
from app.agents.email.recipient_classifier import RecipientClassifier
from app.agents.email.service import EmailAgentService
from app.agents.email.style_policy import EmailStylePolicyResolver
from app.schemas.email import EmailSendRequest


def test_recipient_classifier_detects_professor() -> None:
    recipient_type = RecipientClassifier().classify(
        recipient_hint="Professor Smith",
        purpose="Ask for coursework extension.",
    )

    assert recipient_type == "professor"


def test_recipient_classifier_detects_landlord() -> None:
    recipient_type = RecipientClassifier().classify(
        recipient_hint="letting agency",
        purpose="Ask about tenancy letter.",
    )

    assert recipient_type == "landlord"


def test_style_policy_defaults_to_formal_for_professor() -> None:
    policy = EmailStylePolicyResolver().resolve("professor")

    assert policy.tone == "formal"
    assert "Professor" in policy.salutation


def test_approval_gate_requires_send_approval() -> None:
    result = EmailApprovalGate().evaluate_send()

    assert result.permission_level == "SEND"
    assert result.requires_approval is True


def test_smtp_provider_reports_missing_configuration() -> None:
    provider = SmtpEmailProvider(
        name="qq",
        host="smtp.qq.com",
        port=465,
        username="",
        password="",
        from_email="",
        from_name="Study Abroad Assistant",
        use_ssl=True,
        use_starttls=False,
        required_env=["QQ_SMTP_USERNAME", "QQ_SMTP_PASSWORD"],
    )

    status = provider.availability()

    assert status.available is False
    assert "QQ_SMTP_USERNAME" in status.missing_env
    assert "QQ_SMTP_PASSWORD" in status.missing_env


def test_smtp_provider_reports_available_configuration() -> None:
    provider = SmtpEmailProvider(
        name="outlook",
        host="smtp.office365.com",
        port=587,
        username="user@example.com",
        password="secret",
        from_email="user@example.com",
        from_name="Study Abroad Assistant",
        use_ssl=False,
        use_starttls=True,
        required_env=["OUTLOOK_SMTP_USERNAME", "OUTLOOK_SMTP_PASSWORD"],
    )

    status = provider.availability()

    assert status.available is True
    assert status.metadata["use_starttls"] is True


async def _send_with_fake_audit(request: EmailSendRequest):
    class FakeAudit:
        def __init__(self):
            self.created = []

        async def find_by_idempotency_key(self, *, user_id, key):
            return None

        async def create_attempt(self, *, request, result):
            self.created.append((request, result))
            return "audit_1"

    audit = FakeAudit()
    service = EmailAgentService(
        providers={"dry_run": DryRunEmailProvider()},
        audit_repository=audit,
    )
    return await service.send(request), audit


import pytest


@pytest.mark.asyncio
async def test_email_send_requires_explicit_approval_and_audits_attempt() -> None:
    request = EmailSendRequest(
        user_id="user_1",
        provider="dry_run",
        to_email="student@example.com",
        subject="Reminder",
        body="Please check this reminder.",
        approved=False,
    )

    result, audit = await _send_with_fake_audit(request)

    assert result.status == "requires_approval"
    assert result.requires_approval is True
    assert result.audit_id == "audit_1"
    assert audit.created[0][1].status == "requires_approval"


@pytest.mark.asyncio
async def test_email_send_dry_run_succeeds_after_approval_and_audits() -> None:
    request = EmailSendRequest(
        user_id="user_1",
        provider="dry_run",
        to_email="student@example.com",
        subject="Reminder",
        body="Please check this reminder.",
        approved=True,
        idempotency_key="email_1",
    )

    result, audit = await _send_with_fake_audit(request)

    assert result.status == "sent"
    assert result.dry_run is True
    assert result.audit_id == "audit_1"
    assert result.sent_at is not None
    assert audit.created[0][0].idempotency_key == "email_1"
