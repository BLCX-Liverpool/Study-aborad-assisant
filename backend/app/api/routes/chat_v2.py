from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator.repository import AgentRunRecorder, RouterObservationRepository, TraceSpanRepository
from app.agents.orchestrator.service import StudyAbroadOrchestrator
from app.agents.router.service import IntentRouter
from app.core.database import get_session
from app.core.redis import get_redis
from app.memory.manager import MemoryManager
from app.memory.repository import ConversationRepository, LongTermMemoryRepository
from app.memory.short_term import RedisShortTermMemoryStore
from app.schemas.chat import ChatResponse
from app.schemas.router import RouterOutput
from app.schemas.workflow import ChatV2Request, WorkflowAccepted
from app.workflows.service import ExecutionPolicy, WorkflowService
from app.core.config import get_settings


router = APIRouter()


class PrecomputedRouter:
    def __init__(self, output: RouterOutput) -> None:
        self.output = output

    async def route_async(self, *_args, **_kwargs) -> RouterOutput:
        return self.output


@router.post("", response_model=ChatResponse | WorkflowAccepted)
async def chat_v2(
    request: ChatV2Request,
    response: Response,
    idempotency_key: str = Header(default_factory=lambda: str(uuid4()), alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> ChatResponse | WorkflowAccepted:
    if request.execution_mode == "async" and not get_settings().rabbitmq_workflow_enabled:
        raise HTTPException(status_code=503, detail="Asynchronous workflow execution is disabled")
    # Routing remains synchronous so safety-sensitive wellbeing and clarification
    # responses never depend on asynchronous queue availability.
    router_output = await IntentRouter().route_async(
        request.message,
        uploaded_file_ids=request.uploaded_file_ids,
        agent_inputs=request.agent_inputs,
    )
    if ExecutionPolicy().choose(router_output, request) == "async":
        response.status_code = status.HTTP_202_ACCEPTED
        return await WorkflowService(session).create_chat_workflow(
            request,
            request_id=idempotency_key,
            router_output=router_output,
        )

    memory_manager = MemoryManager(
        short_term_store=RedisShortTermMemoryStore(get_redis()),
        conversation_repository=ConversationRepository(session),
        long_term_repository=LongTermMemoryRepository(session),
    )
    return await StudyAbroadOrchestrator(
        router=PrecomputedRouter(router_output),
        recorder=AgentRunRecorder(session) if request.persist_agent_runs else None,
        router_observations=RouterObservationRepository(session),
        trace_spans=TraceSpanRepository(session),
        memory_manager=memory_manager,
    ).handle_chat(request)
