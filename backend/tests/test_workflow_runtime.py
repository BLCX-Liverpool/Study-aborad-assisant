from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.api.routes.chat_v2 import PrecomputedRouter
from app.messaging.topology import QUEUE_SPECS, ROUTING_KEY_BY_AGENT
from app.outbox.publisher import OutboxPublisher
from app.schemas.messages import AgentStepEvent, AgentTaskCommand, WorkflowPrepareCommand
from app.schemas.memory import MemoryContext, MemoryRoutingDecision, QueryRewriteResult, TopicContinuityResult
from app.schemas.router import RouterOutput, StructuredIntent
from app.schemas.workflow import ChatV2Request
from app.workers.task_handler import is_retryable_error
from app.workers.context_loader import WorkerContextLoader
from app.agents.orchestrator.workers import WorkerAgentSpec
from app.workflows.planner import DurableWorkflowPlanner, _execution_plan
from app.workflows.event_handler import WorkflowEventHandler
from app.workflows.runtime import WorkflowEventRuntime
from app.workflows.service import ExecutionPolicy
from app.workflows.state_machine import (
    InvalidStateTransition,
    StepStateMachine,
    StepStatus,
    WorkflowStateMachine,
    WorkflowStatus,
)


def test_workflow_and_step_state_machines_enforce_contract() -> None:
    assert WorkflowStateMachine.transition("created", "planning") == WorkflowStatus.PLANNING
    assert WorkflowStateMachine.transition("running", "waiting_input") == WorkflowStatus.WAITING_INPUT
    assert StepStateMachine.transition("pending", "queued") == StepStatus.QUEUED
    assert StepStateMachine.transition("running", "retry_wait") == StepStatus.RETRY_WAIT
    with pytest.raises(InvalidStateTransition):
        WorkflowStateMachine.transition("completed", "running")
    with pytest.raises(InvalidStateTransition):
        StepStateMachine.transition("completed", "queued")


def test_message_contract_rejects_unsupported_schema_versions() -> None:
    with pytest.raises(ValidationError):
        AgentTaskCommand(
            schema_version=999,
            workflow_id="wf",
            step_id="step",
            agent="assignment",
            trace_id="trace",
            input_ref="workflow-input:wf",
        )


def test_message_contract_keeps_artifacts_as_references() -> None:
    event = AgentStepEvent(
        message_type="agent.step.completed",
        workflow_id="wf",
        step_id="step",
        agent="travel",
        trace_id="trace",
        artifact_ids=["artifact_1"],
    )
    payload = event.model_dump(mode="json")
    assert payload["artifact_ids"] == ["artifact_1"]
    assert "artifact_payload" not in payload


def test_topology_covers_every_asynchronous_agent_route() -> None:
    bindings = {routing_key for spec in QUEUE_SPECS for routing_key in spec.routing_keys}
    assert set(ROUTING_KEY_BY_AGENT.values()).issubset(bindings)
    assert "workflow.prepare" in bindings
    assert "agent.step.*" in bindings


def test_execution_policy_preserves_sync_safety_and_rolls_out_long_tasks(monkeypatch) -> None:
    settings = SimpleNamespace(
        rabbitmq_workflow_enabled=True,
        async_intents=["assignment", "travel", "finance"],
        async_user_allowlist=[],
        async_rollout_percentage=100,
    )
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)
    policy = ExecutionPolicy()
    wellbeing = RouterOutput(primary_intent="wellbeing", confidence=1.0)
    assignment = RouterOutput(primary_intent="assignment", confidence=1.0, needs_file_parsing=True)
    request = ChatV2Request(user_id="user", message="help", execution_mode="auto")
    assert policy.choose(wellbeing, request) == "sync"
    assert policy.choose(assignment, request) == "async"
    forced_async = request.model_copy(update={"execution_mode": "async"})
    assert policy.choose(wellbeing, forced_async) == "sync"


def test_single_intent_plan_preserves_structured_slots() -> None:
    router = RouterOutput(
        primary_intent="travel",
        confidence=0.9,
        structured_intents=[
            StructuredIntent(
                name="travel.plan",
                agent_intent="travel",
                slots={"origin": "London", "destination": "Paris"},
                confidence=0.9,
            )
        ],
    )
    plan = _execution_plan(ChatV2Request(user_id="u", message="trip"), router)
    assert plan.steps[0].intent_name == "travel.plan"
    assert plan.steps[0].slots["destination"] == "Paris"


@pytest.mark.asyncio
async def test_precomputed_router_only_reuses_preflight_for_initial_route() -> None:
    preflight = RouterOutput(primary_intent="travel", confidence=0.8)
    rewritten = RouterOutput(primary_intent="assignment", confidence=0.95)

    class FallbackRouter:
        def __init__(self) -> None:
            self.messages = []

        async def route_async(self, message, **_kwargs):
            self.messages.append(message)
            return rewritten

    fallback = FallbackRouter()
    router = PrecomputedRouter(preflight, fallback=fallback)

    assert (await router.route_async("initial query")) is preflight
    assert (await router.route_async("rewritten query")) is rewritten
    assert fallback.messages == ["rewritten query"]


@pytest.mark.asyncio
async def test_durable_planner_reroutes_rewritten_query_before_building_steps(monkeypatch) -> None:
    preflight = RouterOutput(primary_intent="travel", confidence=0.8)
    rewritten = RouterOutput(
        primary_intent="assignment",
        confidence=0.95,
        structured_intents=[
            StructuredIntent(
                name="assignment.analyze",
                agent_intent="assignment",
                confidence=0.95,
            )
        ],
    )
    workflow = SimpleNamespace(
        id="workflow-1",
        status="created",
        conversation_id="conversation-1",
        input_json={
            "chat_request": ChatV2Request(
                user_id="user-1",
                message="那个 deadline 怎么安排？",
            ).model_dump(mode="json"),
            "router_output": preflight.model_dump(mode="json"),
        },
        plan_json=None,
        final_response=None,
    )

    class Repository:
        session = object()

        def __init__(self) -> None:
            self.created_steps = []

        async def get(self, workflow_id):
            assert workflow_id == workflow.id
            return workflow

        async def transition_workflow(self, target_workflow, target):
            target_workflow.status = target.value
            return True

        async def create_steps(self, workflow_id, steps):
            assert workflow_id == workflow.id
            self.created_steps = steps

        async def list_steps(self, workflow_id):
            assert workflow_id == workflow.id
            return [SimpleNamespace(status="pending")]

    class Router:
        def __init__(self) -> None:
            self.calls = []

        async def route_async(self, message, **kwargs):
            self.calls.append((message, kwargs))
            return rewritten

    class Memory:
        def __init__(self) -> None:
            self.rebuilt_with = None

        async def build_context(self, **_kwargs):
            return MemoryContext(
                routing=MemoryRoutingDecision(reason="test"),
                topic=TopicContinuityResult(relation="CONTINUE", score=0.9),
                query_rewrite=QueryRewriteResult(
                    original_query="那个 deadline 怎么安排？",
                    rewritten_query="COMP702 coursework 的 deadline 怎么安排？",
                    changed=True,
                ),
                prompt_context="user: COMP702 coursework 在 10 月 10 日截止",
            )

        async def rebuild_context_after_reroute(self, *, request, router_output, memory_context):
            self.rebuilt_with = router_output.primary_intent
            return memory_context.model_copy(
                update={
                    "routing": MemoryRoutingDecision(
                        need_short_term_memory=True,
                        need_long_term_memory=True,
                        memory_source=["short_term", "long_term"],
                        namespaces=["academic"],
                        reason="Rebuilt from the rewritten assignment route.",
                    )
                }
            )

    class WorkflowServiceStub:
        def __init__(self, _session) -> None:
            pass

        async def queue_ready_steps(self, target_workflow):
            assert target_workflow is workflow
            return []

    monkeypatch.setattr("app.workflows.planner.WorkflowService", WorkflowServiceStub)
    repository = Repository()
    router = Router()
    memory = Memory()

    await DurableWorkflowPlanner(repository, router=router, memory_manager=memory).prepare(workflow.id)

    assert router.calls[0][0] == "COMP702 coursework 的 deadline 怎么安排？"
    assert router.calls[0][1]["conversation_context"].startswith("user: COMP702")
    assert workflow.plan_json["router"]["primary_intent"] == "assignment"
    assert workflow.plan_json["memory_context"]["routing"]["namespaces"] == ["academic"]
    assert memory.rebuilt_with == "assignment"
    assert repository.created_steps[0]["agent_intent"] == "assignment"


@pytest.mark.asyncio
async def test_worker_context_loader_uses_rewritten_query() -> None:
    memory_context = MemoryContext(
        routing=MemoryRoutingDecision(reason="test"),
        topic=TopicContinuityResult(relation="CONTINUE", score=0.9),
        query_rewrite=QueryRewriteResult(
            original_query="那个计划继续做",
            rewritten_query="继续制定伦敦三日旅行计划",
            changed=True,
        ),
    )
    workflow = SimpleNamespace(
        id="workflow-1",
        trace_id="trace-1",
        input_json={
            "chat_request": ChatV2Request(
                user_id="user-1",
                conversation_id="conversation-1",
                message="那个计划继续做",
            ).model_dump(mode="json")
        },
        plan_json={"memory_context": memory_context.model_dump(mode="json")},
    )
    step = SimpleNamespace(
        id="step-1",
        step_key="0",
        intent_name="travel.plan",
        agent_intent="travel",
        input_json={"destination": "London"},
        result_summary=None,
    )

    class Repository:
        async def get(self, workflow_id):
            assert workflow_id == workflow.id
            return workflow

        async def get_step(self, step_id, *, workflow_id):
            assert step_id == step.id
            assert workflow_id == workflow.id
            return step

        async def list_artifacts(self, workflow_id, *, artifact_ids):
            assert workflow_id == workflow.id
            assert artifact_ids == []
            return []

    loader = WorkerContextLoader(object())  # type: ignore[arg-type]
    loader.repository = Repository()  # type: ignore[assignment]
    worker = SimpleNamespace(
        spec=WorkerAgentSpec(
            intent="travel",
            input_key="travel",
            input_schema="TravelPlanRequest",
        )
    )
    command = AgentTaskCommand(
        workflow_id=workflow.id,
        step_id=step.id,
        agent="travel",
        trace_id=workflow.trace_id,
        input_ref=f"workflow-input:{workflow.id}",
    )

    context, tool_results = await loader.load(command, worker)  # type: ignore[arg-type]

    assert context.request.message == "继续制定伦敦三日旅行计划"
    assert context.request.agent_inputs["travel"]["destination"] == "London"
    assert tool_results == []


def test_retry_classification_separates_transient_and_permanent_errors() -> None:
    assert is_retryable_error(TimeoutError()) is True
    assert is_retryable_error(httpx.ConnectError("network")) is True
    assert is_retryable_error(PermissionError()) is False
    assert is_retryable_error(LookupError()) is False


@pytest.mark.asyncio
async def test_workflow_event_runtime_wires_conversation_repository(monkeypatch) -> None:
    session = object()
    captured = {}

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class CapturingHandler:
        def __init__(self, handler_session, *, consumer_name, memory_manager) -> None:
            assert handler_session is session
            captured["consumer_name"] = consumer_name
            captured["memory_manager"] = memory_manager

        async def handle(self, event) -> None:
            captured["event"] = event

    event = SimpleNamespace(message_id="event-1")
    message = SimpleNamespace(type="agent.step.completed", body=b"{}")
    monkeypatch.setattr("app.workflows.runtime.get_session_factory", lambda: lambda: SessionContext())
    monkeypatch.setattr("app.workflows.runtime.get_redis", lambda: object())
    monkeypatch.setattr("app.workflows.runtime.deserialize_message", lambda *_args: event)
    monkeypatch.setattr("app.workflows.runtime.WorkflowEventHandler", CapturingHandler)

    await WorkflowEventRuntime().handle_message(message)

    memory_manager = captured["memory_manager"]
    assert memory_manager.conversation_repository is not None
    assert memory_manager.conversation_repository.session is session
    assert captured["event"] is event


@pytest.mark.asyncio
async def test_workflow_completion_defers_memory_commit_to_event_transaction() -> None:
    class Repository:
        async def list_steps(self, workflow_id):
            assert workflow_id == "workflow-1"
            return [SimpleNamespace(status="completed", result_summary="异步助手回复")]

        async def transition_workflow(self, workflow, target):
            workflow.status = target.value
            return True

        async def list_artifacts(self, workflow_id):
            assert workflow_id == "workflow-1"
            return []

    class MemoryManagerStub:
        def __init__(self) -> None:
            self.kwargs = None

        async def update_after_response(self, **kwargs) -> None:
            self.kwargs = kwargs

    class Dispatcher:
        async def dispatch(self, **_kwargs) -> None:
            return None

    memory_manager = MemoryManagerStub()
    handler = WorkflowEventHandler(object(), memory_manager=memory_manager)  # type: ignore[arg-type]
    handler.repository = Repository()  # type: ignore[assignment]
    handler.dispatcher = Dispatcher()  # type: ignore[assignment]
    workflow = SimpleNamespace(
        id="workflow-1",
        trace_id="trace-1",
        conversation_id="conversation-1",
        status="running",
        final_response=None,
        input_json={
            "chat_request": ChatV2Request(
                user_id="user-1",
                conversation_id="conversation-1",
                message="异步用户消息",
            ).model_dump(mode="json")
        },
        plan_json={
            "router": RouterOutput(
                primary_intent="general_chat",
                confidence=0.9,
            ).model_dump(mode="json")
        },
    )

    await handler._finalize_if_ready(workflow)

    assert workflow.status == "completed"
    assert memory_manager.kwargs is not None
    assert memory_manager.kwargs["conversation_id"] == "conversation-1"
    assert memory_manager.kwargs["response_text"] == "异步助手回复"
    assert memory_manager.kwargs["commit"] is False


@pytest.mark.asyncio
async def test_outbox_recovers_when_publish_confirmation_is_lost(monkeypatch) -> None:
    event = SimpleNamespace(
        id="outbox-message",
        routing_key="workflow.prepare",
        payload_json={"message_id": "outbox-message"},
        headers_json={},
        attempt_count=0,
    )

    class Repository:
        def __init__(self) -> None:
            self.failed = 0
            self.published = 0

        async def claim_batch(self, *, limit: int):
            assert limit == 10
            event.attempt_count += 1
            return [event]

        async def mark_failed(self, *_args, **_kwargs) -> None:
            self.failed += 1

        async def mark_published(self, *_args, **_kwargs) -> None:
            self.published += 1

    class Publisher:
        def __init__(self) -> None:
            self.calls = 0

        async def publish(self, **_kwargs) -> None:
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("confirm was not received")

    monkeypatch.setattr(
        "app.outbox.publisher.get_settings",
        lambda: SimpleNamespace(workflow_outbox_batch_size=10),
    )
    repository = Repository()
    publisher = Publisher()
    outbox = OutboxPublisher(repository, publisher)

    assert await outbox.publish_once() == 0
    assert await outbox.publish_once() == 1
    assert repository.failed == 1
    assert repository.published == 1
    assert publisher.calls == 2
