from app.agents.social_content.copy_generator import SocialCopyGenerator
from app.agents.social_content.llm_generator import LlmSocialCopyGenerator
from app.agents.social_content.platform import SocialPlatformClassifier, SocialPlatformStandards
from app.agents.social_content.safety import SocialContentSafetyChecker
from app.schemas.social_content import ImageGenerationToolDesign, SocialContentOutput, SocialContentRequest


class SocialContentAgentService:
    def __init__(
        self,
        classifier: SocialPlatformClassifier | None = None,
        standards: SocialPlatformStandards | None = None,
        safety_checker: SocialContentSafetyChecker | None = None,
        copy_generator: SocialCopyGenerator | None = None,
        llm_generator: LlmSocialCopyGenerator | None = None,
    ) -> None:
        self.classifier = classifier or SocialPlatformClassifier()
        self.standards = standards or SocialPlatformStandards()
        self.safety_checker = safety_checker or SocialContentSafetyChecker()
        self.copy_generator = copy_generator or SocialCopyGenerator()
        self.llm_generator = llm_generator

    def create_content(self, request: SocialContentRequest) -> SocialContentOutput:
        platform = self.classifier.classify(request.topic, request.platform)
        standard = self.standards.get(platform)
        input_safety = self.safety_checker.check(request)
        drafts = [] if input_safety.level == "blocked" else self.copy_generator.generate(request, platform)
        draft_safety = self.safety_checker.check_drafts(drafts) if drafts else input_safety
        safety = self.safety_checker.merge(input_safety, draft_safety)
        return SocialContentOutput(
            summary=_summary(platform, len(drafts), safety.level),
            drafts=drafts,
            safety=safety,
            platform_standard=standard,
            platform_notes=_platform_notes(platform),
            image_generation_tool=_image_tool_design(),
            assumptions=_assumptions(request),
        )

    async def create_content_async(self, request: SocialContentRequest) -> SocialContentOutput:
        platform = self.classifier.classify(request.topic, request.platform)
        standard = self.standards.get(platform)
        input_safety = self.safety_checker.check(request)
        drafts = []
        if input_safety.level != "blocked" and self.llm_generator is not None:
            drafts = await self.llm_generator.generate(request, platform, standard)
        if input_safety.level != "blocked" and not drafts:
            drafts = self.copy_generator.generate(request, platform)
        draft_safety = self.safety_checker.check_drafts(drafts) if drafts else input_safety
        safety = self.safety_checker.merge(input_safety, draft_safety)
        if safety.level == "blocked":
            drafts = []
        return SocialContentOutput(
            summary=_summary(platform, len(drafts), safety.level),
            drafts=drafts,
            safety=safety,
            platform_standard=standard,
            platform_notes=_platform_notes(platform),
            image_generation_tool=_image_tool_design(),
            assumptions=_assumptions(request),
        )


def _summary(platform: str, draft_count: int, safety_level: str) -> str:
    if safety_level == "blocked":
        return "Content request was blocked by the privacy and safety checker."
    return f"Generated {draft_count} {platform} copy draft(s)."


def _platform_notes(platform: str) -> list[str]:
    notes = {
        "xiaohongshu": ["Keep paragraphs short, concrete, and experience-led.", "Avoid exposing exact address, school ID, or private contacts."],
        "instagram": ["Use concise captions and visual-first phrasing.", "Review image/video privacy before posting."],
        "wechat_moments": ["Write naturally for acquaintances; avoid oversharing personal records."],
        "linkedin": ["Keep claims accurate and professional.", "Avoid naming people or organizations without permission."],
        "general": ["Review tone and privacy before posting."],
    }
    return notes.get(platform, notes["general"])


def _assumptions(request: SocialContentRequest) -> list[str]:
    assumptions = ["Current agent generates copy only; image generation must use a separate approved tool."]
    if request.personal_details:
        assumptions.append("Personal details were treated as privacy-sensitive context.")
    if request.notes:
        assumptions.append("User notes were used as soft writing context.")
    return assumptions


def _image_tool_design() -> ImageGenerationToolDesign:
    return ImageGenerationToolDesign(
        expected_inputs=[
            "approved_copy_draft_id",
            "platform",
            "visual_style_reference",
            "privacy_review_status",
            "output_size",
        ]
    )
