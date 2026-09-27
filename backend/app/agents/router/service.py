import json
import re
from dataclasses import dataclass
from typing import Any

from app.core.llm import ChatMessage, ChatRequest, EmbeddingRequest, OpenAICompatibleLLM, get_stage_llm_client
from app.schemas.router import Intent, IntentFusionMetadata, RouterOutput, StructuredIntent


class IntentRouter:
    """Structured multi-intent router with semantic-vector + LLM voting fusion."""

    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        router_llm = llm or get_stage_llm_client("router")
        self.embedding_classifier = EmbeddingIntentClassifier(router_llm)
        self.llm_classifier = LlmIntentClassifier(router_llm)
        self.fusion = IntentFusion()

    def route(
        self,
        message: str,
        uploaded_file_ids: list[str] | None = None,
        agent_inputs: dict[str, dict] | None = None,
    ) -> RouterOutput:
        uploaded_file_ids = uploaded_file_ids or []
        agent_inputs = agent_inputs or {}
        embedding = self.embedding_classifier.classify_fallback(
            message,
            uploaded_file_ids=uploaded_file_ids,
            agent_inputs=agent_inputs,
        )
        return self.fusion.merge(
            embedding=embedding,
            llm=None,
            message=message,
            uploaded_file_ids=uploaded_file_ids,
        )

    async def route_async(
        self,
        message: str,
        uploaded_file_ids: list[str] | None = None,
        agent_inputs: dict[str, dict] | None = None,
    ) -> RouterOutput:
        uploaded_file_ids = uploaded_file_ids or []
        agent_inputs = agent_inputs or {}
        embedding = await self.embedding_classifier.classify(
            message,
            uploaded_file_ids=uploaded_file_ids,
            agent_inputs=agent_inputs,
        )
        llm = await self.llm_classifier.classify(message)
        return self.fusion.merge(
            embedding=embedding,
            llm=llm,
            message=message,
            uploaded_file_ids=uploaded_file_ids,
        )


@dataclass
class ClassificationResult:
    source: str
    intents: list[StructuredIntent]
    raw: dict[str, Any]

    @property
    def primary(self) -> StructuredIntent | None:
        if not self.intents:
            return None
        return sorted(self.intents, key=lambda item: item.confidence, reverse=True)[0]


class EmbeddingIntentClassifier:
    """Semantic-vector intent classifier.

    The primary path embeds the user message and intent prototypes, then ranks
    intents by cosine similarity. If embedding is unavailable, deterministic
    keyword scoring is used only as a fallback.
    """

    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    async def classify(
        self,
        message: str,
        *,
        uploaded_file_ids: list[str],
        agent_inputs: dict[str, dict],
    ) -> ClassificationResult:
        if self.llm is None:
            return self.classify_fallback(
                message,
                uploaded_file_ids=uploaded_file_ids,
                agent_inputs=agent_inputs,
            )
        try:
            prototype_items = list(INTENT_VECTOR_PROTOTYPES.items())
            response = await self.llm.embed(
                EmbeddingRequest(inputs=[message, *[description for _, description in prototype_items]])
            )
            message_embedding = response.embeddings[0]
            scored: list[tuple[Intent, float]] = []
            for (intent, _), embedding in zip(prototype_items, response.embeddings[1:], strict=True):
                score = max(0.0, _cosine_similarity(message_embedding, embedding))
                if intent in agent_inputs:
                    score += 0.12
                if intent == "assignment" and uploaded_file_ids:
                    score += 0.08
                if score > 0.18:
                    scored.append((intent, min(score, 1.0)))
            if _has_unsafe_signal(message.lower()):
                scored.append(("unsafe_request", 0.95))
            if not scored:
                return ClassificationResult(
                    source="semantic_vector",
                    intents=[
                        StructuredIntent(
                            name="unknown",
                            agent_intent="unknown",
                            confidence=0.42,
                            missing_slots=["intent"],
                            source="semantic_vector",
                        )
                    ],
                    raw={"method": "semantic_vector", "scores": [], "embedding_model": response.model},
                )
            scored.sort(key=lambda item: item[1], reverse=True)
            intents = [
                _structured_intent_for(message, intent, confidence, source="semantic_vector")
                for intent, confidence in scored[:4]
            ]
            calendar_intents = _calendar_intents(message)
            if calendar_intents:
                intents = [*calendar_intents, *[intent for intent in intents if not intent.name.startswith("calendar.")]]
            return ClassificationResult(
                source="semantic_vector",
                intents=intents,
                raw={
                    "method": "semantic_vector",
                    "embedding_model": response.model,
                    "scores": [{"intent": intent, "score": score} for intent, score in scored[:8]],
                },
            )
        except Exception as exc:
            fallback = self.classify_fallback(
                message,
                uploaded_file_ids=uploaded_file_ids,
                agent_inputs=agent_inputs,
            )
            fallback.raw["method"] = "semantic_vector_failed_fallback"
            fallback.raw["embedding_error"] = str(exc)
            return fallback

    def classify_fallback(
        self,
        message: str,
        *,
        uploaded_file_ids: list[str],
        agent_inputs: dict[str, dict],
    ) -> ClassificationResult:
        text = message.lower()
        scored: list[tuple[Intent, float]] = []
        for intent, profile in INTENT_PROFILES.items():
            score = _semantic_score(text, profile)
            if intent in agent_inputs:
                score += 0.55
            if intent == "assignment" and uploaded_file_ids:
                score += 0.25
            if score > 0:
                scored.append((intent, min(score, 1.0)))

        if _has_unsafe_signal(text):
            scored.append(("unsafe_request", 0.95))
        if _looks_like_system_command(text):
            scored.append(("system_command", 0.92))
        if not scored and _looks_like_chitchat(text):
            scored.append(("chitchat", 0.72))

        if not scored:
            intents = [
                StructuredIntent(
                    name="unknown",
                    agent_intent="unknown",
                    confidence=0.42,
                    missing_slots=["intent"],
                    source="embedding_fallback",
                )
            ]
            return ClassificationResult(
                source="embedding_fallback",
                intents=intents,
                raw={"method": "keyword_fallback", "scores": []},
            )

        scored.sort(key=lambda item: item[1], reverse=True)
        intents = [
            _structured_intent_for(message, intent, confidence, source="embedding_fallback")
            for intent, confidence in scored[:4]
        ]
        calendar_intents = _calendar_intents(message)
        if calendar_intents:
            intents = [*calendar_intents, *[intent for intent in intents if not intent.name.startswith("calendar.")]]
        return ClassificationResult(
            source="embedding_fallback",
            intents=intents,
            raw={
                "method": "keyword_fallback",
                "scores": [{"intent": intent, "score": score} for intent, score in scored[:6]],
            },
        )


class LlmIntentClassifier:
    def __init__(self, llm: OpenAICompatibleLLM | None = None) -> None:
        self.llm = llm

    async def classify(self, message: str) -> ClassificationResult | None:
        if self.llm is None:
            return None
        try:
            response = await self.llm.chat(
                ChatRequest(
                    messages=[
                        ChatMessage(
                            role="system",
                            content=(
                                "You classify a study-abroad assistant user message into structured intents. "
                                "Return JSON object with intents array. Each intent must include name, agent_intent, "
                                "slots, optional condition, depends_on, missing_slots, confidence. "
                                "Support multi-intent splitting, slot extraction, dependencies, uncertainty, and fallback intents. "
                                "Allowed agent_intent values: assignment, task_planning, email, notice_action, travel, finance, wellbeing, "
                                "fitness, social_content, general_chat, unknown, clarification_required, chitchat, out_of_scope, "
                                "unsafe_request, system_command. Do not execute tools."
                            ),
                        ),
                        ChatMessage(role="user", content=message),
                    ],
                    temperature=0.0,
                    response_format={"type": "json_object"},
                )
            )
            payload = json.loads(response.content)
        except Exception as exc:
            return ClassificationResult(source="llm", intents=[], raw={"error": str(exc)})

        raw_intents = payload.get("intents", [])
        intents: list[StructuredIntent] = []
        if isinstance(raw_intents, list):
            for raw in raw_intents:
                if not isinstance(raw, dict):
                    continue
                raw.setdefault("source", "llm")
                try:
                    intents.append(StructuredIntent.model_validate(raw))
                except Exception:
                    continue
        return ClassificationResult(source="llm", intents=intents, raw=payload)


class IntentFusion:
    def merge(
        self,
        *,
        embedding: ClassificationResult,
        llm: ClassificationResult | None,
        message: str,
        uploaded_file_ids: list[str],
    ) -> RouterOutput:
        embedding_primary = embedding.primary
        llm_primary = llm.primary if llm else None
        selected = _select_intents(embedding, llm, message)
        primary = selected[0] if selected else StructuredIntent(name="unknown", agent_intent="unknown", confidence=0.35)

        if primary.agent_intent == "unknown" and primary.confidence < 0.5:
            primary = primary.model_copy(update={"agent_intent": "clarification_required"})

        clarification_questions = _clarification_questions(selected, message)
        fusion_strategy = _fusion_strategy(embedding_primary, llm_primary)
        disagreement = (
            embedding_primary is not None
            and llm_primary is not None
            and embedding_primary.agent_intent != llm_primary.agent_intent
        )
        metadata = IntentFusionMetadata(
            embedding_primary=embedding_primary.agent_intent if embedding_primary else None,
            embedding_confidence=embedding_primary.confidence if embedding_primary else 0.0,
            llm_primary=llm_primary.agent_intent if llm_primary else None,
            llm_confidence=llm_primary.confidence if llm_primary else 0.0,
            fusion_strategy=fusion_strategy,
            disagreement=disagreement,
            uncertainty_reason=_uncertainty_reason(primary, selected),
            raw_sources={
                "embedding": embedding.raw,
                "llm": llm.raw if llm else None,
            },
        )

        primary_intent = _dispatchable_intent(primary.agent_intent)
        secondary = [
            item.agent_intent
            for item in selected[1:4]
            if item.agent_intent != primary_intent
        ]
        risk_level = "high" if primary_intent == "wellbeing" and _has_high_risk_signal(message.lower()) else "low"
        needs_file_parsing = primary_intent in {"assignment", "notice_action"} or bool(uploaded_file_ids)
        needs_tool = primary_intent in {"assignment", "travel", "notice_action", "task_planning"}

        return RouterOutput(
            primary_intent=primary_intent,
            secondary_intents=secondary,
            confidence=max(min(primary.confidence, 1.0), 0.0),
            structured_intents=selected,
            clarification_questions=clarification_questions,
            fusion_metadata=metadata,
            needs_file_parsing=needs_file_parsing,
            needs_memory=True,
            needs_tool=needs_tool,
            risk_level=risk_level,
        )


INTENT_PROFILES: dict[Intent, tuple[str, ...]] = {
    "assignment": ("assignment", "coursework", "rubric", "brief", "作业", "论文", "评分", "课程要求", "deadline"),
    "task_planning": ("plan", "schedule", "timeline", "reminder", "安排", "计划", "提醒", "规划", "calendar", "日历", "会议"),
    "email": ("email", "mail", "professor", "extension", "邮件", "教授", "导师", "房东", "回信"),
    "notice_action": ("notice", "bill", "letter", "invoice", "通知", "账单", "租房信", "市政", "due"),
    "travel": ("travel", "trip", "flight", "hotel", "airport", "旅行", "行程", "机票", "机场", "酒店"),
    "finance": ("budget", "expense", "rent", "tuition", "deposit", "预算", "支出", "房租", "学费", "押金"),
    "wellbeing": ("stress", "anxious", "lonely", "overwhelmed", "hurt myself", "suicide", "焦虑", "孤独", "压力", "崩溃", "自杀", "自残"),
    "fitness": ("fitness", "workout", "gym", "exercise", "健身", "训练", "运动"),
    "social_content": ("xiaohongshu", "instagram", "post", "vlog", "小红书", "朋友圈", "文案", "社交媒体"),
    "general_chat": ("hello", "hi", "你好", "谢谢", "thanks"),
}


def _semantic_score(text: str, profile: tuple[str, ...]) -> float:
    matches = sum(1 for keyword in profile if keyword.lower() in text)
    if matches == 0:
        return 0.0
    return min(0.35 + matches * 0.15, 0.9)


def _structured_intent_for(message: str, intent: Intent, confidence: float, *, source: str) -> StructuredIntent:
    operation = {
        "assignment": "assignment.analyze",
        "task_planning": "planner.create_or_update_plan",
        "email": "email.draft",
        "notice_action": "notice.parse_actions",
        "travel": "travel.plan",
        "finance": "finance.review_budget",
        "wellbeing": "wellbeing.support",
        "fitness": "fitness.create_plan",
        "social_content": "social_content.create_drafts",
        "general_chat": "general_chat.respond",
        "unsafe_request": "unsafe_request",
        "system_command": "system_command",
        "chitchat": "chitchat",
        "unknown": "unknown",
    }.get(intent, str(intent))
    slots = _extract_slots(message, operation)
    missing_slots = _missing_slots(operation, slots)
    condition = _extract_condition(message, operation)
    depends_on = [0] if condition and operation == "calendar.create_event" else []
    agent_intent = _agent_intent_for_operation(operation, fallback=intent)
    return StructuredIntent(
        name=operation,
        agent_intent=agent_intent,
        slots=slots,
        condition=condition,
        depends_on=depends_on,
        missing_slots=missing_slots,
        confidence=confidence,
        source=source,
    )


def _extract_slots(message: str, operation: str) -> dict[str, Any]:
    slots: dict[str, Any] = {}
    if "明天" in message:
        slots["date"] = "明天"
    if "今天" in message:
        slots["date"] = "今天"
    if "下午" in message:
        slots["time_range"] = "下午"
    if "上午" in message:
        slots["time_range"] = "上午"
    if operation == "calendar.create_event":
        event_match = re.search(r"安排一个?([^，。,.]+?)(?:会|会议|meeting)", message)
        if event_match:
            slots["event_name"] = event_match.group(1).strip() + "会"
    if operation == "travel.plan":
        match = re.search(r"(?:去|to)\s*([A-Za-z\u4e00-\u9fff\s]{2,40})", message)
        if match:
            slots["destination"] = match.group(1).strip()
    return slots


def _missing_slots(operation: str, slots: dict[str, Any]) -> list[str]:
    required = {
        "calendar.query_availability": ["date", "time_range"],
        "calendar.create_event": ["event_name"],
        "travel.plan": ["origin", "destination"],
        "email.draft": ["recipient_or_recipient_type", "purpose"],
    }.get(operation, [])
    return [slot for slot in required if slot not in slots]


def _extract_condition(message: str, operation: str) -> str | None:
    if operation == "calendar.create_event" and ("如果没有" in message or "if no" in message.lower()):
        return "前置日历查询没有发现冲突或会议"
    return None


def _select_intents(
    embedding: ClassificationResult,
    llm: ClassificationResult | None,
    message: str,
) -> list[StructuredIntent]:
    if llm and llm.intents:
        return _with_calendar_split(message, _vote_intents(embedding.intents, llm.intents))
    return _with_calendar_split(message, embedding.intents)


def _vote_intents(
    embedding_intents: list[StructuredIntent],
    llm_intents: list[StructuredIntent],
) -> list[StructuredIntent]:
    votes: dict[str, dict[str, Any]] = {}
    for weight, intents in ((0.5, embedding_intents), (0.5, llm_intents)):
        for rank, intent in enumerate(intents[:4]):
            key = intent.name
            if key not in votes:
                votes[key] = {"intent": intent, "score": 0.0, "sources": set()}
            rank_decay = 1.0 - rank * 0.12
            votes[key]["score"] += weight * intent.confidence * max(rank_decay, 0.5)
            votes[key]["sources"].add(intent.source)
            existing = votes[key]["intent"]
            if intent.confidence > existing.confidence:
                votes[key]["intent"] = intent
    selected = []
    for value in votes.values():
        intent = value["intent"]
        voted_confidence = min(float(value["score"]), 1.0)
        sources = sorted(value["sources"])
        selected.append(
            intent.model_copy(
                update={
                    "confidence": max(voted_confidence, intent.confidence if len(sources) > 1 else voted_confidence),
                    "source": "vote:" + "+".join(sources),
                }
            )
        )
    return sorted(selected, key=lambda item: item.confidence, reverse=True)


def _with_calendar_split(message: str, intents: list[StructuredIntent]) -> list[StructuredIntent]:
    if not intents:
        return intents
    if not _looks_like_calendar_workflow(message):
        return intents
    if any(intent.name.startswith("calendar.") for intent in intents):
        return intents
    return [*_calendar_intents(message), *intents]


def _calendar_intents(message: str) -> list[StructuredIntent]:
    if not _looks_like_calendar_workflow(message):
        return []
    query_slots = _extract_slots(message, "calendar.query_availability")
    create_slots = _extract_slots(message, "calendar.create_event")
    query = StructuredIntent(
        name="calendar.query_availability",
        agent_intent="task_planning",
        slots=query_slots,
        confidence=0.68,
        missing_slots=_missing_slots("calendar.query_availability", query_slots),
        source="embedding",
    )
    create = StructuredIntent(
        name="calendar.create_event",
        agent_intent="task_planning",
        slots=create_slots,
        condition=_extract_condition(message, "calendar.create_event") or "需要先确认对应时间段可用",
        depends_on=[0],
        confidence=0.62,
        missing_slots=_missing_slots("calendar.create_event", create_slots),
        source="embedding",
    )
    return [query, create]


def _looks_like_calendar_workflow(message: str) -> bool:
    lowered = message.lower()
    return any(word in lowered for word in ("meeting", "calendar", "availability", "会议", "日历", "有没有会", "安排一个"))


def _agent_intent_for_operation(operation: str, fallback: Intent) -> Intent:
    if operation.startswith("calendar."):
        return "task_planning"
    return fallback


def _dispatchable_intent(intent: Intent) -> Intent:
    if intent in {"unknown", "chitchat", "clarification_required"}:
        return "general_chat"
    return intent


def _clarification_questions(intents: list[StructuredIntent], message: str) -> list[str]:
    questions = []
    for intent in intents:
        if intent.missing_slots:
            questions.append(f"{intent.name} 缺少信息：{', '.join(intent.missing_slots)}。")
    if not questions and intents and intents[0].agent_intent == "clarification_required":
        questions.append("请补充你希望我处理的具体事项。")
    return questions[:3]


def _fusion_strategy(embedding_primary: StructuredIntent | None, llm_primary: StructuredIntent | None) -> str:
    if llm_primary is None:
        return "semantic_vector_only" if embedding_primary and embedding_primary.source == "semantic_vector" else "embedding_fallback_only"
    if embedding_primary is None:
        return "llm_only"
    if embedding_primary.agent_intent == llm_primary.agent_intent:
        return "semantic_vector_llm_vote_agree"
    return "semantic_vector_llm_vote_disagree"


def _uncertainty_reason(primary: StructuredIntent, selected: list[StructuredIntent]) -> str | None:
    if primary.confidence < 0.5:
        return "Primary intent confidence is below threshold."
    if any(intent.missing_slots for intent in selected):
        return "One or more structured intents have missing slots."
    return None


def _has_unsafe_signal(text: str) -> bool:
    return any(signal in text for signal in ("suicide", "hurt myself", "自杀", "自残", "人肉", "隐私曝光"))


def _looks_like_system_command(text: str) -> bool:
    return any(signal in text for signal in ("删除系统", "wipe database", "ignore previous", "越权", "sudo rm"))


def _looks_like_chitchat(text: str) -> bool:
    compact = text.strip()
    return compact in {"hi", "hello", "你好", "谢谢", "thanks"} or len(compact) <= 4


def _has_high_risk_signal(text: str) -> bool:
    return any(signal in text for signal in ("suicide", "hurt myself", "自杀", "自残", "不想活"))


INTENT_VECTOR_PROTOTYPES: dict[Intent, str] = {
    "assignment": "Analyze coursework briefs, rubrics, deadlines, marking criteria, academic reports, submissions, course requirements.",
    "task_planning": "Plan tasks, schedules, reminders, calendar availability, meetings, timelines, multi-step action plans.",
    "email": "Draft emails to professors, landlords, university staff, extension requests, replies, formal messages.",
    "notice_action": "Extract actions from bills, invoices, official notices, tenancy letters, payment due dates, council tax notices.",
    "travel": "Plan trips, flights, hotels, airports, transport, weather for travel, travel checklist.",
    "finance": "Budget, expenses, rent, tuition, deposit, savings goals, bills, student finance planning.",
    "wellbeing": "Stress, anxiety, loneliness, overwhelm, mental health support, crisis or self-harm signals.",
    "fitness": "Workout, gym, exercise, training schedule, mobility, cardio, strength plan.",
    "social_content": "Write social media posts, Xiaohongshu, Instagram, WeChat Moments, LinkedIn, captions, content drafts.",
    "general_chat": "General conversation, greetings, lightweight questions that do not require a specialized agent.",
}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = sum(a * a for a in left) ** 0.5
    right_norm = sum(b * b for b in right) ** 0.5
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
