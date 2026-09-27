from app.agents.finance.csv_parser import ExpenseCsvParser
from app.agents.finance.service import FinanceAgentService
from app.schemas.finance import ExpenseItem, FinancePlanRequest


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
