from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

SensitivityLevel = Literal["low", "medium", "high", "restricted"]


@dataclass(frozen=True)
class MemoryRetentionPolicy:
    sensitivity: SensitivityLevel
    retain: bool
    requires_user_confirmation: bool
    expires_at: datetime | None
    reason: str


HIGH_SENSITIVITY = (
    "suicide",
    "self harm",
    "自杀",
    "自残",
    "diagnosis",
    "medical",
    "passport",
    "visa number",
    "brp",
    "护照",
    "签证号",
)
MEDIUM_SENSITIVITY = ("fitness", "gym", "健身", "运动", "budget", "预算", "rent", "房租")


def classify_memory_sensitivity(text: str) -> SensitivityLevel:
    lowered = text.lower()
    if any(keyword in lowered for keyword in HIGH_SENSITIVITY):
        return "restricted"
    if any(keyword in lowered for keyword in MEDIUM_SENSITIVITY):
        return "medium"
    if len(text) > 300:
        return "medium"
    return "low"


def retention_policy_for(text: str, *, user_confirmed: bool = False) -> MemoryRetentionPolicy:
    sensitivity = classify_memory_sensitivity(text)
    now = datetime.now(UTC)
    if sensitivity == "restricted":
        return MemoryRetentionPolicy(
            sensitivity=sensitivity,
            retain=False,
            requires_user_confirmation=True,
            expires_at=None,
            reason="Restricted sensitive content is not retained by default.",
        )
    if sensitivity == "medium" and not user_confirmed:
        return MemoryRetentionPolicy(
            sensitivity=sensitivity,
            retain=False,
            requires_user_confirmation=True,
            expires_at=None,
            reason="Medium sensitivity memory requires explicit user confirmation.",
        )
    return MemoryRetentionPolicy(
        sensitivity=sensitivity,
        retain=True,
        requires_user_confirmation=False,
        expires_at=now + timedelta(days=365 if sensitivity == "low" else 90),
        reason="Memory is allowed by retention policy.",
    )
