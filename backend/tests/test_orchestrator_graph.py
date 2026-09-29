import pytest

from app.agents.orchestrator.graph import build_orchestrator_graph
from app.agents.orchestrator.state_store import ConversationStateStore
from app.agents.orchestrator.workers import (
    WorkerAgentSpec,
    WorkerContext,
    WorkerRegistry,
    WorkerRunResult,
)
from app.schemas.chat import AgentArtifact, ChatRequest
from app.schemas.router import RouterOutput


class FakeRouter:
    def __init__(self) -> None:
        self.async_calls = 0

    async def route_async(self, message, uploaded_file_ids=None, agent_inputs=None):
        self.async_calls += 1
        return RouterOutput(primary_intent="travel", confidence=0.91)


class FakeMemoryManager:
    async def build_context(self, request, conversation_id, router_output):
        from app.schemas.memory import MemoryContext, MemoryRoutingDecision, QueryRewriteResult, TopicContinuityResult

        return MemoryContext(
            routing=MemoryRoutingDecision(
                need_short_term_memory=True,
                need_long_term_memory=False,
                namespaces=["travel"],
                memory_source=["short_term"],
                reason="test",
            ),
            topic=TopicContinuityResult(relation="CONTINUE", score=0.9, topic_summary="travel"),
            query_rewrite=QueryRewriteResult(original_query=request.message, rewritten_query=request.message, changed=False),
            recent_messages=[],
            long_term_memories=[],
        )

    async def update_after_response(self, **kwargs):
        return None


class FakeTravelWorker:
    spec = WorkerAgentSpec(
        intent="travel",
        input_key="travel",
        input_schema="TravelPlanRequest",
        output_artifact_kind="travel_plan",
        required_tools=["weather.lookup"],
        memory_namespaces=["travel"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        assert context.memory_context is not None
        assert context.memory_context.routing.namespaces == ["travel"]
        return WorkerRunResult(
            final_response="graph travel worker completed",
            artifacts=[AgentArtifact(name="Travel Plan", kind="travel_plan", payload={"source": "fake"})],
            trace_events=[{"name": "worker.completed", "payload": {"agent": "travel"}}],
        )


@pytest.mark.asyncio
async def test_orchestrator_graph_is_main_async_dispatch_path() -> None:
    router = FakeRouter()
    graph = build_orchestrator_graph(
        router=router,
        memory_manager=FakeMemoryManager(),
        worker_registry=WorkerRegistry(workers=[FakeTravelWorker()]),
    )

    result = await graph.ainvoke(
        {
            "request": ChatRequest(
                user_id="user_1",
                message="我要去曼彻斯特旅行",
                agent_inputs={"travel": {"origin": "London", "destination": "Manchester"}},
            )
        }
    )

    response = result["response"]
    assert router.async_calls == 1
    assert response.router.primary_intent == "travel"
    assert response.final_response == "graph travel worker completed"
    assert response.artifacts[0].kind == "travel_plan"
    assert response.latency_summary is not None
    assert response.latency_summary.span_count >= 4
    assert response.latency_summary.persisted is False
    assert {"router", "memory", "worker"}.issubset(response.latency_summary.by_type)

    trace_names = [event.name for event in response.trace]
    assert trace_names == [
        "chat.received",
        "memory.context_prepared",
        "router.completed",
        "orchestrator.dispatch",
        "worker.selected",
        "worker.completed",
        "memory.updated",
    ]
    selected = next(event for event in response.trace if event.name == "worker.selected")
    assert selected.payload["input_schema"] == "TravelPlanRequest"
    assert selected.payload["required_tools"] == ["weather.lookup"]


@pytest.mark.asyncio
async def test_orchestrator_state_is_scoped_by_conversation_id() -> None:
    class StatefulWorker:
        spec = WorkerAgentSpec(
            intent="travel",
            input_key="travel",
            input_schema="TravelPlanRequest",
            output_artifact_kind="travel_plan",
        )

        async def run(self, context: WorkerContext) -> WorkerRunResult:
            assert context.agent_state is not None
            assert context.agent_state.agent_name == "travel"
            return WorkerRunResult(
                final_response=f"handled {context.request.message}",
                artifacts=[
                    AgentArtifact(
                        name="Travel Plan",
                        kind="travel_plan",
                        payload={"message": context.request.message},
                    )
                ],
            )

    state_store = ConversationStateStore()
    graph = build_orchestrator_graph(
        router=FakeRouter(),
        memory_manager=FakeMemoryManager(),
        worker_registry=WorkerRegistry(workers=[StatefulWorker()]),
        state_store=state_store,
    )

    first = await graph.ainvoke(
        {"request": ChatRequest(user_id="user_1", conversation_id="conv_a", message="first request")}
    )
    second = await graph.ainvoke(
        {"request": ChatRequest(user_id="user_1", conversation_id="conv_a", message="second request")}
    )
    isolated = await graph.ainvoke(
        {"request": ChatRequest(user_id="user_1", conversation_id="conv_b", message="other conversation")}
    )

    assert first["response"].conversation_id == "conv_a"
    assert len([artifact for artifact in first["response"].artifacts if artifact.kind == "travel_plan"]) == 1
    assert len([artifact for artifact in second["response"].artifacts if artifact.kind == "travel_plan"]) == 2
    assert len([artifact for artifact in isolated["response"].artifacts if artifact.kind == "travel_plan"]) == 1
    received = next(event for event in second["response"].trace if event.name == "chat.received")
    assert received.payload["state_artifact_count"] == 1

    conv_a_state = state_store.get_or_create(user_id="user_1", conversation_id="conv_a")
    conv_b_state = state_store.get_or_create(user_id="user_1", conversation_id="conv_b")
    assert conv_a_state.agent_states["travel"].run_count == 2
    assert len(conv_a_state.agent_states["travel"].artifacts) == 2
    assert conv_a_state.agent_states["travel"].last_response == "handled second request"
    assert conv_b_state.agent_states["travel"].run_count == 1
    assert len(conv_b_state.agent_states["travel"].artifacts) == 1
