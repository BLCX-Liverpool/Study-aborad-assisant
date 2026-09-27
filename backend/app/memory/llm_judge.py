from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.chat import ChatTurn
from app.schemas.memory import TopicContinuityResult


class TopicAmbiguityJudge:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    async def judge(
        self,
        *,
        query: str,
        recent_messages: list[ChatTurn],
        initial: TopicContinuityResult,
    ) -> TopicContinuityResult:
        if not initial.needs_llm_judgement or self.llm is None:
            return initial
        recent = "\n".join(f"{message.role}: {message.content}" for message in recent_messages[-6:])
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "Classify whether the user query continues the recent topic. "
                                "Return only one label: CONTINUE, SUBTOPIC, RETURN_TOPIC, NEW_TOPIC, or AMBIGUOUS."
                            ),
                        ),
                        ChatMessage(role="user", content=f"Recent:\n{recent}\n\nQuery:\n{query}"),
                    ],
                    temperature=0.0,
                )
            )
        except Exception:
            return initial

        label = response.content.strip().split()[0].upper()
        if label not in {"CONTINUE", "SUBTOPIC", "RETURN_TOPIC", "NEW_TOPIC", "AMBIGUOUS"}:
            return initial
        score = 0.8 if label in {"CONTINUE", "SUBTOPIC", "RETURN_TOPIC"} else 0.2 if label == "NEW_TOPIC" else initial.score
        return initial.model_copy(update={"relation": label, "score": score, "needs_llm_judgement": False})
