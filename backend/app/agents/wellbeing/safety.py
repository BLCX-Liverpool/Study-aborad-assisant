from app.schemas.wellbeing import WellbeingSafetyAssessment

CRISIS_KEYWORDS = (
    "kill myself",
    "suicide",
    "end my life",
    "want to die",
    "自杀",
    "不想活",
    "结束生命",
)

HIGH_RISK_KEYWORDS = (
    "hurt myself",
    "self harm",
    "cut myself",
    "hurt someone",
    "harm someone",
    "伤害自己",
    "自残",
    "伤害别人",
)

MEDIUM_RISK_KEYWORDS = (
    "panic",
    "can't sleep",
    "cannot sleep",
    "overwhelmed",
    "hopeless",
    "崩溃",
    "失眠",
    "焦虑",
    "绝望",
)


class WellbeingSafetyLayer:
    def assess(self, message: str, context: str | None = None) -> WellbeingSafetyAssessment:
        text = f"{message} {context or ''}".lower()
        crisis = _matches(text, CRISIS_KEYWORDS)
        if crisis:
            return WellbeingSafetyAssessment(
                risk_level="crisis",
                indicators=crisis,
                should_escalate=True,
            )

        high = _matches(text, HIGH_RISK_KEYWORDS)
        if high:
            return WellbeingSafetyAssessment(
                risk_level="high",
                indicators=high,
                should_escalate=True,
            )

        medium = _matches(text, MEDIUM_RISK_KEYWORDS)
        if medium:
            return WellbeingSafetyAssessment(
                risk_level="medium",
                indicators=medium,
                should_escalate=False,
            )

        return WellbeingSafetyAssessment(risk_level="low")


def _matches(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if keyword.lower() in text]
