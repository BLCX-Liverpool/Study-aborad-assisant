from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM, get_stage_llm_client


class SocialContentInputExtraction(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    raw: dict[str, Any] = Field(default_factory=dict)
    recoverable_error: str | None = None


class SocialContentInputExtractor:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm or get_stage_llm_client("social")

    async def extract(
        self,
        *,
        message: str,
        existing_payload: dict[str, Any] | None = None,
        memory_preferences: list[str] | None = None,
    ) -> SocialContentInputExtraction:
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
                                "Extract structured social content drafting inputs for a study-abroad assistant. "
                                "Return JSON with payload, missing_information, clarification_questions, assumptions, confidence. "
                                "payload may include topic, platform, tone, audience, key_points, personal_details, "
                                "include_hashtags, draft_count, language, notes, save_memory_candidates, memory_confirmed. "
                                "Allowed platform values: xiaohongshu, instagram, wechat_moments, linkedin, general. "
                                "Allowed tone values: practical, warm, playful, reflective, professional. "
                                "Allowed language values: zh, en, bilingual. "
                                "Only include values explicitly stated or strongly implied. Do not invent personal details. "
                                "If topic is unclear, put social_content.topic in missing_information, but do not block generation; "
                                "the caller may use the original message as topic and schema defaults for optional fields."
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
            return SocialContentInputExtraction(
                payload={},
                missing_information=[],
                clarification_questions=[],
                recoverable_error=str(exc),
                raw={"input": prompt_payload},
            )
        return SocialContentInputExtraction(
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
