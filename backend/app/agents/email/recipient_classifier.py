from app.schemas.email import RecipientType


class RecipientClassifier:
    KEYWORDS: list[tuple[RecipientType, tuple[str, ...]]] = [
        ("professor", ("professor", "lecturer", "supervisor", "导师", "教授", "老师")),
        ("teaching_assistant", ("ta", "teaching assistant", "助教")),
        ("university_department", ("registry", "student office", "department", "school office", "学校", "学院", "教务")),
        ("landlord", ("landlord", "letting", "property manager", "房东", "中介", "租房")),
        ("service_provider", ("bank", "council", "utility", "gp", "service", "银行", "账单", "市政")),
        ("classmate", ("classmate", "teammate", "groupmate", "同学", "组员")),
    ]

    def classify(self, recipient_hint: str | None, purpose: str) -> RecipientType:
        text = f"{recipient_hint or ''} {purpose}".lower()
        for recipient_type, keywords in self.KEYWORDS:
            if any(keyword in text for keyword in keywords):
                return recipient_type
        return "other"

