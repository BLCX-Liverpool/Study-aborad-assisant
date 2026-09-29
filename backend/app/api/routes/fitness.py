from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.fitness.service import FitnessAgentService
from app.core.database import get_session
from app.core.llm import get_stage_llm_client
from app.memory.candidates import MemoryCandidateService
from app.memory.repository import LongTermMemoryRepository
from app.schemas.fitness import FitnessPlanOutput, FitnessPlanRequest

router = APIRouter()


@router.post("/plan", response_model=FitnessPlanOutput)
async def create_fitness_plan(
    request: FitnessPlanRequest,
    session: AsyncSession = Depends(get_session),
) -> FitnessPlanOutput:
    output = await FitnessAgentService(llm=get_stage_llm_client("fitness")).create_plan_async(request)
    memory_confirmation = await MemoryCandidateService(LongTermMemoryRepository(session)).persist_candidates(
        user_id=request.user_id,
        candidates=output.memory_candidates,
        requested=request.save_memory_candidates or request.remember_preferences,
        confirmed=request.memory_confirmed or request.remember_preferences,
    )
    await session.commit()
    return output.model_copy(update={"memory_confirmation": memory_confirmation})
