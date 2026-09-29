from datetime import datetime
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
    "social_content",
    "planner",
    "email",
    "assignment",
    "general",
]
MemoryCandidateStatus = Literal[
    "not_requested",
    "pending_confirmation",
    "confirmed",
    "rejected",
    "deleted",
    "skipped",
    "failed",
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
    access_policy: dict | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class MemoryContext(BaseModel):
    routing: MemoryRoutingDecision
    topic: TopicContinuityResult
    query_rewrite: QueryRewriteResult
    recent_messages: list[ChatTurn] = Field(default_factory=list)
    long_term_memories: list[LongTermMemoryItem] = Field(default_factory=list)
    prompt_context: str = ""


class MemoryCandidateInput(BaseModel):
    namespace: MemoryNamespace | str
    content: str
    source_type: str | None = None
    source_id: str | None = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    requires_confirmation: bool = True
    confirmed: bool = False
    agent_name: str | None = None


class MemoryCandidatePersistRequest(BaseModel):
    user_id: str
    candidates: list[MemoryCandidateInput] = Field(default_factory=list)
    requested: bool = True
    confirmed: bool = False
    source_id: str | None = None


class MemoryCandidatePersistResponse(BaseModel):
    status: MemoryCandidateStatus
    candidate_count: int = 0
    pending_memory_ids: list[str] = Field(default_factory=list)
    confirmed_memory_ids: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    error: str | None = None


class MemoryCandidateDecisionRequest(BaseModel):
    user_id: str
    memory_ids: list[str] = Field(default_factory=list)


class MemoryCandidateDecisionResponse(BaseModel):
    status: MemoryCandidateStatus
    memory_ids: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    error: str | None = None


class MemoryReviewResponse(BaseModel):
    user_id: str
    memories: list[LongTermMemoryItem] = Field(default_factory=list)
    candidates: list[LongTermMemoryItem] = Field(default_factory=list)
