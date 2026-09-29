from datetime import UTC, date, datetime
from calendar import monthrange

from app.schemas.action import ActionItem
from app.schemas.finance import ExpenseItem, FinanceObligation, FinancePlanRequest


def build_upcoming_obligations(request: FinancePlanRequest) -> list[FinanceObligation]:
    obligations = [*request.obligations]
    for expense in request.expenses:
        obligations.extend(_obligations_from_expense(expense, request))
    for travel_item in request.travel_budget_items:
        if travel_item.estimated_amount is None:
            continue
        obligations.append(
            FinanceObligation(
                bill_type="travel",
                category="travel",
                amount=travel_item.estimated_amount,
                currency=travel_item.currency,
                description=_travel_description(travel_item.category, travel_item.trip_name),
                source_name=travel_item.trip_name,
                recurring=False,
                billing_period="one_time",
                source_type="travel_handoff",
                evidence_text=travel_item.notes,
            )
        )
    return sorted(obligations, key=lambda item: item.due_date or date.max)


def build_planner_items(obligations: list[FinanceObligation]) -> list[ActionItem]:
    items = []
    for obligation in obligations:
        if obligation.due_date is None:
            continue
        deadline = datetime.combine(obligation.due_date, datetime.min.time(), tzinfo=UTC)
        amount = f"{obligation.currency} {obligation.amount:.2f}" if obligation.amount is not None else "amount TBD"
        items.append(
            ActionItem(
                title=f"Review {amount} {obligation.bill_type} payment",
                action_type="bill_due",
                source_type=obligation.source_type,
                source_id=obligation.source_name,
                description="Verify recipient, official payment channel, and available balance before paying.",
                deadline=deadline,
                priority=_priority_for_obligation(obligation),
                evidence=[],
                metadata={
                    "category": obligation.category,
                    "currency": obligation.currency,
                    "amount": obligation.amount,
                    "recurring": obligation.recurring,
                    "billing_period": obligation.billing_period,
                },
            )
        )
    return items


def _obligations_from_expense(expense: ExpenseItem, request: FinancePlanRequest) -> list[FinanceObligation]:
    if not expense.recurring and expense.installment_count <= 1:
        if expense.due_date is None:
            return []
        return [_expense_obligation(expense, expense.due_date, source_type="user_provided")]

    start = expense.due_date or expense.paid_at
    if start is None:
        return []
    count = _occurrence_count(expense, request.lookahead_months)
    return [
        _expense_obligation(
            expense,
            _advance_date(start, expense.billing_period, offset),
            source_type="generated_schedule",
        )
        for offset in range(count)
    ]


def _expense_obligation(
    expense: ExpenseItem,
    due_date: date,
    *,
    source_type: str,
) -> FinanceObligation:
    return FinanceObligation(
        bill_type=_bill_type_for_category(expense.category),
        category=expense.category,
        amount=expense.amount,
        currency=expense.currency,
        due_date=due_date,
        description=expense.description or f"{expense.category} payment",
        source_name=expense.description,
        recurring=expense.recurring,
        billing_period=expense.billing_period,
        source_type=source_type,  # type: ignore[arg-type]
        evidence_text=expense.description,
    )


def _occurrence_count(expense: ExpenseItem, lookahead_months: int) -> int:
    if expense.installment_count > 1:
        return expense.installment_count
    if expense.billing_period == "weekly":
        return min(lookahead_months * 4, 52)
    if expense.billing_period == "monthly":
        return lookahead_months
    if expense.billing_period == "quarterly":
        return max(1, (lookahead_months + 2) // 3)
    if expense.billing_period == "termly":
        return max(1, (lookahead_months + 3) // 4)
    if expense.billing_period == "annual":
        return 1
    return 1


def _advance_date(start: date, period: str, offset: int) -> date:
    if offset == 0:
        return start
    if period == "weekly":
        from datetime import timedelta

        return start + timedelta(weeks=offset)
    if period == "monthly":
        return _add_months(start, offset)
    if period == "quarterly":
        return _add_months(start, offset * 3)
    if period == "termly":
        return _add_months(start, offset * 4)
    if period == "annual":
        return _add_months(start, offset * 12)
    return start


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def _bill_type_for_category(category: str) -> str:
    if category in {"rent", "deposit", "tuition", "utilities", "phone", "insurance", "travel"}:
        return category
    return "other"


def _priority_for_obligation(obligation: FinanceObligation) -> str:
    if obligation.bill_type in {"tuition", "rent", "deposit"}:
        return "high"
    if obligation.bill_type in {"utilities", "insurance"}:
        return "medium"
    return "medium"


def _travel_description(category: str, trip_name: str | None) -> str:
    prefix = f"{trip_name}: " if trip_name else ""
    return f"{prefix}Travel budget item - {category}"
