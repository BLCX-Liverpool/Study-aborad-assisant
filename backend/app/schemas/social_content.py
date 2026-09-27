from typing import Literal

from pydantic import BaseModel, Field

SocialPlatform = Literal["xiaohongshu", "instagram", "wechat_moments", "linkedin", "general"]
ContentTone = Literal["practical", "warm", "playful", "reflective", "professional"]
ContentSafetyLevel = Literal["ok", "needs_review", "blocked"]


class SocialContentRequest(BaseModel):
    user_id: str
    topic: str
    platform: SocialPlatform = "general"
    tone: ContentTone = "warm"
    audience: str | None = None
    key_points: list[str] = Field(default_factory=list)
    personal_details: list[str] = Field(default_factory=list)
    include_hashtags: bool = True
    draft_count: int = Field(default=3, ge=1, le=5)
    language: Literal["zh", "en", "bilingual"] = "zh"
    notes: str | None = None


class SocialContentDraft(BaseModel):
    platform: SocialPlatform
    variant: str = "balanced"
    title: str | None = None
    body: str
    hashtags: list[str] = Field(default_factory=list)
    call_to_action: str | None = None
    platform_fit_notes: list[str] = Field(default_factory=list)


class SocialContentSafetyCheck(BaseModel):
    level: ContentSafetyLevel
    issues: list[str] = Field(default_factory=list)
    redactions: list[str] = Field(default_factory=list)


class PlatformStandard(BaseModel):
    platform: SocialPlatform
    recommended_length: str
    structure: list[str] = Field(default_factory=list)
    tone_notes: list[str] = Field(default_factory=list)
    privacy_rules: list[str] = Field(default_factory=list)


class ImageGenerationToolDesign(BaseModel):
    tool_name: str = "social.image_generation.draft"
    status: Literal["designed_not_enabled"] = "designed_not_enabled"
    boundary: str = "Image generation is a separate approved tool and is not executed by the copywriting agent."
    expected_inputs: list[str] = Field(default_factory=list)


class SocialContentOutput(BaseModel):
    summary: str
    drafts: list[SocialContentDraft] = Field(default_factory=list)
    safety: SocialContentSafetyCheck
    platform_standard: PlatformStandard | None = None
    platform_notes: list[str] = Field(default_factory=list)
    image_generation_tool: ImageGenerationToolDesign | None = None
    assumptions: list[str] = Field(default_factory=list)
    disclaimer: str = "This is writing support. Review privacy, accuracy, and platform rules before posting."
