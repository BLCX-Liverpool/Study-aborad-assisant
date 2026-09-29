import pytest
import json

from app.memory.continuity import TopicContinuityDetector
from app.memory.candidates import MemoryCandidateService
from app.memory.manager import MemoryManager
from app.memory.policy import classify_memory_sensitivity, retention_policy_for
from app.memory.query_rewrite import QueryRewriter
from app.memory.router import MemoryRouter
from app.memory.short_term import InMemoryShortTermMemoryStore
from app.memory.token_counter import TokenCounter
from app.core.llm import ChatResponse
from app.schemas.chat import ChatRequest, ChatTurn
from app.schemas.memory import MemoryCandidateInput
from app.schemas.router import RouterOutput


def test_memory_router_detects_long_term_reference() -> None:
    router_output = RouterOutput(primary_intent="travel", confidence=0.8)

    decision = MemoryRouter().route("我上次去东京住的是哪家酒店？", router_output)

    assert decision.need_long_term_memory is True
    assert "travel" in decision.namespaces
    assert "finance" in decision.namespaces


@pytest.mark.asyncio
async def test_memory_router_uses_llm_decision_for_sources_and_namespaces() -> None:
    class FakeMemoryRouterLlm:
        async def chat(self, request):
            return ChatResponse(
                content=json.dumps(
                    {
                        "need_short_term_memory": True,
                        "need_long_term_memory": True,
                        "memory_source": ["short_term", "long_term"],
                        "namespaces": ["shared", "travel"],
                        "reason": "User asks about a previous trip.",
                    }
                ),
                model="fake-memory",
            )

    decision = await MemoryRouter(llm=FakeMemoryRouterLlm()).route_async(
        query="我上次住的酒店叫什么？",
        router_output=RouterOutput(primary_intent="travel", confidence=0.9),
        recent_messages=[ChatTurn(role="user", content="我们在聊东京旅行。")],
        topic=TopicContinuityDetector().detect("我上次住的酒店叫什么？", [ChatTurn(role="user", content="我们在聊东京旅行。")]),
    )

    assert decision.need_long_term_memory is True
    assert decision.memory_source == ["short_term", "long_term"]
    assert decision.namespaces == ["shared", "travel"]


def test_topic_continuity_and_query_rewrite() -> None:
    recent = [
        ChatTurn(role="user", content="我正在处理 COMP702 coursework，deadline 是 10 月 10 日。"),
        ChatTurn(role="assistant", content="我可以帮你拆解计划。"),
    ]

    topic = TopicContinuityDetector().detect("那个 deadline 怎么安排？", recent)
    rewrite = QueryRewriter().rewrite("那个 deadline 怎么安排？", topic)

    assert topic.relation in {"CONTINUE", "AMBIGUOUS"}
    assert rewrite.changed is True
    assert "COMP702" in rewrite.rewritten_query


@pytest.mark.asyncio
async def test_query_rewriter_uses_llm_for_reference_resolution() -> None:
    from app.memory.query_rewrite import QueryRewriter

    class FakeRewriteLlm:
        async def chat(self, request):
            return ChatResponse(
                content=json.dumps(
                    {
                        "original_query": "那个 deadline 怎么安排？",
                        "rewritten_query": "COMP702 coursework 的 10 月 10 日 deadline 应该怎么安排？",
                        "changed": True,
                        "reason": "Resolved 那个 deadline from recent conversation.",
                    }
                ),
                model="fake-memory",
            )

    recent = [
        ChatTurn(role="user", content="我正在处理 COMP702 coursework，deadline 是 10 月 10 日。"),
        ChatTurn(role="assistant", content="我可以帮你拆解计划。"),
    ]
    topic = TopicContinuityDetector().detect("那个 deadline 怎么安排？", recent)
    rewrite = await QueryRewriter(llm=FakeRewriteLlm()).rewrite_async(
        query="那个 deadline 怎么安排？",
        topic=topic,
        recent_messages=recent,
    )

    assert rewrite.changed is True
    assert rewrite.rewritten_query == "COMP702 coursework 的 10 月 10 日 deadline 应该怎么安排？"


def test_token_counter_and_retention_policy_are_not_character_only() -> None:
    text = "我喜欢周二晚上健身，然后复习 COMP702。"

    assert 3 <= TokenCounter().count_text(text) < len(text)
    sensitivity = classify_memory_sensitivity("My passport number is private.")
    policy = retention_policy_for("My passport number is private.")
    assert sensitivity == "restricted"
    assert policy.retain is False
    assert policy.requires_user_confirmation is True


@pytest.mark.asyncio
async def test_memory_manager_updates_short_term_memory() -> None:
    store = InMemoryShortTermMemoryStore()
    manager = MemoryManager(short_term_store=store)
    request = ChatRequest(user_id="user_1", conversation_id="conv_1", message="我每月预算 £900。")
    router_output = RouterOutput(primary_intent="finance", confidence=0.9)

    await manager.update_after_response(
        request=request,
        conversation_id="conv_1",
        response_text="我会记住这个预算上下文。",
        router_output=router_output,
    )
    recent = await store.load_recent("conv_1", limit=5)

    assert [message.role for message in recent] == ["user", "assistant"]
    assert "£900" in recent[0].content


@pytest.mark.asyncio
async def test_memory_manager_compresses_short_term_queue_and_writes_long_term_summary() -> None:
    class FakeCompressor:
        async def compress(self, messages):
            return "用户正在讨论东京旅行，酒店偏好是安静、靠近地铁。"

    class FakeLongTermRepository:
        def __init__(self) -> None:
            self.memories = []

        async def add_memory(self, **kwargs):
            self.memories.append(kwargs)
            return f"memory_{len(self.memories)}"

    store = InMemoryShortTermMemoryStore()
    repository = FakeLongTermRepository()
    manager = MemoryManager(
        short_term_store=store,
        long_term_repository=repository,  # type: ignore[arg-type]
        compressor=FakeCompressor(),  # type: ignore[arg-type]
        max_context_tokens=20,
    )
    request = ChatRequest(
        user_id="user_1",
        conversation_id="conv_1",
        message="东京旅行酒店偏好：我想住安静、靠近地铁的地方。" * 4,
    )

    await manager.update_after_response(
        request=request,
        conversation_id="conv_1",
        response_text="我会用这个偏好规划后续东京行程。" * 4,
        router_output=RouterOutput(primary_intent="travel", confidence=0.9),
    )

    all_messages = await store.load_all("conv_1")
    assert all_messages[0].role == "system"
    assert all_messages[0].content.startswith("短期记忆压缩摘要")
    assert repository.memories[0]["memory_type"] == "conversation_summary"
    assert repository.memories[0]["source_type"] == "short_term_compression"
    assert repository.memories[0]["access_policy"]["confirmed"] is True


@pytest.mark.asyncio
async def test_memory_candidate_service_pends_confirms_rejects_and_deletes() -> None:
    class FakeLongTermRepository:
        def __init__(self) -> None:
            self.pending: list[tuple[str, dict]] = []
            self.confirmed: list[tuple[str, dict]] = []
            self.rejected: list[str] = []
            self.deleted: list[str] = []

        async def add_memory_candidate(self, **kwargs):
            memory_id = f"pending_{len(self.pending) + 1}"
            self.pending.append((memory_id, kwargs))
            return memory_id

        async def add_memory(self, **kwargs):
            memory_id = f"confirmed_{len(self.confirmed) + 1}"
            self.confirmed.append((memory_id, kwargs))
            return memory_id

        async def confirm_memory_candidates(self, *, user_id, memory_ids):
            return memory_ids

        async def reject_memory_candidates(self, *, user_id, memory_ids):
            self.rejected.extend(memory_ids)
            return memory_ids

        async def delete_memories(self, *, user_id, memory_ids):
            self.deleted.extend(memory_ids)
            return memory_ids

    repository = FakeLongTermRepository()
    service = MemoryCandidateService(repository)  # type: ignore[arg-type]

    pending = await service.persist_candidates(
        user_id="user_1",
        requested=True,
        candidates=[
            MemoryCandidateInput(
                namespace="finance",
                content="Finance budget context: monthly budget GBP 900.",
                source_type="finance_agent",
            )
        ],
    )
    confirmed = await service.persist_candidates(
        user_id="user_1",
        requested=True,
        confirmed=True,
        candidates=[
            MemoryCandidateInput(
                namespace="fitness",
                content="Fitness goal preference: strength training.",
                source_type="fitness_agent",
                confirmed=True,
            )
        ],
    )
    rejected = await service.reject(user_id="user_1", memory_ids=pending.pending_memory_ids)
    deleted = await service.delete(user_id="user_1", memory_ids=confirmed.confirmed_memory_ids)

    assert pending.status == "pending_confirmation"
    assert repository.pending[0][1]["namespace"] == "finance"
    assert confirmed.status == "confirmed"
    assert repository.confirmed[0][1]["memory_type"] == "user_preference"
    assert rejected.memory_ids == ["pending_1"]
    assert deleted.memory_ids == ["confirmed_1"]


@pytest.mark.asyncio
async def test_memory_candidate_service_skips_restricted_content() -> None:
    class FakeLongTermRepository:
        async def add_memory_candidate(self, **kwargs):
            raise AssertionError("restricted content should not be persisted")

        async def add_memory(self, **kwargs):
            raise AssertionError("restricted content should not be persisted")

    result = await MemoryCandidateService(FakeLongTermRepository()).persist_candidates(  # type: ignore[arg-type]
        user_id="user_1",
        requested=True,
        candidates=[MemoryCandidateInput(namespace="shared", content="My passport number is private.")],
    )

    assert result.status == "skipped"
    assert result.skipped
