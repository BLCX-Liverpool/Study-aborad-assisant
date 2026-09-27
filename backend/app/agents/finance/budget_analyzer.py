from collections import defaultdict

from app.schemas.common import PlannedTask
from app.schemas.finance import (
    BudgetCategorySummary,
    ExpenseItem,
    FinancePlanOutput,
    FinancePlanRequest,
)


class StudentBudgetAnalyzer:
    def analyze(self, request: FinancePlanRequest, parsed_expenses: list[ExpenseItem]) -> FinancePlanOutput:
        expenses = [*request.expenses, *parsed_expenses]
        category_totals = _category_totals(expenses)
        total_expense = sum(category_totals.values())
        projected_balance = request.monthly_income - total_expense
        emergency_target = max(total_expense * 3, 500.0 if request.currency.upper() == "GBP" else total_expense)

        return FinancePlanOutput(
            currency=request.currency,
            total_monthly_income=request.monthly_income,
            total_monthly_expense=round(total_expense, 2),
            projected_monthly_balance=round(projected_balance, 2),
            emergency_fund_target=round(emergency_target, 2),
            category_summaries=_summaries(category_totals, request.planning_months),
            action_items=_action_items(request, projected_balance, emergency_target, category_totals),
            risk_notes=_risk_notes(request, projected_balance, emergency_target, category_totals),
            assumptions=_assumptions(request, parsed_expenses),
        )


def _category_totals(expenses: list[ExpenseItem]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for expense in expenses:
        if expense.category == "income":
            continue
        multiplier = 1.0 if expense.recurring else 1.0
        totals[expense.category] += expense.amount * multiplier
    return dict(totals)


def _summaries(totals: dict[str, float], planning_months: int) -> list[BudgetCategorySummary]:
    summaries = []
    for category, total in sorted(totals.items()):
        summaries.append(
            BudgetCategorySummary(
                category=category,  # type: ignore[arg-type]
                total_amount=round(total, 2),
                monthly_amount=round(total / planning_months, 2),
                notes=None,
            )
        )
    return summaries


def _action_items(
    request: FinancePlanRequest,
    projected_balance: float,
    emergency_target: float,
    totals: dict[str, float],
) -> list[PlannedTask]:
    actions = [
        PlannedTask(
            title="Review fixed student costs",
            description="Check rent, tuition, utilities, phone, insurance, and transport before flexible spending.",
            source_type="finance",
            estimated_minutes=45,
            priority="high",
        )
    ]

    if projected_balance < 0:
        actions.append(
            PlannedTask(
                title="Reduce or defer non-essential spending",
                description="Identify travel, subscriptions, and flexible purchases that can be reduced this month.",
                source_type="finance",
                estimated_minutes=60,
                priority="urgent",
            )
        )

    if request.savings_balance < emergency_target:
        actions.append(
            PlannedTask(
                title="Build emergency fund buffer",
                description=f"Target at least {request.currency} {emergency_target:.2f} before discretionary travel or large purchases.",
                source_type="finance",
                estimated_minutes=30,
                priority="medium",
            )
        )

    if totals.get("deposit", 0) > 0:
        actions.append(
            PlannedTask(
                title="Track deposit documents",
                description="Save tenancy agreement, deposit scheme details, payment receipt, and move-in inventory.",
                source_type="finance",
                estimated_minutes=30,
                priority="high",
            )
        )

    return actions


def _risk_notes(
    request: FinancePlanRequest,
    projected_balance: float,
    emergency_target: float,
    totals: dict[str, float],
) -> list[str]:
    notes = []
    if projected_balance < 0:
        notes.append("Projected monthly balance is negative; create a short-term spending reduction plan.")
    if request.savings_balance < emergency_target:
        notes.append("Savings are below the suggested emergency buffer for student living costs.")
    if totals.get("rent", 0) > request.monthly_income * 0.5 and request.monthly_income > 0:
        notes.append("Rent appears to exceed 50% of monthly income; monitor affordability carefully.")
    if totals.get("tuition", 0) > 0:
        notes.append("Tuition deadlines should be checked against official university billing notices.")
    return notes


def _assumptions(request: FinancePlanRequest, parsed_expenses: list[ExpenseItem]) -> list[str]:
    assumptions = [
        "All expense amounts are treated as monthly planning values unless the user marks future one-off costs separately.",
        "Currency conversion is not performed in the first version.",
    ]
    if request.expense_csv:
        assumptions.append(f"Parsed {len(parsed_expenses)} expense rows from CSV input.")
    if request.notes:
        assumptions.append("User notes were considered as budgeting context, not as verified financial records.")
    return assumptions
