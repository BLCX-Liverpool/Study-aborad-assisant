import json

from app.agents.email.prompts import EMAIL_DRAFT_SYSTEM_PROMPT, build_email_draft_prompt
from app.agents.email.recipient_classifier import RecipientClassifier
from app.agents.email.style_policy import EmailStylePolicyResolver
from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.email import EmailDraft, EmailDraftRequest


class EmailDraftGenerationError(RuntimeError):
    pass


class EmailDraftGenerator:
    def __init__(
        self,
        llm: OpenAICompatibleLLM,
        classifier: RecipientClassifier | None = None,
        style_resolver: EmailStylePolicyResolver | None = None,
    ) -> None:
        self.llm = llm
        self.classifier = classifier or RecipientClassifier()
        self.style_resolver = style_resolver or EmailStylePolicyResolver()

    async def generate(self, request: EmailDraftRequest) -> EmailDraft:
        recipient_type = self.classifier.classify(request.recipient_hint, request.purpose)
        style_policy = self.style_resolver.resolve(recipient_type, request.tone_hint)
        schema_json = json.dumps(EmailDraft.model_json_schema(), ensure_ascii=False)
        prompt = build_email_draft_prompt(request, recipient_type, style_policy, schema_json)

        response = await self.llm.chat(
            ChatRequest(
                messages=[
                    ChatMessage(role="system", content=EMAIL_DRAFT_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=prompt),
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        )

        try:
            payload = json.loads(response.content)
            draft = EmailDraft.model_validate(payload)
        except Exception as exc:
            raise EmailDraftGenerationError("Failed to validate EmailDraft output.") from exc

        return draft.model_copy(
            update={
                "recipient_type": recipient_type,
                "tone": style_policy.tone,
                "requires_user_approval": True,
            }
        )

