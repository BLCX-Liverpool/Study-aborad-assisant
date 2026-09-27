from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.planner.repository import PlannerRepository
from app.agents.travel.itinerary import TravelItineraryGenerator
from app.agents.travel.persistence import TravelMemoryConfirmationService, TravelPlannerPersistenceService
from app.agents.travel.service import TravelAgentService
from app.core.database import get_session
from app.memory.repository import LongTermMemoryRepository
from app.schemas.travel import (
    TravelItineraryOutput,
    TravelItineraryRequest,
    TravelMemoryConfirmRequest,
    TravelMemoryConfirmationResult,
    TravelPlanOutput,
    TravelPlanRequest,
)

router = APIRouter()


@router.post("/plan", response_model=TravelPlanOutput)
async def create_travel_plan(
    request: TravelPlanRequest,
    session: AsyncSession = Depends(get_session),
) -> TravelPlanOutput:
    output = await TravelAgentService().plan_async(request)
    planner_persistence = await TravelPlannerPersistenceService(PlannerRepository(session)).persist_plan(
        request=request,
        output=output,
    )
    memory_confirmation = await TravelMemoryConfirmationService(LongTermMemoryRepository(session)).persist_candidates(
        user_id=request.user_id,
        candidates=output.memory_candidates,
        requested=request.save_memory_candidates,
        confirmed=request.memory_confirmed,
    )
    await session.commit()
    return output.model_copy(
        update={
            "planner_persistence": planner_persistence,
            "memory_confirmation": memory_confirmation,
        }
    )


@router.post("/itinerary", response_model=TravelItineraryOutput)
async def create_travel_itinerary(
    request: TravelItineraryRequest,
    session: AsyncSession = Depends(get_session),
) -> TravelItineraryOutput:
    output = TravelItineraryGenerator().generate(request)
    planner_persistence = await TravelPlannerPersistenceService(PlannerRepository(session)).persist_itinerary(
        request=request,
        output=output,
    )
    memory_confirmation = await TravelMemoryConfirmationService(LongTermMemoryRepository(session)).persist_candidates(
        user_id=request.user_id,
        candidates=output.memory_candidates,
        requested=request.save_memory_candidates,
        confirmed=request.memory_confirmed,
    )
    await session.commit()
    return output.model_copy(
        update={
            "planner_persistence": planner_persistence,
            "memory_confirmation": memory_confirmation,
        }
    )


@router.post("/memory/confirm", response_model=TravelMemoryConfirmationResult)
async def confirm_travel_memory(
    request: TravelMemoryConfirmRequest,
    session: AsyncSession = Depends(get_session),
) -> TravelMemoryConfirmationResult:
    result = await TravelMemoryConfirmationService(LongTermMemoryRepository(session)).confirm(
        user_id=request.user_id,
        memory_ids=request.memory_ids,
    )
    await session.commit()
    return result
