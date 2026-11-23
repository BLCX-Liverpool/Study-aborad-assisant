from __future__ import annotations

import json
import re
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
                payload=fallback_social_content_payload(message),
                missing_information=[],
                clarification_questions=[],
                assumptions=["Used deterministic social-content extraction because the LLM extractor was unavailable."],
                confidence=0.55,
                recoverable_error=str(exc),
                raw={"input": prompt_payload},
            )
        return SocialContentInputExtraction(
            payload=normalize_social_content_payload(
                payload.get("payload") if isinstance(payload.get("payload"), dict) else {}
            ),
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


def normalize_social_content_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    platform_aliases = {
        "小红书": "xiaohongshu",
        "红书": "xiaohongshu",
        "rednote": "xiaohongshu",
        "微信朋友圈": "wechat_moments",
        "朋友圈": "wechat_moments",
        "wechat": "wechat_moments",
        "领英": "linkedin",
        "通用": "general",
    }
    tone_aliases = {
        "实用": "practical",
        "温暖": "warm",
        "温馨": "warm",
        "活泼": "playful",
        "俏皮": "playful",
        "反思": "reflective",
        "复盘": "reflective",
        "专业": "professional",
    }
    language_aliases = {
        "中文": "zh",
        "汉语": "zh",
        "英文": "en",
        "英语": "en",
        "双语": "bilingual",
        "中英双语": "bilingual",
    }
    if isinstance(normalized.get("platform"), str):
        platform = normalized["platform"].strip()
        normalized["platform"] = platform_aliases.get(platform.lower(), platform_aliases.get(platform, platform.lower()))
    if isinstance(normalized.get("tone"), str):
        tone = normalized["tone"].strip()
        normalized["tone"] = tone_aliases.get(tone.lower(), tone_aliases.get(tone, tone.lower()))
    if isinstance(normalized.get("language"), str):
        language = normalized["language"].strip()
        normalized["language"] = language_aliases.get(
            language.lower(), language_aliases.get(language, language.lower())
        )
    if normalized.get("platform") not in {"xiaohongshu", "instagram", "wechat_moments", "linkedin", "general"}:
        normalized.pop("platform", None)
    if normalized.get("tone") not in {"practical", "warm", "playful", "reflective", "professional"}:
        normalized.pop("tone", None)
    if normalized.get("language") not in {"zh", "en", "bilingual"}:
        normalized.pop("language", None)

    for field in ("topic", "audience", "notes"):
        value = normalized.get(field)
        if value is not None and not isinstance(value, str):
            normalized.pop(field, None)
    for field in ("key_points", "personal_details"):
        value = normalized.get(field)
        if isinstance(value, dict):
            value = list(value.values())
        if isinstance(value, list):
            normalized[field] = [str(item) for item in value if item is not None and item != ""]
        elif value is not None:
            normalized.pop(field, None)
    for field in ("include_hashtags", "save_memory_candidates", "memory_confirmed"):
        value = normalized.get(field)
        if not isinstance(value, bool):
            normalized.pop(field, None)
    draft_count = normalized.get("draft_count")
    if draft_count is not None:
        try:
            normalized["draft_count"] = max(1, min(int(draft_count), 5))
        except (TypeError, ValueError):
            normalized.pop("draft_count", None)
    return normalized


def fallback_social_content_payload(message: str) -> dict[str, Any]:
    """Extract enough concrete structure to keep the offline fallback useful."""
    lowered = message.lower()
    platform = "general"
    if any(signal in lowered for signal in ("小红书", "xiaohongshu", "rednote")):
        platform = "xiaohongshu"
    elif "instagram" in lowered:
        platform = "instagram"
    elif any(signal in lowered for signal in ("朋友圈", "wechat moments")):
        platform = "wechat_moments"
    elif "linkedin" in lowered:
        platform = "linkedin"

    tone = "warm"
    if any(signal in lowered for signal in ("实用", "干货", "清单", "practical")):
        tone = "practical"
    elif any(signal in lowered for signal in ("活泼", "俏皮", "playful")):
        tone = "playful"
    elif any(signal in lowered for signal in ("复盘", "反思", "reflective")):
        tone = "reflective"
    elif any(signal in lowered for signal in ("专业", "professional")):
        tone = "professional"

    topic = re.split(
        r"[，,。\s]*(?:请你)?(?:请)?帮我(?:写|整理|生成)|[，,。\s]*麻烦(?:你)?帮我(?:写|整理|生成)",
        message,
        maxsplit=1,
    )[0].strip(" ，,。")
    if not topic:
        topic = message.strip()

    key_points: list[str] = []
    destination = re.search(r"(?:去|前往)([^，。,.]{1,20}?)(?:玩(?:了一圈)?|旅行|旅游|逛)", topic)
    if destination:
        key_points.append(f"去了{destination.group(1).strip()}")
    visited = re.search(r"(?:参观|逛|打卡)(?:了)?([^，。,.]+)", topic)
    if visited:
        for place in re.split(r"和|、|以及|及", visited.group(1)):
            cleaned = place.strip(" ，,。")
            if cleaned:
                key_points.append(f"参观了{cleaned}")
    key_points = list(dict.fromkeys(key_points))

    return {
        "topic": topic,
        "platform": platform,
        "tone": tone,
        "key_points": key_points,
        "language": "zh" if re.search(r"[\u4e00-\u9fff]", message) else "en",
    }
