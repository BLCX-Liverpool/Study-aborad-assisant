import pytest

from app.agents.orchestrator.graph import build_orchestrator_graph
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
