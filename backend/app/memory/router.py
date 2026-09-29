import json

from app.core.llm import ChatMessage, ChatRequest, OpenAICompatibleLLM
from app.memory.namespaces import namespaces_for_intent
from app.schemas.chat import ChatTurn
from app.schemas.memory import MemoryRoutingDecision, MemorySource, TopicContinuityResult
from app.schemas.router import RouterOutput

LONG_TERM_SIGNALS = ("上次", "之前", "曾经", "上周", "上个月", "last time", "previous", "before")


class MemoryRouter:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    def route(self, query: str, router_output: RouterOutput) -> MemoryRoutingDecision:
        need_long_term = _needs_long_term(query)
        namespaces = namespaces_for_intent(router_output.primary_intent)
        sources = ["short_term", "long_term"] if need_long_term else ["short_term"]
        return MemoryRoutingDecision(
            need_short_term_memory=True,
            need_long_term_memory=need_long_term,
            memory_source=sources,  # type: ignore[arg-type]
            namespaces=namespaces,
            reason=_reason(query, need_long_term),
        )

    async def route_async(
        self,
        *,
        query: str,
        router_output: RouterOutput,
        recent_messages: list[ChatTurn],
        topic: TopicContinuityResult,
    ) -> MemoryRoutingDecision:
        fallback = self.route(query, router_output)
        if self.llm is None:
            return fallback.model_copy(update={"reason": fallback.reason + " Memory Router LLM unavailable."})
        recent = "\n".join(f"{message.role}: {message.content}" for message in recent_messages[-8:])
        allowed_namespaces = namespaces_for_intent(router_output.primary_intent)
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "You are the Memory Router for a study-abroad assistant. Decide whether the current query "
                                "needs current context only, short-term memory, long-term memory, or both. Return JSON only: "
                                "{need_short_term_memory:boolean, need_long_term_memory:boolean, memory_source:string[], "
                                "namespaces:string[], reason:string}. Only choose namespaces from allowed_namespaces. "
                                "Use long_term when the user refers to previous trips, preferences, budgets, tasks, prior conversations, "
                                "or asks what they said/did before. Use short_term for current conversation continuity."
                            ),
                        ),
                        ChatMessage(
                            role="user",
                            content=json.dumps(
                                {
                                    "query": query,
                                    "primary_intent": router_output.primary_intent,
                                    "topic_relation": topic.relation,
                                    "topic_summary": topic.topic_summary,
                                    "recent_conversation": recent,
                                    "allowed_namespaces": allowed_namespaces,
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
        except Exception as exc:
            return fallback.model_copy(update={"reason": fallback.reason + f" Memory Router LLM failed: {type(exc).__name__}."})

        sources = _valid_sources(payload.get("memory_source"))
        need_short = bool(payload.get("need_short_term_memory", "short_term" in sources or "both" in sources))
        need_long = bool(payload.get("need_long_term_memory", "long_term" in sources or "both" in sources))
        if need_short and "short_term" not in sources:
            sources.append("short_term")
        if need_long and "long_term" not in sources:
            sources.append("long_term")
        if not sources:
            sources = ["current_context"]
        namespaces = [
            namespace
            for namespace in payload.get("namespaces", allowed_namespaces)
            if namespace in allowed_namespaces
        ] or allowed_namespaces
        return MemoryRoutingDecision(
            need_short_term_memory=need_short,
            need_long_term_memory=need_long,
            memory_source=sources,
            namespaces=namespaces,
            reason=str(payload.get("reason") or "LLM memory router decision."),
        )


def _needs_long_term(query: str) -> bool:
    lowered = query.lower()
    return any(signal.lower() in lowered for signal in LONG_TERM_SIGNALS)


def _reason(query: str, need_long_term: bool) -> str:
    if need_long_term:
        return "The query contains references to prior user context."
    return "Recent short-term context is sufficient for the current turn."


def _valid_sources(value: object) -> list[MemorySource]:
    raw = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    normalized: list[MemorySource] = []
    for item in raw:
        if item == "both":
            normalized.extend(["short_term", "long_term"])
        elif item in {"current_context", "short_term", "long_term"}:
            normalized.append(item)  # type: ignore[arg-type]
    return list(dict.fromkeys(normalized))
