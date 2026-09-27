from app.schemas.memory import MemoryNamespace
from app.schemas.router import Intent


INTENT_NAMESPACE: dict[Intent, MemoryNamespace] = {
    "assignment": "academic",
    "task_planning": "shared",
    "email": "shared",
    "notice_action": "shared",
    "travel": "travel",
    "finance": "finance",
    "wellbeing": "wellbeing",
    "fitness": "fitness",
    "social_content": "social",
    "general_chat": "shared",
}

SHARED_READERS: dict[MemoryNamespace, set[MemoryNamespace]] = {
    "shared": {"shared", "academic", "travel", "finance", "wellbeing", "fitness", "social"},
    "academic": {"shared", "academic"},
    "travel": {"shared", "travel", "finance"},
    "finance": {"shared", "finance", "travel"},
    "wellbeing": {"shared", "wellbeing"},
    "fitness": {"shared", "fitness", "wellbeing"},
    "social": {"shared", "social"},
}


def namespaces_for_intent(intent: Intent) -> list[MemoryNamespace]:
    namespace = INTENT_NAMESPACE.get(intent, "shared")
    readable = SHARED_READERS.get(namespace, {"shared", namespace})
    return sorted(readable)


def infer_memory_namespace(text: str, fallback: MemoryNamespace = "shared") -> MemoryNamespace:
    lowered = text.lower()
    if any(keyword in lowered for keyword in ("budget", "rent", "tuition", "预算", "房租", "学费")):
        return "finance"
    if any(keyword in lowered for keyword in ("travel", "trip", "flight", "旅行", "机票", "酒店")):
        return "travel"
    if any(keyword in lowered for keyword in ("assignment", "coursework", "作业", "论文", "课程")):
        return "academic"
    if any(keyword in lowered for keyword in ("stress", "lonely", "焦虑", "孤独", "压力")):
        return "wellbeing"
    if any(keyword in lowered for keyword in ("gym", "fitness", "健身", "运动")):
        return "fitness"
    if any(keyword in lowered for keyword in ("xiaohongshu", "instagram", "小红书", "朋友圈")):
        return "social"
    if any(keyword in lowered for keyword in ("不吃", "allergy", "过敏", "timezone", "时区")):
        return "shared"
    return fallback
