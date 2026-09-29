import json

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

    async def generate(
        self,
        request: SocialContentRequest,
        platform: SocialPlatform,
        standard: PlatformStandard,
    ) -> list[SocialContentDraft]:
        if self.llm is None:
            return []
        skill = self.skill_loader.load("social-content-writing", include_references=True)
        system_prompt = _system_prompt(skill.as_prompt_context() if skill else None)
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
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
                    ],
                    temperature=0.4,
                    response_format={"type": "json_object"},
                )
            )
            payload = json.loads(response.content)
            drafts = payload.get("drafts", [])[: request.draft_count]
            return [SocialContentDraft.model_validate(draft) for draft in drafts]
        except Exception:
            return []


def _system_prompt(skill_context: str | None) -> str:
    base = (
        "你是留学生活场景的社交平台文案助手。"
        "优先遵循下方 Skill 文档与 references，但必须保持输出 schema。"
        "只返回 JSON，字段 drafts 为数组。每个 draft 包含 platform、variant、title、body、hashtags、"
        "call_to_action、platform_fit_notes。不得输出证件号、住址、电话、邮箱、学号等隐私。"
        "不得替用户发布内容，不得伪造经历、成绩、offer、学校身份或他人观点。"
    )
    if not skill_context:
        return base
    return f"{base}\n\n{skill_context}"
