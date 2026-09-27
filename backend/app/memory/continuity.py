import re

from app.schemas.chat import ChatTurn
from app.schemas.memory import TopicContinuityResult


CONTINUATION_SIGNALS = ("继续", "刚才", "上面", "那个", "这个", "it", "that", "this", "continue")
NEW_TOPIC_SIGNALS = ("换个话题", "另外", "新的", "new topic", "unrelated")


class TopicContinuityDetector:
    def detect(self, query: str, recent_messages: list[ChatTurn]) -> TopicContinuityResult:
        if not recent_messages:
            return TopicContinuityResult(relation="NEW_TOPIC", score=0.0)

        recent_text = " ".join(message.content for message in recent_messages[-5:])
        query_entities = _entities(query)
        recent_entities = _entities(recent_text)
        entity_overlap = _overlap_score(query_entities, recent_entities)
        lexical_overlap = _lexical_overlap(query, recent_text)
        continuation_score = 1.0 if _contains_any(query, CONTINUATION_SIGNALS) else 0.0
        new_topic_penalty = 1.0 if _contains_any(query, NEW_TOPIC_SIGNALS) else 0.0
        recent_turn_score = min(len(recent_messages) / 5, 1.0)

        score = (
            0.25 * continuation_score
            + 0.25 * entity_overlap
            + 0.25 * lexical_overlap
            + 0.15 * recent_turn_score
            - 0.25 * new_topic_penalty
        )
        score = max(0.0, min(1.0, score))

        if score >= 0.75:
            relation = "CONTINUE"
        elif score <= 0.30:
            relation = "NEW_TOPIC"
        else:
            relation = "AMBIGUOUS"

        return TopicContinuityResult(
            relation=relation,
            score=score,
            active_entities=sorted(query_entities | recent_entities)[:12],
            topic_summary=_topic_summary(recent_messages),
            needs_llm_judgement=relation == "AMBIGUOUS",
        )


def _entities(text: str) -> set[str]:
    latin = set(re.findall(r"\b[A-Z][A-Za-z0-9]{2,}\b", text))
    course_codes = set(re.findall(r"\b[A-Z]{2,}\d{2,}\b", text))
    chinese_chunks = set(re.findall(r"[\u4e00-\u9fff]{2,8}", text))
    return latin | course_codes | chinese_chunks


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9_\-]+|[\u4e00-\u9fff]{2,}", text.lower()))


def _overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left | right), 1)


def _lexical_overlap(query: str, recent_text: str) -> float:
    return _overlap_score(_tokens(query), _tokens(recent_text))


def _contains_any(text: str, signals: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(signal.lower() in lowered for signal in signals)


def _topic_summary(messages: list[ChatTurn]) -> str | None:
    if not messages:
        return None
    joined = " / ".join(message.content[:80] for message in messages[-3:])
    return joined or None
