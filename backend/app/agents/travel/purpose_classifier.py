from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM, get_stage_llm_client
from app.schemas.travel import TravelPurpose


ALLOWED_TRAVEL_PURPOSES: tuple[TravelPurpose, ...] = (
    "airport_arrival",
    "city_trip",
    "academic_trip",
    "visa_or_immigration",
    "home_visit",
    "other",
)


class TravelPurposeClassification(BaseModel):
    purpose: TravelPurpose = "other"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""
    source: str = "llm"
    raw: dict[str, Any] = Field(default_factory=dict)
    recoverable_error: str | None = None


class TravelPurposeClassifier:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm or get_stage_llm_client("travel")

    async def classify(
        self,
        *,
        message: str,
        origin: str,
        destination: str,
        notes: str | None = None,
        constraints: list[str] | None = None,
    ) -> TravelPurposeClassification:
        prompt_payload = {
            "message": message,
            "origin": origin,
            "destination": destination,
            "notes": notes,
            "constraints": constraints or [],
            "allowed_purposes": list(ALLOWED_TRAVEL_PURPOSES),
        }
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "You classify the user's travel purpose for a study-abroad assistant. "
                                "Return a JSON object with purpose, confidence, and rationale. "
                                "Allowed purpose values are: airport_arrival, city_trip, academic_trip, "
                                "visa_or_immigration, home_visit, other. "
                                "Choose airport_arrival only for airport pickup/arrival/departure logistics; "
                                "academic_trip for university/course/research/conference/campus academic visits; "
                                "visa_or_immigration for visa, BRP, embassy, immigration, appointment or document trips; "
                                "home_visit for family/home visits; city_trip for sightseeing, city orientation or errands; "
                                "other when the evidence is insufficient. Do not invent facts."
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
            return TravelPurposeClassification(
                purpose="other",
                confidence=0.0,
                rationale="LLM purpose classification was unavailable.",
                recoverable_error=str(exc),
                raw={"input": prompt_payload},
            )

        purpose = payload.get("purpose", "other")
        if purpose not in ALLOWED_TRAVEL_PURPOSES:
            purpose = "other"
        return TravelPurposeClassification(
            purpose=purpose,
            confidence=_coerce_confidence(payload.get("confidence")),
            rationale=str(payload.get("rationale") or ""),
            raw=payload,
        )


def _coerce_confidence(value: Any) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return 0.0
