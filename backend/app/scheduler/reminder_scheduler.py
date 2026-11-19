from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Reminder, ReminderStatus
from app.messaging.dispatcher import OutboxDispatcher
from app.schemas.chat import ChatRequest
from app.schemas.messages import WorkflowPrepareCommand
from app.schemas.router import RouterOutput, StructuredIntent
from app.workflows.repository import WorkflowRepository


class ReminderScheduler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = WorkflowRepository(session)
        self.dispatcher = OutboxDispatcher(session)

    async def enqueue_due(self, *, limit: int = 50) -> int:
        now = datetime.now(UTC)
        result = await self.session.execute(
            select(Reminder)
            .where(Reminder.remind_at <= now, Reminder.status == ReminderStatus.PENDING)
            .order_by(Reminder.remind_at)
            .with_for_update(skip_locked=True)
            .limit(limit)
        )
        count = 0
        for reminder in result.scalars().all():
            request_id = f"reminder:{reminder.id}"
            if await self.repository.get_by_request_id(user_id=reminder.user_id, request_id=request_id):
                continue
            workflow = await self.repository.create(
                user_id=reminder.user_id,
                conversation_id=f"reminder:{reminder.id}",
                trace_id=str(uuid4()),
                request_id=request_id,
                workflow_type="reminder",
                input_json={
                    "chat_request": ChatRequest(
                        user_id=reminder.user_id,
                        conversation_id=f"reminder:{reminder.id}",
                        message=f"为到期提醒 {reminder.id} 生成邮件提醒草稿",
                        agent_inputs={
                            "email": {
                                "purpose": "Send a due reminder after explicit user approval.",
                                "context": {"reminder_id": reminder.id, "remind_at": reminder.remind_at.isoformat()},
                            }
                        },
                    ).model_dump(mode="json"),
                    "router_output": RouterOutput(
                        primary_intent="email",
                        confidence=1.0,
                        structured_intents=[
                            StructuredIntent(
                                name="email.draft",
                                agent_intent="email",
                                confidence=1.0,
                                slots={"reminder_id": reminder.id},
                            )
                        ],
                    ).model_dump(mode="json"),
                },
            )
            command = WorkflowPrepareCommand(
                workflow_id=workflow.id,
                trace_id=workflow.trace_id,
                input_ref=f"workflow-input:{workflow.id}",
            )
            await self.dispatcher.dispatch(
                aggregate_type="workflow",
                aggregate_id=workflow.id,
                routing_key="workflow.prepare",
                message=command,
            )
            count += 1
        await self.session.commit()
        return count
