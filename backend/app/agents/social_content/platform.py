from app.schemas.social_content import PlatformStandard, SocialPlatform


class SocialPlatformClassifier:
    def classify(self, text: str, requested_platform: SocialPlatform = "general") -> SocialPlatform:
        if requested_platform != "general":
            return requested_platform
        lowered = text.lower()
        if any(keyword in lowered for keyword in ("小红书", "xiaohongshu", "rednote")):
            return "xiaohongshu"
        if any(keyword in lowered for keyword in ("instagram", "reel", "story")):
            return "instagram"
        if any(keyword in lowered for keyword in ("朋友圈", "wechat", "moments")):
            return "wechat_moments"
        if any(keyword in lowered for keyword in ("linkedin", "career", "professional")):
            return "linkedin"
        return "general"


class SocialPlatformStandards:
    def get(self, platform: SocialPlatform) -> PlatformStandard:
        return _STANDARDS.get(platform, _STANDARDS["general"])


_STANDARDS: dict[SocialPlatform, PlatformStandard] = {
    "xiaohongshu": PlatformStandard(
        platform="xiaohongshu",
        recommended_length="标题 12-24 字，正文 200-600 字，分段短，适合收藏。",
        structure=["钩子标题", "真实经历", "步骤/清单", "提醒和边界", "轻量互动"],
        tone_notes=["具体、经验感强", "少用空泛鸡汤", "保留留学生语境"],
        privacy_rules=["不暴露学校精确宿舍、地址、学号、签证号", "涉及他人经历时匿名化"],
    ),
    "instagram": PlatformStandard(
        platform="instagram",
        recommended_length="Caption 80-220 words, hashtags 3-8.",
        structure=["visual hook", "short context", "takeaways", "soft CTA"],
        tone_notes=["visual-first", "concise", "friendly"],
        privacy_rules=["Check faces, geotags, room numbers, documents before posting."],
    ),
    "wechat_moments": PlatformStandard(
        platform="wechat_moments",
        recommended_length="80-300 字，自然口吻，少标签。",
        structure=["一句近况", "2-4 个观察", "收束句"],
        tone_notes=["像发给熟人看的记录", "不过度营销"],
        privacy_rules=["避免精确定位、票据、联系方式、同学姓名"],
    ),
    "linkedin": PlatformStandard(
        platform="linkedin",
        recommended_length="120-500 words, professional and evidence-aware.",
        structure=["context", "challenge", "actions", "learning", "open question"],
        tone_notes=["专业、克制、可验证", "避免夸大成果"],
        privacy_rules=["不透露雇主/学校未公开信息，不未经许可点名他人"],
    ),
    "general": PlatformStandard(
        platform="general",
        recommended_length="120-500 字，按目标平台再二次裁剪。",
        structure=["主题", "背景", "要点", "下一步"],
        tone_notes=["清晰、具体、不过度承诺"],
        privacy_rules=["默认移除身份、位置、证件、联系方式等敏感信息"],
    ),
}
