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


class RegisteredTool(BaseModel):
    spec: ToolSpec
    handler: ToolHandler
    availability_checker: ToolAvailabilityChecker | None = None

    model_config = {"arbitrary_types_allowed": True}


class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False
    user_id: str | None = None
    conversation_id: str | None = None
    trace_id: str | None = None


class ToolCallResult(BaseModel):
    tool_name: str
    success: bool
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    requires_approval: bool = False
    permission_level: PermissionLevel | None = None
