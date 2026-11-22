from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.auth import CurrentUser, assert_user, get_current_user
from app.schemas.email import EmailSendRequest
from app.schemas.workflow import WorkflowAccepted
from app.workflows.service import WorkflowService
from app.core.config import get_settings


router = APIRouter()


@router.post("/send", response_model=WorkflowAccepted, status_code=status.HTTP_202_ACCEPTED)
async def enqueue_email_send(
    request: EmailSendRequest,
    response: Response,
    idempotency_key: str = Header(default_factory=lambda: str(uuid4()), alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WorkflowAccepted:
    assert_user(request.user_id, current_user)
    if not get_settings().rabbitmq_workflow_enabled:
        raise HTTPException(status_code=503, detail="Asynchronous workflow execution is disabled")
    if not request.approved:
        raise HTTPException(status_code=403, detail="Email sending requires explicit user approval")
    response.status_code = status.HTTP_202_ACCEPTED
    return await WorkflowService(session).create_email_send_workflow(
        request,
        request_id=idempotency_key,
    )
