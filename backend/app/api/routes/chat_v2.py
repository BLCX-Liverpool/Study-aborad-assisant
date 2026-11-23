from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator.repository import AgentRunRecorder, RouterObservationRepository, TraceSpanRepository
from app.agents.orchestrator.service import StudyAbroadOrchestrator
from app.agents.router.service import IntentRouter
from app.core.database import get_session
from app.core.auth import CurrentUser, assert_user, get_current_user
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
    """Reuse the API preflight route once, then preserve normal rerouting semantics."""

    def __init__(self, output: RouterOutput, *, fallback: IntentRouter) -> None:
        self.output = output
        self.fallback = fallback
        self._used_precomputed_output = False

    async def route_async(self, *args, **kwargs) -> RouterOutput:
        if not self._used_precomputed_output:
            self._used_precomputed_output = True
            return self.output
        return await self.fallback.route_async(*args, **kwargs)


@router.post("", response_model=ChatResponse | WorkflowAccepted)
async def chat_v2(
    request: ChatV2Request,
    response: Response,
    idempotency_key: str = Header(default_factory=lambda: str(uuid4()), alias="Idempotency-Key"),
    current_user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ChatResponse | WorkflowAccepted:
    assert_user(request.user_id, current_user)
    if request.execution_mode == "async" and not get_settings().rabbitmq_workflow_enabled:
        raise HTTPException(status_code=503, detail="Asynchronous workflow execution is disabled")
    # Routing remains synchronous so safety-sensitive wellbeing and clarification
    # responses never depend on asynchronous queue availability.
    short_term_store = RedisShortTermMemoryStore(get_redis())
    routing_context = request.history
    if request.conversation_id:
        stored_context = await short_term_store.load_recent(request.conversation_id, limit=8)
        if stored_context:
            routing_context = stored_context
    intent_router = IntentRouter()
    router_output = await intent_router.route_async(
        request.message,
        uploaded_file_ids=request.uploaded_file_ids,
        agent_inputs=request.agent_inputs,
        conversation_context=routing_context,
    )
    if ExecutionPolicy().choose(router_output, request) == "async":
        response.status_code = status.HTTP_202_ACCEPTED
        return await WorkflowService(session).create_chat_workflow(
            request,
            request_id=idempotency_key,
            router_output=router_output,
        )

    memory_manager = MemoryManager(
        short_term_store=short_term_store,
        conversation_repository=ConversationRepository(session),
        long_term_repository=LongTermMemoryRepository(session),
    )
    return await StudyAbroadOrchestrator(
        router=PrecomputedRouter(router_output, fallback=intent_router),
        recorder=AgentRunRecorder(session) if request.persist_agent_runs else None,
        router_observations=RouterObservationRepository(session),
        trace_spans=TraceSpanRepository(session),
        memory_manager=memory_manager,
    ).handle_chat(request)
