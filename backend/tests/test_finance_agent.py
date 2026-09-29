import json
from datetime import date

import pytest

from app.agents.finance.input_extractor import FinanceInputExtraction, FinanceInputExtractor
from app.agents.finance.csv_parser import ExpenseCsvParser
from app.agents.finance.service import FinanceAgentService
from app.agents.orchestrator.state import AgentScopedState
from app.agents.orchestrator.workers import FinanceWorker, WorkerContext
from app.core.llm import ChatResponse
from app.schemas.chat import ChatRequest
from app.schemas.finance import (
    BudgetGoalInput,
    BudgetGoalRequest,
    ExpenseItem,
    FinancePlanRequest,
    FinanceTravelBudgetInput,
)


def test_expense_csv_parser_classifies_student_costs() -> None:
    csv_content = "description,amount,currency,recurring\nRent,900,GBP,true\nGroceries,120,GBP,false\n"

    expenses = ExpenseCsvParser().parse(csv_content, default_currency="GBP")

    assert len(expenses) == 2
    assert expenses[0].category == "rent"
    assert expenses[0].recurring is True
    assert expenses[1].category == "groceries"


def test_finance_agent_flags_negative_monthly_balance() -> None:
    request = FinancePlanRequest(
        user_id="user_1",
        currency="GBP",
        monthly_income=1000,
        savings_balance=200,
        expenses=[
            ExpenseItem(category="rent", amount=850, currency="GBP", recurring=True),
            ExpenseItem(category="tuition", amount=400, currency="GBP"),
        ],
    )

    plan = FinanceAgentService().plan_budget(request)

    assert plan.projected_monthly_balance < 0
    assert any("negative" in note for note in plan.risk_notes)
    assert any(item.priority == "urgent" for item in plan.action_items)
    assert "not financial" in plan.disclaimer


def test_finance_agent_merges_csv_expenses() -> None:
    request = FinancePlanRequest(
        user_id="user_1",
        currency="GBP",
        monthly_income=1500,
        savings_balance=1000,
        expense_csv="description,amount\nTransport pass,80\nPhone SIM,12\n",
    )

    plan = FinanceAgentService().plan_budget(request)

    categories = {summary.category for summary in plan.category_summaries}
    assert {"transport", "phone"}.issubset(categories)
    assert any("Parsed 2 expense rows" in assumption for assumption in plan.assumptions)


def test_finance_budget_outputs_memory_candidates() -> None:
    request = FinancePlanRequest(
        user_id="user_1",
        currency="GBP",
        monthly_income=1200,
        savings_balance=500,
        expenses=[ExpenseItem(category="rent", amount=700, currency="GBP", recurring=True)],
        notes="我希望预算里优先保证房租和应急金。",
    )

    plan = FinanceAgentService().plan_budget(request)

    assert plan.memory_candidates
    assert all(candidate.namespace == "finance" for candidate in plan.memory_candidates)
    assert any("budget context" in candidate.content.lower() for candidate in plan.memory_candidates)


def test_finance_goal_review_outputs_memory_candidates() -> None:
    request = BudgetGoalRequest(
        user_id="user_1",
        currency="GBP",
        monthly_income=1200,
        monthly_expense=800,
        goals=[BudgetGoalInput(name="Emergency fund", target_amount=1200, priority="high")],
        memory_preferences=["Prefer conservative budget planning."],
    )

    output = FinanceAgentService().review_goals(request)

    assert output.memory_candidates
    assert any("Emergency fund" in candidate.content for candidate in output.memory_candidates)


def test_finance_agent_converts_multi_currency_expenses() -> None:
    request = FinancePlanRequest(
        user_id="user_1",
        currency="GBP",
        target_currency="GBP",
        monthly_income=1200,
        expenses=[
            ExpenseItem(category="groceries", amount=100, currency="USD"),
            ExpenseItem(category="phone", amount=50, currency="EUR"),
        ],
    )

    plan = FinanceAgentService().plan_budget(request)

    assert plan.target_currency == "GBP"
    assert plan.total_monthly_expense == 122
    assert {quote.base_currency for quote in plan.exchange_rates}.issuperset({"USD", "EUR"})
    assert any("Currency conversion" in assumption for assumption in plan.assumptions)


def test_finance_agent_generates_recurring_obligations_and_planner_items() -> None:
    request = FinancePlanRequest(
        user_id="user_1",
        currency="GBP",
        monthly_income=1500,
        expenses=[
            ExpenseItem(
                category="rent",
                amount=700,
                currency="GBP",
                description="Student rent",
                due_date=date(2026, 10, 1),
                recurring=True,
                billing_period="monthly",
            )
        ],
        lookahead_months=3,
    )

    plan = FinanceAgentService().plan_budget(request)

    assert len(plan.upcoming_obligations) == 3
    assert [item.due_date for item in plan.upcoming_obligations] == [
        date(2026, 10, 1),
        date(2026, 11, 1),
        date(2026, 12, 1),
    ]
    assert len(plan.planner_items) == 3
    assert all(item.action_type == "bill_due" for item in plan.planner_items)


def test_finance_agent_includes_travel_budget_handoff() -> None:
    request = FinancePlanRequest(
        user_id="user_1",
        currency="GBP",
        monthly_income=1500,
        travel_budget_items=[
            FinanceTravelBudgetInput(
                category="transport",
                estimated_amount=120,
                currency="GBP",
                trip_name="Manchester academic trip",
            )
        ],
    )

    plan = FinanceAgentService().plan_budget(request)

    assert any(summary.category == "travel" and summary.total_amount == 120 for summary in plan.category_summaries)
    assert plan.upcoming_obligations[0].source_type == "travel_handoff"
    assert any("Travel budget handoff" in assumption for assumption in plan.assumptions)


@pytest.mark.asyncio
async def test_finance_input_extractor_uses_llm_json_response() -> None:
    class FakeFinanceLlm:
        async def chat(self, request):
            assert request.response_format == {"type": "json_object"}
            assert "do not invent defaults" in request.messages[0].content.lower()
            return ChatResponse(
                content=json.dumps(
                    {
                        "payload": {
                            "currency": "GBP",
                            "monthly_income": 1500,
                            "expenses": [
                                {
                                    "category": "rent",
                                    "amount": 850,
                                    "currency": "GBP",
                                    "description": "Student rent",
                                    "recurring": True,
                                    "billing_period": "monthly",
                                }
                            ],
                        },
                        "missing_information": [],
                        "clarification_questions": [],
                        "confidence": 0.9,
                        "rationale": "Income and rent are explicit.",
                    }
                ),
                model="fake-finance",
            )

    extraction = await FinanceInputExtractor(llm=FakeFinanceLlm()).extract(
        message="My monthly income is £1500 and rent is £850 per month.",
    )

    assert extraction.payload["monthly_income"] == 1500
    assert extraction.payload["expenses"][0]["category"] == "rent"
    assert extraction.missing_information == []


@pytest.mark.asyncio
async def test_finance_worker_asks_for_missing_information_instead_of_using_defaults() -> None:
    class EmptyExtractor:
        async def extract(self, **kwargs):
            return FinanceInputExtraction(
                payload={},
                missing_information=["finance.monthly_income_or_savings_balance", "finance.expenses_or_obligations"],
                clarification_questions=["请提供收入和至少一项支出。"],
                confidence=0.2,
            )

    result = await FinanceWorker(input_extractor=EmptyExtractor()).run(
        WorkerContext(
            request=ChatRequest(user_id="user_1", message="帮我看看这个月预算怎么办"),
            agent_state=AgentScopedState(agent_name="finance"),
        )
    )

    assert result.artifacts == []
    assert "finance.monthly_income_or_savings_balance" in result.missing_information
    assert "finance.expenses_or_obligations" in result.missing_information
    assert result.next_actions == ["请提供收入和至少一项支出。"]
    assert result.trace_events[0]["name"] == "finance.input_needs_clarification"


@pytest.mark.asyncio
async def test_finance_worker_builds_plan_from_extracted_structured_payload() -> None:
    class StructuredExtractor:
        async def extract(self, **kwargs):
            return FinanceInputExtraction(
                payload={
                    "currency": "GBP",
                    "monthly_income": 1500,
                    "savings_balance": 600,
                    "expenses": [
                        {
                            "category": "rent",
                            "amount": 850,
                            "currency": "GBP",
                            "description": "Student rent",
                            "recurring": True,
                            "billing_period": "monthly",
                        }
                    ],
                },
                confidence=0.9,
            )

    agent_state = AgentScopedState(agent_name="finance")
    result = await FinanceWorker(input_extractor=StructuredExtractor()).run(
        WorkerContext(
            request=ChatRequest(user_id="user_1", message="I earn £1500 monthly and pay £850 rent."),
            agent_state=agent_state,
        )
    )

    assert result.missing_information == []
    assert result.artifacts[0].kind == "finance_plan"
    assert result.artifacts[0].payload["projected_monthly_balance"] == 650
    assert agent_state.metadata["last_finance_input_extraction"]["payload"]["monthly_income"] == 1500


@pytest.mark.asyncio
async def test_finance_worker_requires_currency_for_extracted_amounts() -> None:
    class MissingCurrencyExtractor:
        async def extract(self, **kwargs):
            return FinanceInputExtraction(
                payload={
                    "monthly_income": 1500,
                    "expenses": [{"category": "rent", "amount": 850}],
                },
                confidence=0.8,
            )

    result = await FinanceWorker(input_extractor=MissingCurrencyExtractor()).run(
        WorkerContext(
            request=ChatRequest(user_id="user_1", message="I earn 1500 and rent is 850."),
            agent_state=AgentScopedState(agent_name="finance"),
        )
    )

    assert "finance.currency" in result.missing_information
    assert result.artifacts == []


@pytest.mark.asyncio
async def test_finance_worker_does_not_block_complete_structured_input_when_extractor_degrades() -> None:
    class DegradedExtractor:
        async def extract(self, **kwargs):
            return FinanceInputExtraction(
                missing_information=["finance.monthly_income", "finance.expenses_or_obligations"],
                clarification_questions=["Extractor could not read the request."],
                recoverable_error="LLM unavailable",
            )

    result = await FinanceWorker(input_extractor=DegradedExtractor()).run(
        WorkerContext(
            request=ChatRequest(
                user_id="user_1",
                message="structured budget request",
                agent_inputs={
                    "finance": {
                        "currency": "GBP",
                        "monthly_income": 1500,
                        "expenses": [{"category": "rent", "amount": 850, "currency": "GBP"}],
                    }
                },
            ),
            agent_state=AgentScopedState(agent_name="finance"),
        )
    )

    assert result.missing_information == []
    assert result.artifacts[0].kind == "finance_plan"
