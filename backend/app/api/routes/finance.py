from fastapi import APIRouter

from app.agents.finance.bill_verifier import FinanceBillVerifier
from app.agents.finance.service import FinanceAgentService
from app.core.llm import get_llm_client
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
async def create_budget_plan(request: FinancePlanRequest) -> FinancePlanOutput:
    return FinanceAgentService().plan_budget(request)


@router.post("/bills/parse", response_model=FinanceBillParseOutput)
async def parse_finance_bill(request: FinanceBillParseRequest) -> FinanceBillParseOutput:
    return await FinanceAgentService(bill_verifier=FinanceBillVerifier(get_llm_client())).parse_bill_async(request)


@router.post("/goals/review", response_model=BudgetGoalOutput)
async def review_budget_goals(request: BudgetGoalRequest) -> BudgetGoalOutput:
    return FinanceAgentService().review_goals(request)
