from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM, get_stage_llm_client


class FitnessInputExtraction(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw: dict[str, Any] = Field(default_factory=dict)
    recoverable_error: str | None = None


class FitnessInputExtractor:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm or get_stage_llm_client("fitness")

    async def extract(
        self,
        *,
        message: str,
        existing_payload: dict[str, Any] | None = None,
        memory_preferences: list[str] | None = None,
    ) -> FitnessInputExtraction:
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
                                "Extract structured fitness planning inputs. Return JSON with payload, missing_information, "
                                "clarification_questions, assumptions, confidence. Do not invent goal, fitness_level, available slots, "
                                "equipment, injuries, constraints, intensity, or plan length. payload may include goal, fitness_level, "
                                "available_slots, equipment, constraints, preferred_intensity, plan_weeks, notes. "
                                "available_slots use day_of_week mon/tue/wed/thu/fri/sat/sun, start_time HH:MM, duration_minutes. "
                                "Allowed goals: general_fitness, strength, cardio, mobility, weight_management, stress_relief. "
                                "Allowed fitness_level: beginner, intermediate, advanced. Allowed preferred_intensity: low, moderate, high. "
                                "Missing keys should be fitness.goal, fitness.available_slots, fitness.equipment."
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
            return FitnessInputExtraction(
                missing_information=["fitness.goal", "fitness.available_slots", "fitness.equipment"],
                clarification_questions=["请提供健身目标、每周可训练时间，以及可用器械或是否徒手训练。"],
                recoverable_error=str(exc),
                raw={"input": prompt_payload},
            )
        return FitnessInputExtraction(
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
