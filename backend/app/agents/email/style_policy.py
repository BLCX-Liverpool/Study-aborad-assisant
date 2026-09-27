from dataclasses import dataclass

from app.schemas.email import EmailTone, RecipientType


@dataclass(frozen=True)
class EmailStylePolicy:
    tone: EmailTone
    salutation: str
    closing: str
    guidance: list[str]


class EmailStylePolicyResolver:
    def resolve(self, recipient_type: RecipientType, tone_hint: EmailTone | None = None) -> EmailStylePolicy:
        if tone_hint:
            tone = tone_hint
        elif recipient_type in {"professor", "teaching_assistant", "university_department", "landlord", "service_provider"}:
            tone = "formal"
        else:
            tone = "friendly"

        if recipient_type == "professor":
            return EmailStylePolicy(
                tone=tone,
                salutation="Dear Professor [Name],",
                closing="Best regards,",
                guidance=[
                    "Be concise and respectful.",
                    "Mention course code and assignment context when available.",
                    "Make a clear request without sounding demanding.",
                ],
            )

        if recipient_type == "teaching_assistant":
            return EmailStylePolicy(
                tone=tone,
                salutation="Dear [Name],",
                closing="Best regards,",
                guidance=[
                    "Be polite and specific.",
                    "Include course or tutorial context.",
                    "Ask for clarification clearly.",
                ],
            )

        if recipient_type == "classmate":
            return EmailStylePolicy(
                tone=tone,
                salutation="Hi [Name],",
                closing="Best,",
                guidance=[
                    "Keep the tone friendly.",
                    "State the shared task or course context.",
                    "Make the next action easy to answer.",
                ],
            )

        return EmailStylePolicy(
            tone=tone,
            salutation="Dear [Name],",
            closing="Best regards,",
            guidance=[
                "Use a clear subject line.",
                "State the context and request directly.",
                "Avoid committing to external actions on behalf of the user.",
            ],
        )

