from datetime import UTC, datetime

from app.agents.email.approval import EmailApprovalGate
from app.agents.email.draft_generator import EmailDraftGenerator
from app.agents.email.providers import EmailProvider, build_email_providers
from app.agents.email.repository import EmailSendAuditRepository, result_from_attempt
from app.schemas.email import EmailDraftRequest, EmailDraftResponse, EmailProviderName, EmailProviderStatus, EmailSendRequest, EmailSendResult


class EmailAgentService:
    def __init__(
        self,
        draft_generator: EmailDraftGenerator | None = None,
        approval_gate: EmailApprovalGate | None = None,
        providers: dict[EmailProviderName, EmailProvider] | None = None,
        audit_repository: EmailSendAuditRepository | None = None,
    ) -> None:
        self.draft_generator = draft_generator
        self.approval_gate = approval_gate or EmailApprovalGate()
        self.providers = providers or build_email_providers()
        self.audit_repository = audit_repository

    async def create_draft(self, request: EmailDraftRequest) -> EmailDraftResponse:
        if self.draft_generator is None:
            raise RuntimeError("Email draft generator is not configured.")
        draft = await self.draft_generator.generate(request)
        approval = self.approval_gate.evaluate_send()
        return EmailDraftResponse(draft=draft, approval=approval)

    def provider_statuses(self) -> list[EmailProviderStatus]:
        return [provider.availability() for provider in self.providers.values()]

    async def send(self, request: EmailSendRequest) -> EmailSendResult:
        existing = None
        if self.audit_repository is not None:
            existing = await self.audit_repository.find_by_idempotency_key(
                user_id=request.user_id,
                key=request.idempotency_key,
            )
        if existing is not None:
            return result_from_attempt(existing)

        provider = self.providers.get(request.provider)
        if provider is None:
            result = EmailSendResult(
                status="failed",
                provider=request.provider,
                to_email=request.to_email,
                subject=request.subject,
                error=f"Unknown email provider: {request.provider}",
            )
            return await self._audit(request, result)

        if not request.approved:
            result = EmailSendResult(
                status="requires_approval",
                provider=request.provider,
                to_email=request.to_email,
                subject=request.subject,
                requires_approval=True,
                error="Sending email is an external action and requires explicit user approval.",
            )
            return await self._audit(request, result)

        result = await provider.send(request)
        if result.status == "sent" and result.sent_at is None:
            result = result.model_copy(update={"sent_at": datetime.now(UTC)})
        return await self._audit(request, result)

    async def _audit(self, request: EmailSendRequest, result: EmailSendResult) -> EmailSendResult:
        if self.audit_repository is None:
            return result
        audit_id = await self.audit_repository.create_attempt(request=request, result=result)
        return result.model_copy(update={"audit_id": audit_id})
