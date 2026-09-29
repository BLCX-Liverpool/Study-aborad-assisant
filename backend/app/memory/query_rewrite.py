import json

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.schemas.chat import ChatTurn
from app.schemas.memory import QueryRewriteResult, TopicContinuityResult


REFERENCE_SIGNALS = ("那个", "这个", "上次", "之前", "刚才", "它", "this", "that", "it", "previous")


class QueryRewriter:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    def rewrite(self, query: str, topic: TopicContinuityResult) -> QueryRewriteResult:
        if topic.relation not in {"CONTINUE", "SUBTOPIC", "RETURN_TOPIC", "AMBIGUOUS"}:
            return QueryRewriteResult(original_query=query, rewritten_query=query)

        if not _has_reference_signal(query):
            return QueryRewriteResult(original_query=query, rewritten_query=query)

        context = topic.topic_summary or ", ".join(topic.active_entities[:5])
        if not context:
            return QueryRewriteResult(original_query=query, rewritten_query=query)

        rewritten = f"基于当前话题上下文（{context}），用户问题是：{query}"
        return QueryRewriteResult(
            original_query=query,
            rewritten_query=rewritten,
            changed=True,
            reason="Detected reference signal and attached recent topic context.",
        )

    async def rewrite_async(
        self,
        *,
        query: str,
        topic: TopicContinuityResult,
        recent_messages: list[ChatTurn],
    ) -> QueryRewriteResult:
        fallback = self.rewrite(query, topic)
        if topic.relation not in {"CONTINUE", "SUBTOPIC", "RETURN_TOPIC", "AMBIGUOUS"}:
            return fallback
        if self.llm is None:
            return fallback
        recent = "\n".join(f"{message.role}: {message.content}" for message in recent_messages[-10:])
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "Resolve references and rewrite the user query for retrieval. Return JSON only with "
                                "original_query, rewritten_query, changed, reason. Use recent conversation, topic summary, "
                                "active entities, recent tool/task context if present. Do not add facts that are not grounded in context."
                            ),
                        ),
                        ChatMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "query": query,
                                    "topic_relation": topic.relation,
                                    "topic_summary": topic.topic_summary,
                                    "active_entities": topic.active_entities,
                                    "recent_conversation": recent,
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
            )
            payload = json.loads(response.content)
        except Exception:
            return fallback
        rewritten = str(payload.get("rewritten_query") or query).strip()
        changed = bool(payload.get("changed", rewritten != query)) and rewritten != query
        return QueryRewriteResult(
            original_query=query,
            rewritten_query=rewritten or query,
            changed=changed,
            reason=str(payload.get("reason") or "LLM query rewrite.") if changed else None,
        )


def _has_reference_signal(query: str) -> bool:
    lowered = query.lower()
    return any(signal.lower() in lowered for signal in REFERENCE_SIGNALS)
