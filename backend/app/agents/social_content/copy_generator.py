from app.schemas.social_content import SocialContentDraft, SocialContentRequest, SocialPlatform


class SocialCopyGenerator:
    def generate(self, request: SocialContentRequest, platform: SocialPlatform) -> list[SocialContentDraft]:
        variants = ["balanced", "practical", "storytelling", "concise", "reflective"][: request.draft_count]
        return [
            SocialContentDraft(
                platform=platform,
                variant=variant,
                title=_title(request, platform, variant),
                body=_body(request, platform, variant),
                hashtags=_hashtags(request, platform) if request.include_hashtags else [],
                call_to_action=_call_to_action(platform, variant),
                platform_fit_notes=_platform_fit_notes(platform, variant),
            )
            for variant in variants
        ]


def _title(request: SocialContentRequest, platform: SocialPlatform, variant: str) -> str | None:
    if platform == "wechat_moments":
        return None
    if platform == "xiaohongshu":
        travel_title = _xiaohongshu_travel_title(request.key_points, variant)
        if travel_title:
            return travel_title
    topic = _compact_topic(request.topic, 18 if platform == "xiaohongshu" else 36)
    if request.language == "en":
        return f"{topic}: a {variant} student-life note"
    if platform == "linkedin":
        return f"{topic}｜留学生经验复盘"
    if variant == "practical":
        return f"{topic}｜实用攻略"
    if variant == "storytelling":
        return f"{topic}｜真实旅行记录"
    return f"{topic}｜留学生真实记录"


def _body(request: SocialContentRequest, platform: SocialPlatform, variant: str) -> str:
    points = request.key_points or _points_from_topic(request.topic)
    audience = request.audience or "同样在海外学习生活的人"
    if request.language == "en":
        return _english_body(request, platform, points, audience, variant)
    if platform == "xiaohongshu":
        return _xiaohongshu_body(request, points, audience, variant)
    if platform == "wechat_moments":
        return _moments_body(request, points, variant)
    if platform == "linkedin":
        return _linkedin_body(request, points, variant)
    return _general_zh_body(request, points, audience, variant)


def _xiaohongshu_body(request: SocialContentRequest, points: list[str], audience: str, variant: str) -> str:
    lead = {
        "practical": "这篇直接整理成可照做版本。",
        "storytelling": "一开始我也很乱，后来才发现可以这样拆。",
        "concise": "短版记录，先抓重点。",
        "reflective": "这件事给我的提醒比流程本身更重要。",
    }.get(variant, "最近想记录一下。")
    lines = [
        f"{lead}主题是：{request.topic}。",
        f"适合看到这篇的人：{audience}。",
        "",
        "我的观察：",
        *[f"- {point}" for point in points],
        "",
        "留学生活很多时候不是一步到位，而是不断把混乱整理成可执行的小动作。",
    ]
    return "\n".join(lines)


def _compact_topic(topic: str, limit: int) -> str:
    compact = topic.strip(" ，,。")
    for marker in ("请你帮我", "请帮我", "帮我写", "麻烦帮我"):
        if marker in compact:
            compact = compact.split(marker, 1)[0].strip(" ，,。")
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip(" ，,。")


def _xiaohongshu_travel_title(points: list[str], variant: str) -> str | None:
    destination = next((point.removeprefix("去了").strip() for point in points if point.startswith("去了")), "")
    highlights = [
        point.removeprefix("参观了").removeprefix("打卡了").strip()
        for point in points
        if point.startswith(("参观了", "打卡了"))
    ]
    highlights = [item for item in highlights if item]
    if not destination or not highlights:
        return None
    joined = "和".join(highlights[:2])
    label = {
        "practical": "旅行攻略",
        "storytelling": "旅行实录",
        "concise": "旅行速记",
        "reflective": "旅行回忆",
    }.get(variant, "旅行记录")
    title = f"{destination}{label}｜{joined}"
    return title if len(title) <= 24 else f"{destination}{label}｜{joined[: max(6, 23 - len(destination + label))]}"


def _points_from_topic(topic: str) -> list[str]:
    clauses = [item.strip(" ，,。") for item in topic.replace("，", "。").split("。")]
    concrete = [item for item in clauses if item]
    return concrete[:3] or ["记录这次经历", "整理值得分享的细节", "补充自己的真实感受"]


def _moments_body(request: SocialContentRequest, points: list[str], variant: str) -> str:
    closing = "慢慢来，但确实在往前走。" if variant != "concise" else "先记下来。"
    return "\n".join(
        [
            f"{request.topic}",
            "今天的小记录：",
            *[f"{index + 1}. {point}" for index, point in enumerate(points[:4])],
            closing,
        ]
    )


def _linkedin_body(request: SocialContentRequest, points: list[str], variant: str) -> str:
    intro = "I recently reflected on" if request.language == "en" else "最近围绕"
    return "\n".join(
        [
            f"{intro} {request.topic} 做了一次复盘。",
            "",
            "Key takeaways:",
            *[f"- {point}" for point in points],
            "",
            "这段经历提醒我，留学生的成长不只是适应环境，也包括把经验沉淀成下一次可复用的方法。",
        ]
    )


def _general_zh_body(request: SocialContentRequest, points: list[str], audience: str, variant: str) -> str:
    prefix = "简短版：" if variant == "concise" else "想分享一个小经验："
    return "\n".join(
        [
            f"{prefix}「{request.topic}」。",
            f"如果你也是{audience}，也许会有一点参考。",
            "",
            *[f"- {point}" for point in points],
            "",
            "先把事情做小，再把节奏稳住。",
        ]
    )


def _english_body(
    request: SocialContentRequest,
    platform: SocialPlatform,
    points: list[str],
    audience: str,
    variant: str,
) -> str:
    return "\n".join(
        [
            f"A {variant} student-life note on {request.topic}.",
            f"For: {audience}.",
            "",
            "What stood out:",
            *[f"- {point}" for point in points],
            "",
            "Small systems make overseas study feel a little less chaotic.",
        ]
    )


def _hashtags(request: SocialContentRequest, platform: SocialPlatform) -> list[str]:
    base = ["留学生活", "海外学习"]
    if platform == "xiaohongshu":
        base.extend(["留学生日常", "经验分享"])
    elif platform == "instagram":
        base.extend(["studentlife", "studyabroad"])
    elif platform == "linkedin":
        base.extend(["StudyAbroad", "StudentExperience"])
    return base[:6]


def _call_to_action(platform: SocialPlatform, variant: str) -> str:
    if platform == "linkedin":
        return "欢迎交流类似经历和方法。"
    if platform == "wechat_moments":
        return "记录一下，也给之后的自己看。"
    if variant == "practical":
        return "可以先收藏，需要时逐条对照。"
    return "你也有类似经历的话，可以先收藏，之后慢慢对照。"


def _platform_fit_notes(platform: SocialPlatform, variant: str) -> list[str]:
    notes = [f"Variant: {variant}."]
    if platform == "xiaohongshu":
        notes.append("Use short paragraphs, concrete steps, and privacy-safe anecdotes.")
    elif platform == "linkedin":
        notes.append("Keep claims evidence-aware and avoid private organizational details.")
    elif platform == "wechat_moments":
        notes.append("Keep the tone natural and suitable for acquaintances.")
    else:
        notes.append("Review length and tone before adapting to the final channel.")
    return notes
