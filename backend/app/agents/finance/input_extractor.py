from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM, get_stage_llm_client


class FinanceInputExtraction(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)
    recoverable_error: str | None = None


class FinanceInputExtractor:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm or get_stage_llm_client("finance")

    async def extract(
        self,
        *,
        message: str,
        existing_payload: dict[str, Any] | None = None,
        memory_preferences: list[str] | None = None,
    ) -> FinanceInputExtraction:
        prompt_payload = {
            "message": message,
            "existing_payload": existing_payload or {},
            "memory_preferences": memory_preferences or [],
        }
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "You extract structured finance planning inputs for a study-abroad assistant. "
                                "Return JSON with payload, missing_information, clarification_questions, confidence, rationale. "
                                "Only include fields that are explicitly stated or strongly implied by the user or existing_payload. "
                                "Do not invent defaults for income, savings, expenses, dates, currencies, or billing periods. "
                                "payload may include currency, monthly_income, savings_balance, expenses, obligations, "
                                "target_currency, planning_months, lookahead_months, notes. "
                                "expenses items use category, amount, currency, description, recurring, billing_period, due_date. "
                                "obligations items use bill_type, category, amount, currency, due_date, description, recurring, billing_period. "
                                "Allowed categories: rent, deposit, tuition, utilities, groceries, transport, phone, insurance, "
                                "travel, income, emergency_fund, other. Allowed billing_period: one_time, weekly, monthly, "
                                "quarterly, termly, annual. Missing keys should be named like finance.monthly_income or "
                                "finance.expenses_or_obligations."
                            ),
                        ),
                        ChatMessage(role="user", content=json.dumps(prompt_payload, ensure_ascii=False)),
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
            )
            payload = json.loads(response.content)
        except Exception as exc:
            return FinanceInputExtraction(
                missing_information=["finance.monthly_income", "finance.expenses_or_obligations"],
                clarification_questions=[
                    "请提供每月收入或可用储蓄，以及至少一项支出、账单或付款义务。"
                ],
                rationale="LLM finance input extraction was unavailable.",
                recoverable_error=str(exc),
                raw={"input": prompt_payload},
            )

        extracted_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
        return FinanceInputExtraction(
            payload=extracted_payload,
            missing_information=_string_list(payload.get("missing_information")),
            clarification_questions=_string_list(payload.get("clarification_questions")),
            confidence=_coerce_confidence(payload.get("confidence")),
            rationale=str(payload.get("rationale") or ""),
            raw=payload,
        )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in {None, ""}]


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0
