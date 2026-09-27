from fastapi import APIRouter

from app.agents.fitness.service import FitnessAgentService
from app.schemas.fitness import FitnessPlanOutput, FitnessPlanRequest

router = APIRouter()


@router.post("/plan", response_model=FitnessPlanOutput)
async def create_fitness_plan(request: FitnessPlanRequest) -> FitnessPlanOutput:
    return FitnessAgentService().create_plan(request)
