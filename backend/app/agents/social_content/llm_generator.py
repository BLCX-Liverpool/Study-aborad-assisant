import json

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.social_content import (
    PlatformStandard,
    SocialContentDraft,
    SocialContentRequest,
    SocialPlatform,
)


class LlmSocialCopyGenerator:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    async def generate(
        self,
        request: SocialContentRequest,
        platform: SocialPlatform,
        standard: PlatformStandard,
    ) -> list[SocialContentDraft]:
        if self.llm is None:
            return []
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "你是留学生活场景的社交平台文案助手。"
                                "只返回 JSON，字段 drafts 为数组。每个 draft 包含 platform、variant、title、body、hashtags、"
                                "call_to_action、platform_fit_notes。不得输出证件号、住址、电话、邮箱、学号等隐私。"
                            ),
                        ),
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
