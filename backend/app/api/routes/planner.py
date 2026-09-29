from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.planner.repository import PlannerRepository
from app.agents.planner.reminder_worker import ReminderWorker
from app.agents.planner.service import TaskPlannerService
from app.core.database import get_session
from app.schemas.planner import (
    AssignmentPlanningRequest,
    DueReminder,
    EmailReminderQueueItem,
    EmailReminderSendRequest,
    EmailReminderSendResponse,
    GlobalPlanningRequest,
    PlannerOutput,
    SavedPlannerOutput,
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
    session: AsyncSession = Depends(get_session),
) -> list[DueReminder]:
    return await ReminderWorker(session).due_reminders()


@router.get("/reminders/email-queue", response_model=list[EmailReminderQueueItem])
async def email_reminder_queue(
    session: AsyncSession = Depends(get_session),
) -> list[EmailReminderQueueItem]:
    return await ReminderWorker(session).email_queue()


@router.post("/reminders/email-send", response_model=EmailReminderSendResponse)
async def send_email_reminders(
    request: EmailReminderSendRequest,
    session: AsyncSession = Depends(get_session),
) -> EmailReminderSendResponse:
    result = await ReminderWorker(session).send_email_reminders(request)
    await session.commit()
    return result
