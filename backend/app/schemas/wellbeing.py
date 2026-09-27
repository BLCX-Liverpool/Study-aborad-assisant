from typing import Literal

from pydantic import BaseModel, Field

RiskLevel = Literal["low", "medium", "high", "crisis"]


class WellbeingSupportRequest(BaseModel):
    user_id: str
    message: str
    context: str | None = None
    allow_sensitive_memory: bool = False


class WellbeingSafetyAssessment(BaseModel):
    risk_level: RiskLevel
    indicators: list[str] = Field(default_factory=list)
    should_escalate: bool = False


class WellbeingSupportResponse(BaseModel):
    safety: WellbeingSafetyAssessment
    supportive_message: str
    grounding_steps: list[str] = Field(default_factory=list)
    suggested_actions: list[str] = Field(default_factory=list)
    crisis_guidance: list[str] = Field(default_factory=list)
    professional_help_notice: str
    should_store_sensitive_content: bool = False
