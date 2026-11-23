import json

import pytest

from app.agents.router.service import IntentRouter
from app.core.llm import ChatResponse, EmbeddingResponse


def test_router_detects_email_and_task_planning() -> None:
    result = IntentRouter().route("帮我给教授写一封 extension 邮件，然后安排后续提醒")

    assert result.primary_intent == "email"
    assert "task_planning" in result.secondary_intents
    assert result.confidence >= 0.55


def test_router_marks_assignment_file_parsing() -> None:
    result = IntentRouter().route(
        "分析这个 coursework brief",
        uploaded_file_ids=["file_1"],
    )

    assert result.primary_intent == "assignment"
    assert result.needs_file_parsing is True
    assert result.needs_tool is True


def test_router_splits_calendar_workflow_into_structured_intents() -> None:
    result = IntentRouter().route("帮我查一下明天下午有没有会议，如果没有就安排一个项目讨论会。")

    assert result.primary_intent == "task_planning"
    assert [intent.name for intent in result.structured_intents[:2]] == [
        "calendar.query_availability",
        "calendar.create_event",
    ]
    assert result.structured_intents[0].slots["date"] == "明天"
    assert result.structured_intents[0].slots["time_range"] == "下午"
    assert result.structured_intents[1].slots["event_name"] == "项目讨论会"
    assert result.structured_intents[1].depends_on == [0]
    assert result.fusion_metadata.embedding_primary is not None


def test_router_uses_fallback_intent_for_unclear_request() -> None:
    result = IntentRouter().route("这个怎么办")

    assert result.primary_intent == "clarification_required"
    assert result.structured_intents[0].agent_intent == "clarification_required"
    assert result.clarification_questions


@pytest.mark.asyncio
async def test_router_async_uses_embedding_candidates_then_llm_reranking() -> None:
    class FakeRouterModel:
        default_model = "router-test"
        default_embedding_model = "router-embedding-test"

        async def embed(self, request):
            vectors = []
            for text in request.inputs:
                lowered = text.lower()
                if "calendar" in lowered or "schedule" in lowered or "会议" in lowered or "安排" in lowered:
                    vectors.append([1.0, 0.0, 0.0])
                elif "email" in lowered or "邮件" in lowered:
                    vectors.append([0.0, 1.0, 0.0])
                else:
                    vectors.append([0.0, 0.0, 1.0])
            return EmbeddingResponse(
                embeddings=vectors,
                model=self.default_embedding_model,
            )

        async def chat(self, request):
            return ChatResponse(
                content=json.dumps(
                    {
                        "intents": [
                            {
                                "name": "calendar.query_availability",
                                "agent_intent": "task_planning",
                                "slots": {"date": "明天", "time_range": "下午"},
                                "depends_on": [],
                                "missing_slots": [],
                                "confidence": 0.88,
                            },
                            {
                                "name": "calendar.create_event",
                                "agent_intent": "task_planning",
                                "slots": {"event_name": "项目讨论会"},
                                "condition": "下午没有其他会议",
                                "depends_on": [0],
                                "missing_slots": [],
                                "confidence": 0.84,
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                model=self.default_model,
            )

    model = FakeRouterModel()
    result = await IntentRouter(llm=model).route_async(
        "帮我查一下明天下午有没有会议，如果没有就安排一个项目讨论会。",
        conversation_context=[{"role": "user", "content": "我们正在讨论项目会议"}],
    )

    assert result.primary_intent == "task_planning"
    assert result.fusion_metadata.raw_sources["embedding"]["method"] == "semantic_vector_top_k"
    assert result.fusion_metadata.raw_sources["llm"]["intents"]
    assert result.fusion_metadata.fusion_strategy == "rules_embedding_coarse_llm_rerank"
    assert result.fusion_metadata.context_used is True
    assert result.structured_intents[0].source == "llm_reranker"


def test_router_routes_self_harm_to_wellbeing_with_high_risk() -> None:
    result = IntentRouter().route("我不想活了，想自杀")

    assert result.primary_intent == "wellbeing"
    assert result.risk_level == "high"
    assert result.structured_intents[0].name == "wellbeing.support"
    assert all(item.agent_intent != "unsafe_request" for item in result.structured_intents)


def test_router_reports_medium_risk_for_anxiety_without_crisis_signal() -> None:
    result = IntentRouter().route("我最近很焦虑，压力很大")

    assert result.primary_intent == "wellbeing"
    assert result.risk_level == "medium"


def test_keyword_fallback_uses_word_boundaries() -> None:
    result = IntentRouter().route("My current assignment needs review")

    assert result.primary_intent == "assignment"
    assert "finance" not in result.secondary_intents


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("帮我安排一个伦敦旅行计划", "travel"),
        ("帮我安排一个健身训练计划", "fitness"),
        ("我想了解会议文化", "clarification_required"),
    ],
)
def test_calendar_rules_do_not_trigger_for_non_calendar_actions(message: str, expected: str) -> None:
    result = IntentRouter().route(message)

    assert result.primary_intent == expected
    assert all(not item.name.startswith("calendar.") for item in result.structured_intents)


@pytest.mark.asyncio
async def test_llm_receives_query_context_rules_candidates_and_definitions() -> None:
    class CapturingModel:
        default_model = "router-test"
        default_embedding_model = "router-embedding-test"

        def __init__(self) -> None:
            self.rerank_payload = None

        async def embed(self, request):
            vectors = [[1.0, 0.0]]
            for text in request.inputs[1:]:
                vectors.append([1.0, 0.0] if "email" in text.lower() else [0.0, 1.0])
            return EmbeddingResponse(embeddings=vectors, model=self.default_embedding_model)

        async def chat(self, request):
            self.rerank_payload = json.loads(request.messages[1].content)
            return ChatResponse(
                content=json.dumps(
                    {
                        "intents": [
                            {
                                "name": "email",
                                "agent_intent": "email",
                                "slots": {"recipient_or_recipient_type": "教授", "purpose": "申请延期"},
                                "depends_on": [],
                                "missing_slots": [],
                                "confidence": 0.93,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                model=self.default_model,
            )

    model = CapturingModel()
    result = await IntentRouter(llm=model).route_async(
        "那就帮我写一封申请延期的邮件",
        conversation_context=[{"role": "user", "content": "我的统计学作业周五截止"}],
    )

    assert result.primary_intent == "email"
    assert result.structured_intents[0].name == "email.draft"
    assert model.rerank_payload["query"] == "那就帮我写一封申请延期的邮件"
    assert "统计学作业" in model.rerank_payload["dialogue_context_summary"]
    assert model.rerank_payload["rule_candidates"]
    assert model.rerank_payload["embedding_top_k"]
    assert "email" in model.rerank_payload["intent_definitions"]


@pytest.mark.asyncio
async def test_llm_dependencies_are_reordered_and_remapped_by_operation_name() -> None:
    class DependencyModel:
        default_model = "router-test"
        default_embedding_model = "router-embedding-test"

        async def embed(self, request):
            return EmbeddingResponse(embeddings=[[1.0, 0.0] for _ in request.inputs], model=self.default_embedding_model)

        async def chat(self, request):
            return ChatResponse(
                content=json.dumps(
                    {
                        "intents": [
                            {
                                "name": "calendar.create_event",
                                "agent_intent": "task_planning",
                                "slots": {"event_name": "项目讨论会"},
                                "depends_on": ["calendar.query_availability"],
                                "missing_slots": [],
                                "confidence": 0.95,
                            },
                            {
                                "name": "calendar.query_availability",
                                "agent_intent": "task_planning",
                                "slots": {"date": "明天", "time_range": "下午"},
                                "depends_on": [],
                                "missing_slots": [],
                                "confidence": 0.80,
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
                model=self.default_model,
            )

    result = await IntentRouter(llm=DependencyModel()).route_async(
        "查一下明天下午有没有会议，如果没有就安排一个项目讨论会"
    )

    assert [item.name for item in result.structured_intents[:2]] == [
        "calendar.query_availability",
        "calendar.create_event",
    ]
    assert result.structured_intents[1].depends_on == [0]
