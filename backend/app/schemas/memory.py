from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.chat import ChatTurn

MemorySource = Literal["current_context", "short_term", "long_term", "both"]
TopicRelation = Literal["CONTINUE", "SUBTOPIC", "NEW_TOPIC", "RETURN_TOPIC", "AMBIGUOUS"]
MemoryNamespace = Literal[
    "shared",
    "academic",
    "travel",
    "finance",
    "wellbeing",
    "fitness",
    "social",
]


class MemoryRoutingDecision(BaseModel):
    need_short_term_memory: bool = True
    need_long_term_memory: bool = False
    memory_source: list[MemorySource] = Field(default_factory=lambda: ["short_term"])
    namespaces: list[MemoryNamespace] = Field(default_factory=lambda: ["shared"])
    reason: str


class TopicContinuityResult(BaseModel):
    relation: TopicRelation
    score: float = Field(ge=0.0, le=1.0)
    active_entities: list[str] = Field(default_factory=list)
    topic_summary: str | None = None
    needs_llm_judgement: bool = False


class QueryRewriteResult(BaseModel):
    original_query: str
    rewritten_query: str
    changed: bool = False
    reason: str | None = None


class LongTermMemoryItem(BaseModel):
    id: str | None = None
    namespace: MemoryNamespace | str
    memory_type: str
    content: str
    score: float = 0.0
    source_type: str | None = None
    source_id: str | None = None
    confidence: float | None = None


class MemoryContext(BaseModel):
    routing: MemoryRoutingDecision
    topic: TopicContinuityResult
    query_rewrite: QueryRewriteResult
    recent_messages: list[ChatTurn] = Field(default_factory=list)
    long_term_memories: list[LongTermMemoryItem] = Field(default_factory=list)
    prompt_context: str = ""
