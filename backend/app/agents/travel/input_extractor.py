from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM, get_stage_llm_client


class TravelInputExtraction(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    assumptions: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
    recoverable_error: str | None = None


class TravelInputExtractor:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm or get_stage_llm_client("travel")

    async def extract(
        self,
        *,
        message: str,
        existing_payload: dict[str, Any] | None = None,
        memory_preferences: list[str] | None = None,
    ) -> TravelInputExtraction:
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
                                "Extract structured travel planning inputs for a study-abroad assistant. "
                                "Return JSON with payload, missing_information, clarification_questions, assumptions, confidence. "
                                "Only include fields explicitly stated or strongly implied; do not invent origin, destination, dates, budget, currency, or accommodation. "
                                "payload may include origin, destination, depart_at, return_at, purpose, budget_amount, currency, "
                                "accommodation_needed, notes, constraints. Datetimes must be ISO-8601 with timezone when possible. "
                                "Allowed purpose values: airport_arrival, city_trip, academic_trip, visa_or_immigration, home_visit, other. "
                                "Missing keys should use names like travel.origin, travel.destination, travel.currency."
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
            return TravelInputExtraction(
                missing_information=["travel.origin", "travel.destination"],
                clarification_questions=["请提供出发地和目的地。"],
                recoverable_error=str(exc),
                raw={"input": prompt_payload},
            )
        return TravelInputExtraction(
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
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


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0
