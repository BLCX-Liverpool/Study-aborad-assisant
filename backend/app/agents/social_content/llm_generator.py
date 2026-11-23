import json
import re
from typing import Any

from pydantic import ValidationError

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.social_content import (
    PlatformStandard,
    SocialContentDraft,
    SocialContentRequest,
    SocialPlatform,
)
from app.skills import SkillLoader


class LlmSocialCopyGenerator:
    def __init__(self, llm: OpenAICompatibleLLM | None = None, skill_loader: SkillLoader | None = None) -> None:
        self.llm = llm
        self.skill_loader = skill_loader or SkillLoader()
        self.last_error: str | None = None

    async def generate(
        self,
        request: SocialContentRequest,
        platform: SocialPlatform,
        standard: PlatformStandard,
    ) -> list[SocialContentDraft]:
        if self.llm is None:
            self.last_error = "LLM client is not configured."
            return []
        self.last_error = None
        skill = self.skill_loader.load("social-content-writing", include_references=True)
        system_prompt = _system_prompt(skill.as_prompt_context() if skill else None)
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(
                role="user",
                content=json.dumps(
                    {
                        "request": request.model_dump(mode="json"),
                        "platform": platform,
                        "platform_standard": standard.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                ),
            ),
        ]
        best_drafts: list[SocialContentDraft] = []
        last_validation_errors: list[str] = []
        for attempt in range(2):
            try:
                response = await self.llm.chat(
                    ChatRequest(
                        messages=messages,
                        temperature=0.4 if attempt == 0 else 0.0,
                        response_format={"type": "json_object"},
                    )
                )
            except Exception as exc:
                if best_drafts:
                    return best_drafts[: request.draft_count]
                self.last_error = f"{type(exc).__name__}: {str(exc)[:300]}"
                return []

            try:
                payload = json.loads(response.content)
            except (TypeError, json.JSONDecodeError) as exc:
                drafts: list[SocialContentDraft] = []
                errors = [f"Response is not valid JSON: {exc}"]
            else:
                drafts, errors = _validate_drafts(payload, platform, request.draft_count)

            if drafts and not errors:
                return drafts
            if len(drafts) > len(best_drafts):
                best_drafts = drafts
            last_validation_errors = errors
            if attempt == 0:
                messages = [
                    *messages,
                    ChatMessage(role="assistant", content=response.content[:8_000]),
                    ChatMessage(role="user", content=_repair_prompt(errors, request.draft_count, platform)),
                ]

        if best_drafts:
            return best_drafts[: request.draft_count]
        self.last_error = "ValidationError: " + "; ".join(last_validation_errors)[:500]
        return []


def _system_prompt(skill_context: str | None) -> str:
    base = (
        "你是留学生活场景的社交平台文案助手。"
        "优先遵循下方 Skill 文档与 references，但必须保持输出 schema。"
        "只返回一个 JSON 对象，不要使用 Markdown 代码块。根对象必须只有 drafts 数组。"
        "每个 draft 必须严格使用以下类型："
        '{"platform":"xiaohongshu|instagram|wechat_moments|linkedin|general",'
        '"variant":"string","title":"string|null","body":"string",'
        '"hashtags":["string"],"call_to_action":"string|null",'
        '"platform_fit_notes":["string"]}。'
        "hashtags 和 platform_fit_notes 即使只有一项也必须是 JSON 数组，绝不能返回字符串。"
        "platform 必须使用上述英文枚举值，不得返回中文平台名。"
        "不得输出证件号、住址、电话、邮箱、学号等隐私。"
        "不得替用户发布内容，不得伪造经历、成绩、offer、学校身份或他人观点。"
    )
    if not skill_context:
        return base
    return f"{base}\n\n{skill_context}"


def _validate_drafts(
    payload: object,
    platform: SocialPlatform,
    draft_count: int,
) -> tuple[list[SocialContentDraft], list[str]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("drafts"), list):
        return [], ["Root field drafts must be a JSON array."]
    valid: list[SocialContentDraft] = []
    errors: list[str] = []
    for index, raw_draft in enumerate(payload["drafts"][:draft_count]):
        if not isinstance(raw_draft, dict):
            errors.append(f"drafts[{index}] must be a JSON object")
            continue
        try:
            valid.append(SocialContentDraft.model_validate(_normalize_draft(raw_draft, platform)))
        except ValidationError as exc:
            errors.append(f"drafts[{index}]: {_compact_validation_error(exc)}")
    if not valid and not errors:
        errors.append("drafts must contain at least one draft")
    return valid, errors


def _normalize_draft(raw_draft: dict[str, Any], platform: SocialPlatform) -> dict[str, Any]:
    normalized = dict(raw_draft)
    platform_aliases = {
        "小红书": "xiaohongshu",
        "rednote": "xiaohongshu",
        "朋友圈": "wechat_moments",
        "微信朋友圈": "wechat_moments",
        "领英": "linkedin",
        "通用": "general",
    }
    raw_platform = normalized.get("platform")
    if isinstance(raw_platform, str):
        normalized_platform = platform_aliases.get(raw_platform.strip(), raw_platform.strip().lower())
    else:
        normalized_platform = platform
    normalized["platform"] = (
        normalized_platform
        if normalized_platform in {"xiaohongshu", "instagram", "wechat_moments", "linkedin", "general"}
        else platform
    )
    normalized["hashtags"] = _coerce_string_list(normalized.get("hashtags"), split_hashtags=True)
    normalized["platform_fit_notes"] = _coerce_string_list(normalized.get("platform_fit_notes"))
    if not isinstance(normalized.get("variant"), str):
        normalized["variant"] = "balanced"
    for field in ("title", "call_to_action"):
        value = normalized.get(field)
        if value is not None and not isinstance(value, str):
            normalized[field] = str(value)
    return normalized


def _coerce_string_list(value: object, *, split_hashtags: bool = False) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    if isinstance(value, str):
        if split_hashtags:
            return [item for item in re.split(r"[\s#，,、;；]+", value.strip()) if item]
        return [value.strip()] if value.strip() else []
    return [str(value)]


def _compact_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors(include_url=False):
        location = ".".join(str(item) for item in error.get("loc", [])) or "draft"
        parts.append(f"{location}: {error.get('msg', 'invalid value')}")
    return ", ".join(parts)


def _repair_prompt(errors: list[str], draft_count: int, platform: SocialPlatform) -> str:
    error_text = "; ".join(errors)[:1_500] or "The drafts array was empty."
    return (
        "上一条 JSON 未通过结构校验，请修复后重新返回完整 JSON 对象。"
        f"校验错误：{error_text}。"
        f"返回 1 到 {draft_count} 条 {platform} 草稿。"
        "必须确保 hashtags 和 platform_fit_notes 是字符串数组，platform 使用英文枚举，body 是字符串。"
        "只返回修复后的 JSON，不要解释。"
    )
