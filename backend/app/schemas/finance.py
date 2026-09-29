from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.action import ActionItem
from app.schemas.common import PlannedTask
from app.schemas.memory import MemoryCandidatePersistResponse

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
BillingPeriod = Literal["one_time", "weekly", "monthly", "quarterly", "termly", "annual"]
FinanceSourceType = Literal["user_provided", "parsed_bill", "travel_handoff", "generated_schedule"]
FinanceDataSource = Literal["provider_verified", "static_estimate", "user_provided", "unavailable"]


class ExpenseItem(BaseModel):
    category: FinanceCategory = "other"
    amount: float = Field(ge=0)
    currency: str = "GBP"
    description: str | None = None
    paid_at: date | None = None
    due_date: date | None = None
    recurring: bool = False
    billing_period: BillingPeriod = "one_time"
    installment_count: int = Field(default=1, ge=1, le=24)


class FinancePlanRequest(BaseModel):
    user_id: str
    currency: str = "GBP"
    monthly_income: float = Field(default=0, ge=0)
    savings_balance: float = Field(default=0, ge=0)
    expenses: list[ExpenseItem] = Field(default_factory=list)
    expense_csv: str | None = None
    planning_months: int = Field(default=1, ge=1, le=12)
    notes: str | None = None
    memory_preferences: list[str] = Field(default_factory=list)
    target_currency: str | None = None
    lookahead_months: int = Field(default=3, ge=1, le=12)
    obligations: list["FinanceObligation"] = Field(default_factory=list)
    travel_budget_items: list["FinanceTravelBudgetInput"] = Field(default_factory=list)
    save_memory_candidates: bool = False
    memory_confirmed: bool = False


class BudgetCategorySummary(BaseModel):
    category: FinanceCategory
    total_amount: float
    monthly_amount: float
    notes: str | None = None


class FinancePlanOutput(BaseModel):
    currency: str
    target_currency: str | None = None
    total_monthly_income: float
    total_monthly_expense: float
    total_monthly_expense_in_target_currency: float | None = None
    projected_monthly_balance: float
    projected_monthly_balance_in_target_currency: float | None = None
    emergency_fund_target: float
    category_summaries: list[BudgetCategorySummary] = Field(default_factory=list)
    exchange_rates: list["ExchangeRateQuote"] = Field(default_factory=list)
    upcoming_obligations: list["FinanceObligation"] = Field(default_factory=list)
    planner_items: list["ActionItem"] = Field(default_factory=list)
    action_items: list[PlannedTask] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    memory_candidates: list["FinanceMemoryCandidate"] = Field(default_factory=list)
    memory_confirmation: MemoryCandidatePersistResponse | None = None
    disclaimer: str = "This is budgeting support for student life and is not financial, tax, or legal advice."


class FinanceMemoryCandidate(BaseModel):
    namespace: str = "finance"
    content: str
    requires_confirmation: bool = True
    confirmed: bool = False
    source_type: str = "finance_agent"
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)


class ExchangeRateQuote(BaseModel):
    base_currency: str
    quote_currency: str
    rate: float | None = Field(default=None, ge=0)
    source: FinanceDataSource = "unavailable"
    provider_name: str | None = None
    as_of: datetime | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    recoverable_error: str | None = None


class FinanceTravelBudgetInput(BaseModel):
    category: str
    estimated_amount: float | None = Field(default=None, ge=0)
    currency: str = "GBP"
    notes: str | None = None
    source: FinanceDataSource = "user_provided"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    trip_name: str | None = None


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
    billing_period: BillingPeriod = "one_time"
    source_type: FinanceSourceType = "parsed_bill"
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
    planner_items: list["ActionItem"] = Field(default_factory=list)
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
    save_memory_candidates: bool = False
    memory_confirmed: bool = False


class BudgetGoalOutput(BaseModel):
    currency: str
    available_monthly_surplus: float
    goal_reviews: list[BudgetGoalReview] = Field(default_factory=list)
    action_items: list[PlannedTask] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    memory_candidates: list[FinanceMemoryCandidate] = Field(default_factory=list)
    memory_confirmation: MemoryCandidatePersistResponse | None = None
    disclaimer: str = "This is budgeting support for student life and is not financial, tax, or legal advice."
