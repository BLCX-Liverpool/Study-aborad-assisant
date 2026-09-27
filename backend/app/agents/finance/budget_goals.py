from datetime import UTC, datetime

from app.schemas.common import PlannedTask
from app.schemas.finance import BudgetGoalOutput, BudgetGoalRequest, BudgetGoalReview


class BudgetGoalPlanner:
    def review(self, request: BudgetGoalRequest) -> BudgetGoalOutput:
        surplus = round(request.monthly_income - request.monthly_expense, 2)
        adjusted_surplus = surplus - sum(goal.recurring_contribution for goal in request.goals)
        reviews = [_review_goal(goal, adjusted_surplus) for goal in request.goals]
        return BudgetGoalOutput(
            currency=request.currency,
            available_monthly_surplus=round(adjusted_surplus, 2),
            goal_reviews=reviews,
            action_items=_action_items(reviews, adjusted_surplus),
            risk_notes=_risk_notes(reviews, adjusted_surplus),
            assumptions=_assumptions(request),
        )


def _review_goal(goal, monthly_surplus: float) -> BudgetGoalReview:
    remaining = round(max(goal.target_amount - goal.current_amount, 0), 2)
    if remaining <= 0:
        return BudgetGoalReview(
            name=goal.name,
            status="reached",
            remaining_amount=0,
            required_monthly_contribution=0,
            months_remaining=0,
            notes=["Goal target has already been reached."],
        )

    months = _months_until(goal.target_date)
    if months is None:
        return BudgetGoalReview(
            name=goal.name,
            status="needs_plan",
            remaining_amount=remaining,
            notes=["Target date is missing; set a date before judging monthly contribution feasibility."],
        )

    required = round(remaining / max(months, 1), 2)
    status = "on_track"
    notes = [f"Needs about {required:.2f} per month for {months} month(s)."]
    if monthly_surplus <= 0:
        status = "at_risk"
        notes.append("Current monthly surplus is not positive.")
    elif required > monthly_surplus:
        status = "at_risk"
        notes.append("Required monthly contribution exceeds available monthly surplus.")
    elif required > monthly_surplus * 0.6:
        status = "at_risk"
        notes.append("Required contribution uses most of the available surplus.")

    return BudgetGoalReview(
        name=goal.name,
        status=status,
        remaining_amount=remaining,
        required_monthly_contribution=required,
        months_remaining=months,
        notes=notes,
    )


def _months_until(target_date) -> int | None:
    if target_date is None:
        return None
    today = datetime.now(tz=UTC).date()
    if target_date <= today:
        return 1
    year_delta = target_date.year - today.year
    month_delta = target_date.month - today.month
    months = year_delta * 12 + month_delta
    if target_date.day > today.day:
        months += 1
    return max(months, 1)


def _action_items(reviews: list[BudgetGoalReview], surplus: float) -> list[PlannedTask]:
    actions = []
    if surplus <= 0:
        actions.append(
            PlannedTask(
                title="Create a short-term spending adjustment plan",
                description="Monthly surplus is not positive, so savings goals need an expense review before contributions.",
                source_type="finance",
                estimated_minutes=45,
                priority="urgent",
            )
        )

    for review in reviews:
        if review.status == "at_risk":
            actions.append(
                PlannedTask(
                    title=f"Rework savings goal: {review.name}",
                    description="Adjust the target date, contribution amount, or discretionary spending before relying on this goal.",
                    source_type="finance",
                    estimated_minutes=30,
                    priority="high",
                )
            )
        elif review.status == "needs_plan":
            actions.append(
                PlannedTask(
                    title=f"Set target date for savings goal: {review.name}",
                    description="Add a target date so the monthly contribution can be estimated.",
                    source_type="finance",
                    estimated_minutes=15,
                    priority="medium",
                )
            )
    return actions


def _risk_notes(reviews: list[BudgetGoalReview], surplus: float) -> list[str]:
    notes = []
    if surplus <= 0:
        notes.append("Available monthly surplus is zero or negative.")
    if any(review.status == "at_risk" for review in reviews):
        notes.append("At least one savings goal may be unrealistic under the current budget.")
    return notes


def _assumptions(request: BudgetGoalRequest) -> list[str]:
    assumptions = [
        "Goal feasibility uses a simple monthly surplus calculation.",
        "Currency conversion and interest/investment return are not included.",
    ]
    if any(goal.recurring_contribution > 0 for goal in request.goals):
        assumptions.append("Recurring goal contributions were subtracted from available monthly surplus.")
    if request.memory_preferences:
        assumptions.append("Finance memory preferences considered: " + "; ".join(request.memory_preferences[:3]))
    if request.savings_balance > 0:
        assumptions.append("Savings balance is recorded as context; goal current_amount remains the source of truth per goal.")
    return assumptions
