from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.planner.repository import PlannerRepository
from app.agents.planner.reminder_worker import ReminderWorker
from app.agents.planner.service import TaskPlannerService
from app.core.database import get_session
from app.core.auth import CurrentUser, get_current_user
from app.db.models import Reminder, ReminderStatus
from app.schemas.planner import (
    AssignmentPlanningRequest,
    DueReminder,
    EmailReminderQueueItem,
    EmailReminderSendRequest,
    EmailReminderSendResponse,
    GlobalPlanningRequest,
    PlannerOutput,
    SavedPlannerOutput,
    ReminderApprovalRequest,
    ReminderApprovalResponse,
)

router = APIRouter()


@router.post("/assignment", response_model=PlannerOutput)
async def plan_assignment(request: AssignmentPlanningRequest) -> PlannerOutput:
    return TaskPlannerService().plan_assignment(request)


@router.post("/global", response_model=PlannerOutput)
async def plan_global(
    request: GlobalPlanningRequest,
    session: AsyncSession = Depends(get_session),
) -> PlannerOutput:
    if not request.existing_blocks:
        request = request.model_copy(
            update={"existing_blocks": await PlannerRepository(session).list_schedule_blocks(request.user_id)}
        )
    return await TaskPlannerService().plan_global(request)


@router.post("/save/{user_id}", response_model=SavedPlannerOutput)
async def save_plan(
    user_id: str,
    plan: PlannerOutput,
    session: AsyncSession = Depends(get_session),
) -> SavedPlannerOutput:
    return await PlannerRepository(session).save_plan(user_id=user_id, plan=plan)


@router.get("/reminders/due", response_model=list[DueReminder])
async def due_reminders(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[DueReminder]:
    return await ReminderWorker(session).due_reminders(user_id=current_user.id)


@router.get("/reminders/email-queue", response_model=list[EmailReminderQueueItem])
async def email_reminder_queue(
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[EmailReminderQueueItem]:
    return await ReminderWorker(session).email_queue(user_id=current_user.id)


@router.post("/reminders/email-send", response_model=EmailReminderSendResponse)
async def send_email_reminders(
    request: EmailReminderSendRequest,
    session: AsyncSession = Depends(get_session),
) -> EmailReminderSendResponse:
    raise HTTPException(
        status_code=410,
        detail="Synchronous reminder sending was retired; approve a reminder and let the scheduler enqueue it.",
    )


@router.post("/reminders/{reminder_id}/approval", response_model=ReminderApprovalResponse)
async def approve_reminder_delivery(
    reminder_id: str,
    request: ReminderApprovalRequest,
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReminderApprovalResponse:
    reminder = await session.get(Reminder, reminder_id)
    if reminder is None or reminder.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if reminder.status != ReminderStatus.PENDING:
        raise HTTPException(status_code=409, detail="Only pending reminders can be approved")
    reminder.recipient_email = request.recipient_email
    reminder.delivery_approved = request.approved
    reminder.approved_at = datetime.now(UTC) if request.approved else None
    reminder.idempotency_key = reminder.idempotency_key or f"email-reminder:{reminder.id}"
    await session.commit()
    return ReminderApprovalResponse(
        reminder_id=reminder.id,
        status=reminder.status,
        delivery_approved=reminder.delivery_approved,
        recipient_email=reminder.recipient_email,
    )
