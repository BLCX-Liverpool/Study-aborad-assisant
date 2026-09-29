from collections import defaultdict

from app.agents.finance.exchange_rates import CurrencyConverter, ExchangeRateProvider
from app.agents.finance.obligations import build_planner_items, build_upcoming_obligations
from app.schemas.common import PlannedTask
from app.schemas.finance import (
    BudgetCategorySummary,
    ExpenseItem,
    FinancePlanOutput,
    FinancePlanRequest,
)


class StudentBudgetAnalyzer:
    def __init__(self, exchange_rate_provider: ExchangeRateProvider | None = None) -> None:
        self.exchange_rate_provider = exchange_rate_provider

    def analyze(self, request: FinancePlanRequest, parsed_expenses: list[ExpenseItem]) -> FinancePlanOutput:
        target_currency = (request.target_currency or request.currency).upper()
        converter = CurrencyConverter(self.exchange_rate_provider)
        expenses = [*request.expenses, *parsed_expenses]
        obligations = build_upcoming_obligations(request)
        category_totals = _category_totals(expenses, converter, target_currency)
        travel_total = _travel_budget_total(request, converter, target_currency)
        if travel_total:
            category_totals["travel"] = category_totals.get("travel", 0.0) + travel_total
        total_expense = sum(category_totals.values())
        income_in_target = converter.convert(
            request.monthly_income,
            base_currency=request.currency,
            quote_currency=target_currency,
        )
        if income_in_target is None:
            income_in_target = request.monthly_income if request.currency.upper() == target_currency else 0.0
        projected_balance = income_in_target - total_expense
        emergency_target = max(total_expense * 3, 500.0 if request.currency.upper() == "GBP" else total_expense)

        return FinancePlanOutput(
            currency=request.currency,
            target_currency=target_currency,
            total_monthly_income=request.monthly_income,
            total_monthly_expense=round(total_expense, 2),
            total_monthly_expense_in_target_currency=round(total_expense, 2),
            projected_monthly_balance=round(projected_balance, 2),
            projected_monthly_balance_in_target_currency=round(projected_balance, 2),
            emergency_fund_target=round(emergency_target, 2),
            category_summaries=_summaries(category_totals, request.planning_months),
            exchange_rates=converter.quotes(),
            upcoming_obligations=obligations,
            planner_items=build_planner_items(obligations),
            action_items=_action_items(request, projected_balance, emergency_target, category_totals),
            risk_notes=_risk_notes(request, projected_balance, emergency_target, category_totals),
            assumptions=_assumptions(request, parsed_expenses, converter),
        )


def _category_totals(
    expenses: list[ExpenseItem],
    converter: CurrencyConverter,
    target_currency: str,
) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    for expense in expenses:
        if expense.category == "income":
            continue
        amount = converter.convert(
            expense.amount,
            base_currency=expense.currency,
            quote_currency=target_currency,
        )
        if amount is None:
            amount = expense.amount if expense.currency.upper() == target_currency else 0.0
        multiplier = 1.0 if expense.recurring else 1.0
        totals[expense.category] += amount * multiplier
    return dict(totals)


def _travel_budget_total(
    request: FinancePlanRequest,
    converter: CurrencyConverter,
    target_currency: str,
) -> float:
    total = 0.0
    for item in request.travel_budget_items:
        if item.estimated_amount is None:
            continue
        converted = converter.convert(
            item.estimated_amount,
            base_currency=item.currency,
            quote_currency=target_currency,
        )
        if converted is not None:
            total += converted
    return round(total, 2)


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


def _assumptions(
    request: FinancePlanRequest,
    parsed_expenses: list[ExpenseItem],
    converter: CurrencyConverter,
) -> list[str]:
    assumptions = [
        "All expense amounts are treated as monthly planning values unless the user marks future one-off costs separately.",
        "Currency conversion is an estimate unless the exchange rate source is provider_verified.",
    ]
    if request.expense_csv:
        assumptions.append(f"Parsed {len(parsed_expenses)} expense rows from CSV input.")
    if request.target_currency and request.target_currency.upper() != request.currency.upper():
        assumptions.append(f"Budget was normalized to target currency {request.target_currency.upper()}.")
    if request.travel_budget_items:
        assumptions.append("Travel budget handoff items were included in the travel spending category.")
    if request.obligations or any(expense.recurring or expense.installment_count > 1 for expense in request.expenses):
        assumptions.append("Upcoming obligations were generated from bills, due dates, recurring expenses, and installments.")
    unavailable = [quote for quote in converter.quotes() if quote.rate is None]
    if unavailable:
        assumptions.append("Some currency conversions were unavailable and excluded from converted totals.")
    if request.notes:
        assumptions.append("User notes were considered as budgeting context, not as verified financial records.")
    if request.memory_preferences:
        assumptions.append("Finance memory preferences considered: " + "; ".join(request.memory_preferences[:3]))
    return assumptions
