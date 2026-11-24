from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from app.core.permissions import PermissionLevel

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
ToolAvailabilityChecker = Callable[[], "ToolAvailabilityStatus"]


class ToolAvailabilityStatus(BaseModel):
    name: str
    capability: str
    available: bool
    status: str = "unavailable"
    permission_level: PermissionLevel
    required_env: list[str] = Field(default_factory=list)
    missing_env: list[str] = Field(default_factory=list)
    recoverable_error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolSpec(BaseModel):
    name: str
    description: str
    permission_level: PermissionLevel
    capability: str | None = None
    provider_name: str | None = None
    required_env: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    external_api: bool = False
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_attempts: int = Field(default=1, ge=1, le=3)
    cache_ttl_seconds: int = Field(default=60, ge=0, le=86_400)


class RegisteredTool(BaseModel):
    spec: ToolSpec
    handler: ToolHandler
    availability_checker: ToolAvailabilityChecker | None = None
    input_model: type[BaseModel] | None = None

    model_config = {"arbitrary_types_allowed": True}


class ToolCallRequest(BaseModel):
    call_id: str | None = None
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False
    idempotency_key: str | None = None
    user_id: str | None = None
    conversation_id: str | None = None
    trace_id: str | None = None


class ToolCallResult(BaseModel):
    call_id: str | None = None
    tool_name: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    arguments: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    requires_approval: bool = False
    permission_level: PermissionLevel | None = None
    attempts: int = 0
    duration_ms: float | None = None
    degraded: bool = False
    cached: bool = False
    retryable: bool = False
    error_type: str | None = None
