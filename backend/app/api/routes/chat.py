from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator.repository import AgentRunRecorder, RouterObservationRepository, TraceSpanRepository
from app.agents.orchestrator.service import StudyAbroadOrchestrator
from app.core.database import get_session
from app.core.redis import get_redis
from app.memory.manager import MemoryManager
from app.memory.repository import ConversationRepository, LongTermMemoryRepository
from app.memory.short_term import RedisShortTermMemoryStore
from app.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> ChatResponse:
    memory_manager = MemoryManager(
        short_term_store=RedisShortTermMemoryStore(get_redis()),
        conversation_repository=ConversationRepository(session),
        long_term_repository=LongTermMemoryRepository(session),
    )
    if not request.persist_agent_runs:
        return await StudyAbroadOrchestrator(
            memory_manager=memory_manager,
            router_observations=RouterObservationRepository(session),
            trace_spans=TraceSpanRepository(session),
        ).handle_chat(request)

    return await StudyAbroadOrchestrator(
        recorder=AgentRunRecorder(session),
        router_observations=RouterObservationRepository(session),
        trace_spans=TraceSpanRepository(session),
        memory_manager=memory_manager,
    ).handle_chat(request)
