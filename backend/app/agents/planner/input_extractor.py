from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM, get_stage_llm_client


class PlanningInputExtraction(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    planning_horizon_days: int | None = None
    existing_blocks: list[dict[str, Any]] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw: dict[str, Any] = Field(default_factory=dict)
    recoverable_error: str | None = None


class PlanningInputExtractor:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm or get_stage_llm_client("planner")

    async def extract(
        self,
        *,
        message: str,
        existing_payload: dict[str, Any] | None = None,
        memory_preferences: list[str] | None = None,
    ) -> PlanningInputExtraction:
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
                                "Extract planning items from a natural language request. Return JSON with items, planning_horizon_days, "
                                "existing_blocks, missing_information, clarification_questions, assumptions, confidence. "
                                "items must fit ActionItem fields: title, action_type, source_type, description, deadline, start_time, end_time, "
                                "location, priority, metadata. Do not invent deadlines or fixed times; if you assume duration or horizon, put it in assumptions. "
                                "Allowed action_type values: assignment_deadline, bill_due, tenancy_action, travel_event, appointment, email_follow_up, generic_task. "
                                "Use source_type='user_request' for user-entered tasks. Missing keys should be planner.item_scope or planner.deadline_or_horizon."
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
            return PlanningInputExtraction(
                missing_information=["planner.item_scope", "planner.deadline_or_horizon"],
                clarification_questions=["请说明要安排哪些任务，以及希望安排到哪一天或多长时间范围内完成。"],
                recoverable_error=str(exc),
                raw={"input": prompt_payload},
            )
        return PlanningInputExtraction(
            items=payload.get("items") if isinstance(payload.get("items"), list) else [],
            planning_horizon_days=_coerce_int(payload.get("planning_horizon_days")),
            existing_blocks=payload.get("existing_blocks") if isinstance(payload.get("existing_blocks"), list) else [],
            missing_information=_string_list(payload.get("missing_information")),
            clarification_questions=_string_list(payload.get("clarification_questions")),
            assumptions=_string_list(payload.get("assumptions")),
            confidence=_coerce_confidence(payload.get("confidence")),
            raw=payload,
        )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in {None, ""}]


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0
