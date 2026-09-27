import re

from app.schemas.social_content import SocialContentDraft, SocialContentRequest, SocialContentSafetyCheck

SENSITIVE_PATTERNS = [
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    re.compile(r"\b(?:\+?\d[\d\s-]{7,}\d)\b"),
]
SENSITIVE_KEYWORDS = ("passport", "brp", "visa number", "student id", "address", "护照", "签证号", "学生号", "住址")
BLOCKED_KEYWORDS = ("hate speech", "dox", "人肉", "隐私曝光")


class SocialContentSafetyChecker:
    def check(self, request: SocialContentRequest) -> SocialContentSafetyCheck:
        text = " ".join([request.topic, request.notes or "", *request.key_points, *request.personal_details])
        return self.check_text(text)

    def check_drafts(self, drafts: list[SocialContentDraft]) -> SocialContentSafetyCheck:
        text = " ".join(
            " ".join([draft.title or "", draft.body, draft.call_to_action or "", *draft.hashtags])
            for draft in drafts
        )
        return self.check_text(text)

    def merge(self, first: SocialContentSafetyCheck, second: SocialContentSafetyCheck) -> SocialContentSafetyCheck:
        level_order = {"ok": 0, "needs_review": 1, "blocked": 2}
        level = first.level if level_order[first.level] >= level_order[second.level] else second.level
        return SocialContentSafetyCheck(
            level=level,
            issues=[*first.issues, *[issue for issue in second.issues if issue not in first.issues]],
            redactions=[*first.redactions, *[item for item in second.redactions if item not in first.redactions]],
        )

    def check_text(self, text: str) -> SocialContentSafetyCheck:
        issues = []
        redactions = []

        if any(keyword in text.lower() for keyword in BLOCKED_KEYWORDS):
            return SocialContentSafetyCheck(
                level="blocked",
                issues=["Content appears to request unsafe or privacy-violating publication."],
            )

        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(text):
                issues.append("Potential direct contact detail detected.")
                redactions.append(pattern.sub("[redacted]", text)[:120])
                break

        if any(keyword in text.lower() for keyword in SENSITIVE_KEYWORDS):
            issues.append("Potential identity, immigration, or address detail detected.")

        level = "needs_review" if issues else "ok"
        return SocialContentSafetyCheck(level=level, issues=issues, redactions=redactions)
