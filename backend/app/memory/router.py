from app.memory.namespaces import namespaces_for_intent
from app.schemas.memory import MemoryRoutingDecision
from app.schemas.router import RouterOutput

LONG_TERM_SIGNALS = ("上次", "之前", "曾经", "上周", "上个月", "last time", "previous", "before")


class MemoryRouter:
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


def _needs_long_term(query: str) -> bool:
    lowered = query.lower()
    return any(signal.lower() in lowered for signal in LONG_TERM_SIGNALS)


def _reason(query: str, need_long_term: bool) -> str:
    if need_long_term:
        return "The query contains references to prior user context."
    return "Recent short-term context is sufficient for the current turn."
