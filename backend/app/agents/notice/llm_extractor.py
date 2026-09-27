import json

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.action import ActionItem, NoticeParseRequest


class LlmNoticeExtractor:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    async def extract(self, request: NoticeParseRequest) -> list[ActionItem]:
        if self.llm is None:
            return []
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "Extract action items from the notice as JSON array. "
                                "Each item must include title, action_type, description, priority, optional deadline/start_time/end_time/location. "
                                "Allowed action_type values: assignment_deadline, bill_due, tenancy_action, travel_event, appointment, email_follow_up, generic_task. "
                                "Do not invent dates or amounts."
                            ),
                        ),
                        ChatMessage(role="user", content=request.text),
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
            )
            payload = json.loads(response.content)
        except Exception:
            return []
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []
        parsed: list[ActionItem] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item.setdefault("source_type", request.source_type)
            item.setdefault("source_id", request.source_id)
            try:
                parsed.append(ActionItem.model_validate(item))
            except Exception:
                continue
        return parsed
