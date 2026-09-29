from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM, get_stage_llm_client


class EmailInputExtraction(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw: dict[str, Any] = Field(default_factory=dict)
    recoverable_error: str | None = None


class EmailInputExtractor:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm or get_stage_llm_client("email")

    async def extract(self, *, message: str, existing_payload: dict[str, Any] | None = None) -> EmailInputExtraction:
        prompt_payload = {"message": message, "existing_payload": existing_payload or {}}
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "Extract structured email draft inputs. Return JSON with payload, missing_information, "
                                "clarification_questions, confidence. payload may include purpose, recipient_hint, language, "
                                "tone_hint, context with recipient_name, sender_name, course_code, assignment_title, deadline, "
                                "additional_context, evidence_summary. Do not invent names, deadlines, or evidence."
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
            return EmailInputExtraction(
                payload={},
                recoverable_error=str(exc),
                raw={"input": prompt_payload},
            )
        return EmailInputExtraction(
            payload=payload.get("payload") if isinstance(payload.get("payload"), dict) else {},
            missing_information=_string_list(payload.get("missing_information")),
            clarification_questions=_string_list(payload.get("clarification_questions")),
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
