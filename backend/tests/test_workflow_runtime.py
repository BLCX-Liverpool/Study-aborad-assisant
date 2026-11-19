from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.messaging.topology import QUEUE_SPECS, ROUTING_KEY_BY_AGENT
from app.outbox.publisher import OutboxPublisher
from app.schemas.messages import AgentStepEvent, AgentTaskCommand, WorkflowPrepareCommand
from app.schemas.router import RouterOutput, StructuredIntent
from app.schemas.workflow import ChatV2Request
from app.workers.task_handler import is_retryable_error
from app.workflows.planner import _execution_plan
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


def test_retry_classification_separates_transient_and_permanent_errors() -> None:
    assert is_retryable_error(TimeoutError()) is True
    assert is_retryable_error(httpx.ConnectError("network")) is True
    assert is_retryable_error(PermissionError()) is False
    assert is_retryable_error(LookupError()) is False


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
