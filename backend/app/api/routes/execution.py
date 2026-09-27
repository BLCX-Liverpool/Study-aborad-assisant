from fastapi import APIRouter

from app.agents.orchestrator.multi_intent_executor import MultiIntentExecutionPlanner
from app.agents.router.service import IntentRouter
from app.schemas.execution import MultiIntentExecutionPlan, MultiIntentExecutionRequest

router = APIRouter()


@router.post("/plan", response_model=MultiIntentExecutionPlan)
async def plan_multi_intent(request: MultiIntentExecutionRequest) -> MultiIntentExecutionPlan:
    structured_intents = request.structured_intents
    if not structured_intents:
        router_output = await IntentRouter().route_async(request.message)
        structured_intents = router_output.structured_intents
    return MultiIntentExecutionPlanner().plan(
        request.model_copy(update={"structured_intents": structured_intents})
    )
