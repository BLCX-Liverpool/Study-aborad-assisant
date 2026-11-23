import json

import pytest

from app.agents.orchestrator.repository import AgentRunRecorder
from app.agents.orchestrator.graph import build_orchestrator_graph
from app.agents.orchestrator.workers import GeneralChatWorker, WorkerContext, WorkerRegistry
from app.agents.router.service import IntentRouter, RuleIntentClassifier
from app.agents.social_content.input_extractor import (
    fallback_social_content_payload,
    normalize_social_content_payload,
)
from app.agents.social_content.service import SocialContentAgentService
from app.core.tracing import TraceEvent
from app.memory.continuity import TopicContinuityDetector
from app.memory.query_rewrite import QueryRewriter
from app.schemas.chat import ChatRequest, ChatTurn
from app.schemas.memory import MemoryContext, MemoryRoutingDecision, QueryRewriteResult
from app.schemas.router import RouterOutput
from app.schemas.social_content import SocialContentRequest


def test_social_fallback_extracts_concrete_york_details() -> None:
    payload = fallback_social_content_payload(
        "我上周去约克玩了一圈，参观了肉铺街和约克大教堂，请你帮我写一份发到小红书上的文案"
    )

    assert payload["topic"] == "我上周去约克玩了一圈，参观了肉铺街和约克大教堂"
    assert payload["platform"] == "xiaohongshu"
    assert payload["key_points"] == ["去了约克", "参观了肉铺街", "参观了约克大教堂"]

    payload["user_id"] = "user_1"
    output = SocialContentAgentService().create_content(SocialContentRequest.model_validate(payload))
    assert output.drafts[0].title == "约克旅行记录｜肉铺街和约克大教堂"
    assert "发生了什么" not in output.drafts[0].body


def test_social_llm_payload_aliases_are_normalized() -> None:
    assert normalize_social_content_payload(
        {"platform": "小红书", "tone": "温暖", "language": "中文"}
    ) == {"platform": "xiaohongshu", "tone": "warm", "language": "zh"}

    malformed = normalize_social_content_payload(
        {
            "personal_details": {"place": "约克", "visits": ["肉铺街", "约克大教堂"]},
            "save_memory_candidates": ["not", "a", "boolean"],
            "draft_count": "9",
        }
    )
    assert malformed["personal_details"] == ["约克", "['肉铺街', '约克大教堂']"]
    assert "save_memory_candidates" not in malformed
    assert malformed["draft_count"] == 5


def test_previous_question_routes_to_general_chat_without_llm() -> None:
    result = RuleIntentClassifier().classify(
        "我上次的提问是什么",
        uploaded_file_ids=[],
        agent_inputs={},
    )

    assert result.primary is not None
    assert result.primary.agent_intent == "general_chat"
    assert result.primary.confidence == 0.96

    rewritten = IntentRouter().route(
        "基于当前话题上下文（帮我写小红书文案），用户问题是：我上次的提问是什么"
    )
    assert rewritten.primary_intent == "general_chat"
    assert len(rewritten.structured_intents) == 1


def test_previous_reference_is_treated_as_conversation_continuity() -> None:
    recent = [
        ChatTurn(role="user", content="我上周去了约克，参观了肉铺街。"),
        ChatTurn(role="assistant", content="已经为你生成小红书文案。"),
    ]
    topic = TopicContinuityDetector().detect("我上次的提问是什么", recent)
    rewrite = QueryRewriter().rewrite("我上次的提问是什么", topic)

    assert topic.relation != "NEW_TOPIC"
    assert rewrite.changed is True
    assert "约克" in rewrite.rewritten_query


@pytest.mark.asyncio
async def test_general_chat_answers_previous_question_from_short_term_memory() -> None:
    previous = "我上周去约克玩了一圈，请帮我写一份小红书文案"
    context = MemoryContext(
        routing=MemoryRoutingDecision(
            need_short_term_memory=True,
            need_long_term_memory=False,
            memory_source=["short_term"],
            namespaces=["general"],
            reason="test",
        ),
        topic=TopicContinuityDetector().detect(
            "我上次的提问是什么",
            [ChatTurn(role="user", content=previous)],
        ),
        query_rewrite=QueryRewriteResult(
            original_query="我上次的提问是什么",
            rewritten_query="我上次的提问是什么",
        ),
        recent_messages=[
            ChatTurn(role="user", content=previous),
            ChatTurn(role="assistant", content="Generated 3 drafts."),
        ],
    )

    result = await GeneralChatWorker().run(
        WorkerContext(
            request=ChatRequest(user_id="user_1", message="我上次的提问是什么"),
            memory_context=context,
        )
    )

    assert previous in result.final_response
    assert result.trace_events[0]["name"] == "orchestrator.conversation_recall"


@pytest.mark.asyncio
async def test_agent_run_recorder_converts_datetimes_to_json_values() -> None:
    class JsonCheckingSession:
        def __init__(self) -> None:
            self.run = None

        def add(self, run) -> None:
            self.run = run

        async def commit(self) -> None:
            json.dumps(self.run.input_json)
            json.dumps(self.run.output_json)

        async def rollback(self) -> None:
            return None

    session = JsonCheckingSession()
    recorder = AgentRunRecorder(session)  # type: ignore[arg-type]
    await recorder.record_completed_run(
        user_id="user_1",
        conversation_id="conv_1",
        trace_id="trace_1",
        agent_name="general_chat",
        router_output=RouterOutput(primary_intent="general_chat", confidence=0.96),
        input_json={},
        output_json={
            "trace": [
                TraceEvent(trace_id="trace_1", name="test").model_dump(),
            ]
        },
    )

    assert session.run is not None
    json.dumps(session.run.output_json)


@pytest.mark.asyncio
async def test_agent_run_persistence_failure_does_not_fail_chat() -> None:
    class Router:
        async def route_async(self, *args, **kwargs):
            return RouterOutput(primary_intent="general_chat", confidence=0.96)

    class MemoryManager:
        async def build_context(self, *, request, conversation_id, router_output):
            return MemoryContext(
                routing=MemoryRoutingDecision(
                    need_short_term_memory=True,
                    need_long_term_memory=False,
                    memory_source=["short_term"],
                    namespaces=["general"],
                    reason="test",
                ),
                topic=TopicContinuityDetector().detect(request.message, []),
                query_rewrite=QueryRewriteResult(
                    original_query=request.message,
                    rewritten_query=request.message,
                ),
                recent_messages=[],
            )

        async def update_after_response(self, **kwargs):
            return None

    class FailingRecorder:
        rolled_back = False

        async def record_completed_run(self, **kwargs):
            raise TypeError("observability persistence failed")

        async def rollback(self):
            self.rolled_back = True

    recorder = FailingRecorder()
    graph = build_orchestrator_graph(
        router=Router(),  # type: ignore[arg-type]
        memory_manager=MemoryManager(),  # type: ignore[arg-type]
        worker_registry=WorkerRegistry(workers=[GeneralChatWorker()]),
        recorder=recorder,  # type: ignore[arg-type]
    )
    result = await graph.ainvoke(
        {
            "request": ChatRequest(
                user_id="user_1",
                message="你好",
                persist_agent_runs=True,
            )
        }
    )

    assert result["response"].final_response
    assert recorder.rolled_back is True
    assert "agent_run.persist_failed" in [event.name for event in result["response"].trace]
