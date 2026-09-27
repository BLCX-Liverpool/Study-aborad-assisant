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

    assert result.primary_intent == "general_chat"
    assert result.structured_intents[0].agent_intent in {"clarification_required", "unknown"}
    assert result.clarification_questions


@pytest.mark.asyncio
async def test_router_async_uses_semantic_vector_and_llm_voting() -> None:
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

    result = await IntentRouter(llm=FakeRouterModel()).route_async(
        "帮我查一下明天下午有没有会议，如果没有就安排一个项目讨论会。"
    )

    assert result.primary_intent == "task_planning"
    assert result.fusion_metadata.raw_sources["embedding"]["method"] == "semantic_vector"
    assert result.fusion_metadata.raw_sources["llm"]["intents"]
    assert result.fusion_metadata.fusion_strategy == "semantic_vector_llm_vote_agree"
    assert result.structured_intents[0].source.startswith("vote:")
