import pytest

from app.memory.continuity import TopicContinuityDetector
from app.memory.manager import MemoryManager
from app.memory.policy import classify_memory_sensitivity, retention_policy_for
from app.memory.query_rewrite import QueryRewriter
from app.memory.router import MemoryRouter
from app.memory.short_term import InMemoryShortTermMemoryStore
from app.memory.token_counter import TokenCounter
from app.schemas.chat import ChatRequest, ChatTurn
from app.schemas.router import RouterOutput


def test_memory_router_detects_long_term_reference() -> None:
    router_output = RouterOutput(primary_intent="travel", confidence=0.8)

    decision = MemoryRouter().route("我上次去东京住的是哪家酒店？", router_output)

    assert decision.need_long_term_memory is True
    assert "travel" in decision.namespaces
    assert "finance" in decision.namespaces


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
