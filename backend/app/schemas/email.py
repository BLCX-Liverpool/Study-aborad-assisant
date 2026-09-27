from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RecipientType = Literal[
    "professor",
    "teaching_assistant",
    "classmate",
    "university_department",
    "landlord",
    "service_provider",
    "other",
]

EmailTone = Literal["formal", "polite", "friendly", "urgent"]
EmailLanguage = Literal["en", "zh", "bilingual"]
EmailProviderName = Literal["dry_run", "qq", "outlook"]
EmailSendStatus = Literal["requires_approval", "queued", "sent", "failed", "skipped"]


class EmailContext(BaseModel):
    assignment_title: str | None = None
    course_code: str | None = None
    deadline: str | None = None
    recipient_name: str | None = None
    sender_name: str | None = None
    additional_context: str | None = None
    evidence_summary: list[str] = Field(default_factory=list)


class EmailDraftRequest(BaseModel):
    user_id: str
    purpose: str
    recipient_hint: str | None = None
    context: EmailContext = Field(default_factory=EmailContext)
    language: EmailLanguage = "en"
    tone_hint: EmailTone | None = None


class EmailDraft(BaseModel):
    recipient_type: RecipientType
    subject: str
    body: str
    tone: EmailTone
    missing_information: list[str] = Field(default_factory=list)
    requires_user_approval: bool = True


class EmailApprovalGateResult(BaseModel):
    action_name: str = "send_email"
    permission_level: str = "SEND"
    requires_approval: bool = True
    reason: str = "Sending email is an external action and requires explicit user approval."


class EmailDraftResponse(BaseModel):
    draft: EmailDraft
    approval: EmailApprovalGateResult


class EmailProviderStatus(BaseModel):
    provider: EmailProviderName
    available: bool
    status: str
    required_env: list[str] = Field(default_factory=list)
    missing_env: list[str] = Field(default_factory=list)
    recoverable_error: str | None = None
    metadata: dict = Field(default_factory=dict)


class EmailSendRequest(BaseModel):
    user_id: str
    provider: EmailProviderName = "dry_run"
    to_email: str
    subject: str
    body: str
    approved: bool = False
    from_email: str | None = None
    from_name: str | None = None
    reply_to: str | None = None
    idempotency_key: str | None = None
    source_type: str = "email_agent"
    source_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class EmailSendResult(BaseModel):
    status: EmailSendStatus
    provider: EmailProviderName
    to_email: str
    subject: str
    audit_id: str | None = None
    provider_message_id: str | None = None
    sent_at: datetime | None = None
    requires_approval: bool = False
    error: str | None = None
    dry_run: bool = False
    metadata: dict = Field(default_factory=dict)
