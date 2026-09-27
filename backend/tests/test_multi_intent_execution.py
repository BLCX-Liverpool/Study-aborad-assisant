import pytest
import asyncio
from time import perf_counter

from app.agents.orchestrator.graph import build_orchestrator_graph
from app.agents.orchestrator.multi_intent_executor import MultiIntentExecutionPlanner
from app.agents.orchestrator.repository import RouterObservationRepository
from app.agents.orchestrator.service import StudyAbroadOrchestrator
from app.agents.orchestrator.workers import WorkerAgentSpec, WorkerContext, WorkerRegistry, WorkerRunResult
from app.schemas.chat import AgentArtifact
from app.schemas.chat import ChatRequest
from app.schemas.execution import MultiIntentExecutionRequest
from app.schemas.router import RouterOutput, StructuredIntent


def test_multi_intent_execution_planner_converts_calendar_to_email_reminder() -> None:
    plan = MultiIntentExecutionPlanner().plan(
        MultiIntentExecutionRequest(
            user_id="user_1",
            message="帮我查一下明天下午有没有会议，如果没有就安排一个项目讨论会。",
            structured_intents=[
                StructuredIntent(
                    name="calendar.query_availability",
                    agent_intent="task_planning",
                    slots={"date": "明天", "time_range": "下午"},
                    confidence=0.8,
                ),
                StructuredIntent(
                    name="calendar.create_event",
                    agent_intent="task_planning",
                    slots={"event_name": "项目讨论会"},
                    condition="下午没有其他会议",
                    depends_on=[0],
                    confidence=0.8,
                ),
            ],
        )
    )

    assert plan.planner_output is not None
    assert plan.planner_output.tasks[0].source_type == "multi_intent_calendar"
    assert plan.email_reminder_drafts[0].channel == "email"
    assert plan.steps[1].depends_on == [0]


@pytest.mark.asyncio
async def test_orchestrator_returns_multi_intent_execution_artifact() -> None:
    response = await StudyAbroadOrchestrator().handle_chat(
        ChatRequest(
            user_id="user_1",
            message="帮我查一下明天下午有没有会议，如果没有就安排一个项目讨论会。",
        )
    )

    assert response.router.primary_intent == "task_planning"
    artifact = next(item for item in response.artifacts if item.kind == "multi_intent_execution")
    assert artifact.payload["email_reminder_drafts"][0]["channel"] == "email"
    assert "邮件提醒" in response.next_actions[0]


@pytest.mark.asyncio
async def test_orchestrator_executes_multi_worker_plan_with_artifact_handoff() -> None:
    class FakeRouter:
        async def route_async(self, message, uploaded_file_ids=None, agent_inputs=None):
            return RouterOutput(
                primary_intent="travel",
                confidence=0.86,
                structured_intents=[
                    StructuredIntent(
                        name="travel.plan",
                        agent_intent="travel",
                        slots={"origin": "London", "destination": "Manchester"},
                        confidence=0.86,
                    ),
                    StructuredIntent(
                        name="finance.review_budget",
                        agent_intent="finance",
                        slots={"currency": "GBP"},
                        depends_on=[0],
                        confidence=0.8,
                    ),
                ],
            )

    class FakeMemoryManager:
        async def build_context(self, request, conversation_id, router_output):
            from app.schemas.memory import MemoryContext, MemoryRoutingDecision, QueryRewriteResult, TopicContinuityResult

            return MemoryContext(
                routing=MemoryRoutingDecision(
                    need_short_term_memory=False,
                    need_long_term_memory=False,
                    namespaces=[],
                    memory_source=[],
                    reason="test",
                ),
                topic=TopicContinuityResult(relation="NEW_TOPIC", score=0.1, topic_summary="multi"),
                query_rewrite=QueryRewriteResult(
                    original_query=request.message,
                    rewritten_query=request.message,
                    changed=False,
                ),
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
        )

        async def run(self, context: WorkerContext) -> WorkerRunResult:
            assert context.execution_step is not None
            assert context.request.agent_inputs["travel"]["destination"] == "Manchester"
            return WorkerRunResult(
                final_response="travel completed",
                artifacts=[
                    AgentArtifact(
                        name="Travel Plan",
                        kind="travel_plan",
                        payload={"destination": "Manchester"},
                    )
                ],
                trace_events=[{"name": "worker.completed", "payload": {"agent": "travel"}}],
            )

    class FakeFinanceWorker:
        spec = WorkerAgentSpec(
            intent="finance",
            input_key="finance",
            input_schema="FinancePlanRequest",
            output_artifact_kind="finance_plan",
        )

        async def run(self, context: WorkerContext) -> WorkerRunResult:
            assert any(artifact.kind == "travel_plan" for artifact in context.existing_artifacts)
            return WorkerRunResult(
                final_response="finance completed",
                artifacts=[AgentArtifact(name="Finance Plan", kind="finance_plan", payload={"currency": "GBP"})],
                trace_events=[{"name": "worker.completed", "payload": {"agent": "finance"}}],
            )

    graph = build_orchestrator_graph(
        router=FakeRouter(),
        memory_manager=FakeMemoryManager(),
        worker_registry=WorkerRegistry(workers=[FakeTravelWorker(), FakeFinanceWorker()]),
    )

    result = await graph.ainvoke(
        {"request": ChatRequest(user_id="user_1", message="帮我规划旅行并估算预算")}
    )

    response = result["response"]
    assert "travel completed" in response.final_response
    assert "finance completed" in response.final_response
    assert [artifact.kind for artifact in response.artifacts].count("travel_plan") == 1
    assert [artifact.kind for artifact in response.artifacts].count("finance_plan") == 1
    execution_artifact = next(
        artifact for artifact in response.artifacts if artifact.kind == "multi_worker_execution_result"
    )
    assert [step["status"] for step in execution_artifact.payload["steps"]] == ["completed", "completed"]
    assert response.latency_summary is not None
    assert any(item.span_name.startswith("worker.travel") for item in response.latency_summary.slowest_spans)


@pytest.mark.asyncio
async def test_orchestrator_runs_independent_worker_steps_in_parallel() -> None:
    class FakeRouter:
        async def route_async(self, message, uploaded_file_ids=None, agent_inputs=None):
            return RouterOutput(
                primary_intent="travel",
                confidence=0.9,
                structured_intents=[
                    StructuredIntent(
                        name="travel.plan",
                        agent_intent="travel",
                        slots={"origin": "London", "destination": "Manchester"},
                        confidence=0.9,
                    ),
                    StructuredIntent(
                        name="finance.review_budget",
                        agent_intent="finance",
                        slots={"currency": "GBP", "monthly_income": 1000},
                        confidence=0.9,
                    ),
                ],
            )

    class FakeMemoryManager:
        async def build_context(self, request, conversation_id, router_output):
            from app.schemas.memory import MemoryContext, MemoryRoutingDecision, QueryRewriteResult, TopicContinuityResult

            return MemoryContext(
                routing=MemoryRoutingDecision(
                    need_short_term_memory=False,
                    need_long_term_memory=False,
                    namespaces=[],
                    memory_source=[],
                    reason="test",
                ),
                topic=TopicContinuityResult(relation="NEW_TOPIC", score=0.1, topic_summary="parallel"),
                query_rewrite=QueryRewriteResult(
                    original_query=request.message,
                    rewritten_query=request.message,
                    changed=False,
                ),
                recent_messages=[],
                long_term_memories=[],
            )

        async def update_after_response(self, **kwargs):
            return None

    starts = {}

    class SlowTravelWorker:
        spec = WorkerAgentSpec(
            intent="travel",
            input_key="travel",
            input_schema="TravelPlanRequest",
            output_artifact_kind="travel_plan",
        )

        async def run(self, context: WorkerContext) -> WorkerRunResult:
            starts["travel"] = perf_counter()
            await asyncio.sleep(0.05)
            return WorkerRunResult(
                final_response="travel done",
                artifacts=[AgentArtifact(name="Travel Plan", kind="travel_plan", payload={})],
            )

    class SlowFinanceWorker:
        spec = WorkerAgentSpec(
            intent="finance",
            input_key="finance",
            input_schema="FinancePlanRequest",
            output_artifact_kind="finance_plan",
        )

        async def run(self, context: WorkerContext) -> WorkerRunResult:
            starts["finance"] = perf_counter()
            await asyncio.sleep(0.05)
            return WorkerRunResult(
                final_response="finance done",
                artifacts=[AgentArtifact(name="Finance Plan", kind="finance_plan", payload={})],
            )

    graph = build_orchestrator_graph(
        router=FakeRouter(),
        memory_manager=FakeMemoryManager(),
        worker_registry=WorkerRegistry(workers=[SlowTravelWorker(), SlowFinanceWorker()]),
    )

    started = perf_counter()
    result = await graph.ainvoke({"request": ChatRequest(user_id="user_1", message="旅行和预算都规划一下")})
    elapsed = perf_counter() - started

    response = result["response"]
    assert "travel done" in response.final_response
    assert "finance done" in response.final_response
    assert abs(starts["travel"] - starts["finance"]) < 0.08
    assert elapsed < 0.13
    trace_names = [event.name for event in response.trace]
    assert "orchestrator.worker_layer_started" in trace_names
    execution_artifact = next(
        artifact for artifact in response.artifacts if artifact.kind == "multi_worker_execution_result"
    )
    assert [step["status"] for step in execution_artifact.payload["steps"]] == ["completed", "completed"]


@pytest.mark.asyncio
async def test_router_observation_repository_persists_router_metadata() -> None:
    class FakeSession:
        def __init__(self):
            self.added = []
            self.flushed = False
            self.committed = False

        def add(self, value):
            self.added.append(value)

        async def flush(self):
            self.flushed = True

        async def commit(self):
            self.committed = True

    session = FakeSession()
    router_output = RouterOutput(
        primary_intent="task_planning",
        confidence=0.8,
        structured_intents=[
            StructuredIntent(
                name="calendar.query_availability",
                agent_intent="task_planning",
                confidence=0.8,
            )
        ],
    )

    observation_id = await RouterObservationRepository(session).record(
        user_id="user_1",
        conversation_id="conv_1",
        trace_id="trace_1",
        message="安排会议",
        router_output=router_output,
    )

    assert observation_id
    assert session.flushed is True
    assert session.committed is True
    assert session.added[0].primary_intent == "task_planning"
    assert session.added[0].structured_intents_json[0]["name"] == "calendar.query_availability"
