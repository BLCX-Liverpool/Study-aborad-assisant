from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.memory.short_term import summarize_messages
from app.schemas.chat import ChatTurn


class MemoryCompressor:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    async def compress(self, messages: list[ChatTurn]) -> str:
        if not messages:
            return ""
        fallback = summarize_messages(messages, max_items=8)
        if self.llm is None:
            return fallback
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "Summarize the conversation into durable context for a study abroad assistant. "
                                "Keep user preferences, deadlines, entities, unresolved questions, and safety boundaries. "
                                "Do not invent facts."
                            ),
                        ),
                        ChatMessage(role="user", content=fallback),
                    ],
                    temperature=0.0,
                )
            )
        except Exception:
            return fallback
        return response.content.strip() or fallback
