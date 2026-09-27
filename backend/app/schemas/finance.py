from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import PlannedTask

FinanceCategory = Literal[
    "rent",
    "deposit",
    "tuition",
    "utilities",
    "groceries",
    "transport",
    "phone",
    "insurance",
    "travel",
    "income",
    "emergency_fund",
    "other",
]


class ExpenseItem(BaseModel):
    category: FinanceCategory = "other"
    amount: float = Field(ge=0)
    currency: str = "GBP"
    description: str | None = None
    paid_at: date | None = None
    recurring: bool = False


class FinancePlanRequest(BaseModel):
    user_id: str
    currency: str = "GBP"
    monthly_income: float = Field(default=0, ge=0)
    savings_balance: float = Field(default=0, ge=0)
    expenses: list[ExpenseItem] = Field(default_factory=list)
    expense_csv: str | None = None
    planning_months: int = Field(default=1, ge=1, le=12)
    notes: str | None = None


class BudgetCategorySummary(BaseModel):
    category: FinanceCategory
    total_amount: float
    monthly_amount: float
    notes: str | None = None


class FinancePlanOutput(BaseModel):
    currency: str
    total_monthly_income: float
    total_monthly_expense: float
    projected_monthly_balance: float
    emergency_fund_target: float
    category_summaries: list[BudgetCategorySummary] = Field(default_factory=list)
    action_items: list[PlannedTask] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    disclaimer: str = "This is budgeting support for student life and is not financial, tax, or legal advice."


BillType = Literal["tuition", "rent", "deposit", "utilities", "phone", "insurance", "travel", "other"]
BudgetGoalStatus = Literal["reached", "on_track", "at_risk", "needs_plan"]


class FinanceObligation(BaseModel):
    bill_type: BillType = "other"
    category: FinanceCategory = "other"
    amount: float | None = Field(default=None, ge=0)
    currency: str = "GBP"
    due_date: date | None = None
    description: str
    source_name: str | None = None
    recurring: bool = False
    evidence_text: str | None = None


class FinanceBillParseRequest(BaseModel):
    user_id: str
    raw_text: str = ""
    source_path: Path | None = None
    default_currency: str = "GBP"
    source_name: str | None = None


class FinanceBillParseOutput(BaseModel):
    obligations: list[FinanceObligation] = Field(default_factory=list)
    action_items: list[PlannedTask] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    disclaimer: str = "This is document parsing support and is not financial, tax, or legal advice."


class BudgetGoalInput(BaseModel):
    name: str
    target_amount: float = Field(ge=0)
    current_amount: float = Field(default=0, ge=0)
    target_date: date | None = None
    category: FinanceCategory = "emergency_fund"
    priority: Literal["low", "medium", "high"] = "medium"
    recurring_contribution: float = Field(default=0, ge=0)


class BudgetGoalReview(BaseModel):
    name: str
    status: BudgetGoalStatus
    remaining_amount: float
    required_monthly_contribution: float | None = None
    months_remaining: int | None = None
    notes: list[str] = Field(default_factory=list)


class BudgetGoalRequest(BaseModel):
    user_id: str
    currency: str = "GBP"
    monthly_income: float = Field(default=0, ge=0)
    monthly_expense: float = Field(default=0, ge=0)
    savings_balance: float = Field(default=0, ge=0)
    goals: list[BudgetGoalInput] = Field(default_factory=list)
    memory_preferences: list[str] = Field(default_factory=list)


class BudgetGoalOutput(BaseModel):
    currency: str
    available_monthly_surplus: float
    goal_reviews: list[BudgetGoalReview] = Field(default_factory=list)
    action_items: list[PlannedTask] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    disclaimer: str = "This is budgeting support for student life and is not financial, tax, or legal advice."
