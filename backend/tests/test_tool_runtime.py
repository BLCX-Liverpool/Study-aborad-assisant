import asyncio

import httpx
import pytest
from pydantic import BaseModel, Field

from app.core.permissions import PermissionLevel
from app.agents.orchestrator.workers import TravelWorker, WorkerContext
from app.agents.travel.input_extractor import TravelInputExtraction
from app.schemas.chat import ChatRequest
from app.tools.decision import AgentToolDecision, ToolCallDraft, ToolDecisionAgent
from app.tools.executor import ToolExecutor
from app.tools.inputs import MapsDirectionsInput
from app.tools.models import ToolCallRequest, ToolSpec
from app.tools.registry import ToolRegistry
from app.tools.runtime import AgentToolRuntime


class QueryInput(BaseModel):
    query: str = Field(min_length=1)


class FakeDecisionAgent:
    def __init__(self, calls):
        self.calls = calls
        self.rounds = 0

    async def decide(self, **kwargs):
        self.rounds += 1
        if self.rounds > 1:
            return AgentToolDecision(action="respond", reason="done")
        return AgentToolDecision(action="call_tools", reason="needed", tool_calls=self.calls)


class UnavailableLlm:
    async def chat(self, request):
        raise RuntimeError("LLM unavailable")


@pytest.mark.asyncio
async def test_executor_validates_arguments_before_handler() -> None:
    called = False

    async def handler(arguments):
        nonlocal called
        called = True
        return arguments

    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="search", description="search", permission_level=PermissionLevel.SEARCH),
        handler,
        input_model=QueryInput,
    )

    result = await ToolExecutor(registry).run(ToolCallRequest(tool_name="search", arguments={}))

    assert result.success is False
    assert result.error_type == "ValidationError"
    assert result.attempts == 0
    assert called is False


@pytest.mark.asyncio
async def test_external_tool_retries_three_total_attempts_with_exponential_backoff() -> None:
    attempts = 0
    delays = []

    async def handler(arguments):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise httpx.ConnectError("temporary")
        return {"query": arguments["query"]}

    async def record_sleep(delay):
        delays.append(delay)

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="search",
            description="search",
            permission_level=PermissionLevel.SEARCH,
            external_api=True,
            max_attempts=3,
        ),
        handler,
        input_model=QueryInput,
    )

    result = await ToolExecutor(registry, sleep=record_sleep, jitter=lambda: 0.0).run(
        ToolCallRequest(tool_name="search", arguments={"query": "student visa"})
    )

    assert result.success is True
    assert result.attempts == 3
    assert delays == [0.5, 1.0]


@pytest.mark.asyncio
async def test_runtime_executes_independent_read_tools_in_parallel_and_filters_allowlist() -> None:
    active = 0
    max_active = 0

    async def handler(arguments):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1
        return arguments

    registry = ToolRegistry()
    for name in ("search.a", "search.b", "search.c", "not.allowed"):
        registry.register(
            ToolSpec(name=name, description=name, permission_level=PermissionLevel.SEARCH),
            handler,
            input_model=QueryInput,
        )
    calls = [
        ToolCallDraft(tool_name="search.a", arguments={"query": "a"}),
        ToolCallDraft(tool_name="search.b", arguments={"query": "b"}),
        ToolCallDraft(tool_name="search.c", arguments={"query": "c"}),
        ToolCallDraft(tool_name="not.allowed", arguments={"query": "x"}),
    ]
    runtime = AgentToolRuntime(
        agent_name="assignment",
        allowed_tools=["search.a", "search.b", "search.c"],
        request=ChatRequest(user_id="u1", message="research"),
        registry=registry,
        decision_agent=FakeDecisionAgent(calls),
        max_parallel_calls=3,
    )

    batch = await runtime.run({"topic": "research"})

    assert [result.tool_name for result in batch.results] == ["search.a", "search.b", "search.c"]
    assert max_active == 3


@pytest.mark.asyncio
async def test_runtime_uses_domain_fallback_without_explicit_tool_parameters() -> None:
    seen = []

    async def handler(arguments):
        seen.append(arguments)
        return {"base_currency": "USD", "quote_currency": "GBP", "rate": 0.79}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="finance.exchange_rate",
            description="rate",
            permission_level=PermissionLevel.READ,
        ),
        handler,
    )
    runtime = AgentToolRuntime(
        agent_name="finance",
        allowed_tools=["finance.exchange_rate"],
        request=ChatRequest(user_id="u1", message="convert my USD budget to GBP"),
        registry=registry,
        decision_agent=ToolDecisionAgent("finance", llm=UnavailableLlm()),
    )

    batch = await runtime.run({"currency": "USD", "target_currency": "GBP"})

    assert len(batch.results) == 1
    assert seen == [{"base_currency": "USD", "quote_currency": "GBP"}]


@pytest.mark.asyncio
async def test_side_effect_tool_requires_approval_and_idempotency_key() -> None:
    async def handler(arguments):
        return {"sent": True}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(name="email.send", description="send", permission_level=PermissionLevel.SEND),
        handler,
    )
    executor = ToolExecutor(registry)

    approval_result = await executor.run(ToolCallRequest(tool_name="email.send"))
    idempotency_result = await executor.run(ToolCallRequest(tool_name="email.send", approved=True))
    success_result = await executor.run(
        ToolCallRequest(tool_name="email.send", approved=True, idempotency_key="workflow:step:call")
    )

    assert approval_result.error_type == "ApprovalRequired"
    assert idempotency_result.error_type == "IdempotencyKeyRequired"
    assert success_result.success is True


@pytest.mark.asyncio
async def test_travel_worker_consumes_unified_tool_results_without_direct_provider_call() -> None:
    calls = 0

    async def directions(arguments):
        nonlocal calls
        calls += 1
        return {
            "provider_status": {
                "name": "travel.maps.directions",
                "capability": "travel_route_directions",
                "available": True,
                "status": "available",
                "permission_level": "SEARCH",
            },
            "routes": [
                {
                    "origin": arguments["origin"],
                    "destination": arguments["destination"],
                    "mode": arguments["mode"],
                    "estimated_minutes": 120,
                    "distance_km": 260.0,
                }
            ],
        }

    class InputExtractor:
        async def extract(self, **kwargs):
            return TravelInputExtraction(
                payload={
                    "origin": "Manchester",
                    "destination": "London",
                    "purpose": "city_trip",
                },
                confidence=1.0,
            )

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="travel.maps.directions",
            description="directions",
            permission_level=PermissionLevel.SEARCH,
        ),
        directions,
        input_model=MapsDirectionsInput,
    )
    decision = FakeDecisionAgent(
        [
            ToolCallDraft(
                tool_name="travel.maps.directions",
                arguments={
                    "origin": "Manchester",
                    "destination": "London",
                    "mode": "transit",
                },
            )
        ]
    )
    request = ChatRequest(user_id="u1", message="Plan my trip from Manchester to London")
    runtime = AgentToolRuntime(
        agent_name="travel",
        allowed_tools=["travel.maps.directions"],
        request=request,
        registry=registry,
        decision_agent=decision,
    )

    result = await TravelWorker(input_extractor=InputExtractor()).run(
        WorkerContext(request=request, tool_runtime=runtime)
    )

    assert calls == 1
    assert len(result.artifacts) == 1
    assert result.artifacts[0].payload["route_suggestions"][0]["source"] == "provider_verified"
