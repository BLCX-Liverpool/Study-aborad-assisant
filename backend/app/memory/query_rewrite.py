from app.schemas.memory import QueryRewriteResult, TopicContinuityResult


REFERENCE_SIGNALS = ("那个", "这个", "上次", "之前", "刚才", "它", "this", "that", "it", "previous")


class QueryRewriter:
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


def _has_reference_signal(query: str) -> bool:
    lowered = query.lower()
    return any(signal.lower() in lowered for signal in REFERENCE_SIGNALS)
