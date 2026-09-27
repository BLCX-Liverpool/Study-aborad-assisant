from typing import Literal

from pydantic import BaseModel, Field


Intent = Literal[
    "assignment",
    "task_planning",
    "email",
    "notice_action",
    "travel",
    "finance",
    "wellbeing",
    "fitness",
    "social_content",
    "general_chat",
    "unknown",
    "clarification_required",
    "chitchat",
    "out_of_scope",
    "unsafe_request",
    "system_command",
]


class StructuredIntent(BaseModel):
    name: str
    agent_intent: Intent
    slots: dict = Field(default_factory=dict)
    condition: str | None = None
    depends_on: list[int] = Field(default_factory=list)
    missing_slots: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = "fusion"


class IntentFusionMetadata(BaseModel):
    embedding_primary: str | None = None
    embedding_confidence: float = 0.0
    llm_primary: str | None = None
    llm_confidence: float = 0.0
    fusion_strategy: str = "embedding_only"
    disagreement: bool = False
    uncertainty_reason: str | None = None
    raw_sources: dict = Field(default_factory=dict)


class RouterOutput(BaseModel):
    primary_intent: Intent
    secondary_intents: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    structured_intents: list[StructuredIntent] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    fusion_metadata: IntentFusionMetadata = Field(default_factory=IntentFusionMetadata)
    needs_file_parsing: bool = False
    needs_memory: bool = True
    needs_tool: bool = False
    risk_level: Literal["low", "medium", "high"] = "low"
