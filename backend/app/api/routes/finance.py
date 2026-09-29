from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.finance.bill_verifier import FinanceBillVerifier
from app.agents.finance.service import FinanceAgentService
from app.core.database import get_session
from app.core.llm import get_llm_client
from app.memory.candidates import MemoryCandidateService
from app.memory.repository import LongTermMemoryRepository
from app.schemas.finance import (
    BudgetGoalOutput,
    BudgetGoalRequest,
    FinanceBillParseOutput,
    FinanceBillParseRequest,
    FinancePlanOutput,
    FinancePlanRequest,
)

router = APIRouter()


@router.post("/budget", response_model=FinancePlanOutput)
async def create_budget_plan(
    request: FinancePlanRequest,
    session: AsyncSession = Depends(get_session),
) -> FinancePlanOutput:
    output = FinanceAgentService().plan_budget(request)
    memory_confirmation = await MemoryCandidateService(LongTermMemoryRepository(session)).persist_candidates(
        user_id=request.user_id,
        candidates=output.memory_candidates,
        requested=request.save_memory_candidates,
        confirmed=request.memory_confirmed,
    )
    await session.commit()
    return output.model_copy(update={"memory_confirmation": memory_confirmation})


@router.post("/bills/parse", response_model=FinanceBillParseOutput)
async def parse_finance_bill(request: FinanceBillParseRequest) -> FinanceBillParseOutput:
    return await FinanceAgentService(bill_verifier=FinanceBillVerifier(get_llm_client())).parse_bill_async(request)


@router.post("/goals/review", response_model=BudgetGoalOutput)
async def review_budget_goals(
    request: BudgetGoalRequest,
    session: AsyncSession = Depends(get_session),
) -> BudgetGoalOutput:
    output = FinanceAgentService().review_goals(request)
    memory_confirmation = await MemoryCandidateService(LongTermMemoryRepository(session)).persist_candidates(
        user_id=request.user_id,
        candidates=output.memory_candidates,
        requested=request.save_memory_candidates,
        confirmed=request.memory_confirmed,
    )
    await session.commit()
    return output.model_copy(update={"memory_confirmation": memory_confirmation})
