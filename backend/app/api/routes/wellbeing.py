from fastapi import APIRouter

from app.agents.wellbeing.service import WellbeingAgentService
from app.schemas.wellbeing import WellbeingSupportRequest, WellbeingSupportResponse

router = APIRouter()


@router.post("/support", response_model=WellbeingSupportResponse)
async def create_wellbeing_support(request: WellbeingSupportRequest) -> WellbeingSupportResponse:
    return WellbeingAgentService().support(request)
