from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.email.draft_generator import EmailDraftGenerator
from app.agents.email.repository import EmailSendAuditRepository
from app.agents.email.service import EmailAgentService
from app.core.database import get_session
from app.core.llm import get_llm_client
from app.schemas.email import EmailDraftRequest, EmailDraftResponse, EmailProviderStatus, EmailSendRequest, EmailSendResult

router = APIRouter()


@router.post("/drafts", response_model=EmailDraftResponse)
async def create_email_draft(request: EmailDraftRequest) -> EmailDraftResponse:
    service = EmailAgentService(
        draft_generator=EmailDraftGenerator(get_llm_client()),
    )
    return await service.create_draft(request)


@router.get("/providers/status", response_model=list[EmailProviderStatus])
async def email_provider_status() -> list[EmailProviderStatus]:
    service = EmailAgentService(
        draft_generator=EmailDraftGenerator(get_llm_client()),
    )
    return service.provider_statuses()


@router.post("/send", response_model=EmailSendResult)
async def send_email(
    request: EmailSendRequest,
    session: AsyncSession = Depends(get_session),
) -> EmailSendResult:
    service = EmailAgentService(
        draft_generator=EmailDraftGenerator(get_llm_client()),
        audit_repository=EmailSendAuditRepository(session),
    )
    result = await service.send(request)
    await session.commit()
    return result
