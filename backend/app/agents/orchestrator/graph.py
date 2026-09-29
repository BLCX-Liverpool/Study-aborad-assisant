from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, TypedDict

from app.agents.orchestrator.multi_intent_executor import MultiIntentExecutionPlanner
from app.agents.orchestrator.repository import AgentRunRecorder, RouterObservationRepository, TraceSpanRepository
from app.agents.orchestrator.state import AgentState
from app.agents.orchestrator.state_store import ConversationStateStore, default_conversation_state_store
from app.agents.orchestrator.workers import (
    WorkerContext,
    WorkerRegistry,
    WorkerRunResult,
    not_implemented_result,
)
from app.agents.router.service import IntentRouter
from app.core.tracing import capture_latency_span, summarize_latency_spans
from app.memory.manager import MemoryManager
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.execution import ExecutionStep, MultiIntentExecutionPlan, MultiIntentExecutionRequest
from app.schemas.router import Intent, RouterOutput
from app.tools.executor import ToolExecutor
from app.tools.models import ToolCallRequest, ToolCallResult
from app.tools.registry import ToolRegistry, build_default_tool_registry


class OrchestratorGraphState(TypedDict, total=False):
    request: ChatRequest
    agent_state: AgentState
    router_output: RouterOutput
    worker_result: WorkerRunResult
    execution_plan: MultiIntentExecutionPlan
    response: ChatResponse


@dataclass
class WorkerStepExecutionResult:
    step: ExecutionStep
    worker_result: WorkerRunResult
    worker_key: tuple[str, str] | None
    tool_results: list[ToolCallResult]
    trace_events: list[dict[str, Any]]


def build_orchestrator_graph(
    *,
    router: IntentRouter | None = None,
    memory_manager: MemoryManager | None = None,
    worker_registry: WorkerRegistry | None = None,
    tool_registry: ToolRegistry | None = None,
    recorder: AgentRunRecorder | None = None,
    router_observations: RouterObservationRepository | None = None,
    trace_spans: TraceSpanRepository | None = None,
    state_store: ConversationStateStore | None = None,
):
    """Build the production LangGraph orchestrator for the `/api/chat` path."""

    try:
        from langgraph.graph import END, StateGraph
    except ImportError as exc:
        raise RuntimeError("langgraph is required to build the orchestrator graph.") from exc

    runtime = OrchestratorGraphRuntime(
        router=router or IntentRouter(),
        memory_manager=memory_manager or MemoryManager(),
        worker_registry=worker_registry or WorkerRegistry(),
        tool_registry=tool_registry or build_default_tool_registry(),
        recorder=recorder,
        router_observations=router_observations,
        trace_spans=trace_spans,
        state_store=state_store or default_conversation_state_store,
    )

    graph = StateGraph(OrchestratorGraphState)
    graph.add_node("initialize", runtime.initialize)
    graph.add_node("route", runtime.route)
    graph.add_node("memory", runtime.memory)
    graph.add_node("record_router_observation", runtime.record_router_observation)
    graph.add_node("prepare_multi_intent", runtime.prepare_multi_intent)
    graph.add_node("dispatch_worker", runtime.dispatch_worker)
    graph.add_node("finalize_response", runtime.finalize_response)
    graph.add_node("persist_run", runtime.persist_run)
    graph.add_node("update_memory", runtime.update_memory)
    graph.add_node("persist_spans", runtime.persist_spans)
    graph.add_node("build_response", runtime.build_response)

    graph.set_entry_point("initialize")
    graph.add_edge("initialize", "route")
    graph.add_edge("route", "memory")
    graph.add_edge("memory", "record_router_observation")
    graph.add_edge("record_router_observation", "prepare_multi_intent")
    graph.add_edge("prepare_multi_intent", "dispatch_worker")
    graph.add_edge("dispatch_worker", "finalize_response")
    graph.add_edge("finalize_response", "persist_run")
    graph.add_edge("persist_run", "update_memory")
    graph.add_edge("update_memory", "persist_spans")
    graph.add_edge("persist_spans", "build_response")
    graph.add_edge("build_response", END)
    return graph.compile()


class OrchestratorGraphRuntime:
    def __init__(
        self,
        *,
        router: IntentRouter,
        memory_manager: MemoryManager,
        worker_registry: WorkerRegistry,
        tool_registry: ToolRegistry,
        recorder: AgentRunRecorder | None,
        router_observations: RouterObservationRepository | None,
        trace_spans: TraceSpanRepository | None,
        state_store: ConversationStateStore,
    ) -> None:
        self.router = router
        self.memory_manager = memory_manager
        self.worker_registry = worker_registry
        self.tool_registry = tool_registry
        self.recorder = recorder
        self.router_observations = router_observations
        self.trace_spans = trace_spans
        self.state_store = state_store

    async def initialize(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        request = graph_state["request"]
        state = self.state_store.get_or_create(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
        )
        state.prepare_for_request(request)
        request = request.model_copy(update={"conversation_id": state.conversation_id})
        state.add_trace(
            "chat.received",
            {
                "conversation_id": state.conversation_id,
                "uploaded_file_ids": request.uploaded_file_ids,
                "state_message_count": len(state.messages),
                "state_artifact_count": len(state.artifacts),
            },
        )
        return {**graph_state, "request": request, "agent_state": state}

    async def route(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        request = graph_state["request"]
        state = graph_state["agent_state"]
        async with self._span(
            state,
            span_name="router.initial_route",
            span_type="router",
            input_json={
                "message_length": len(request.message),
                "uploaded_file_count": len(request.uploaded_file_ids),
                "agent_input_keys": sorted(request.agent_inputs.keys()),
            },
        ) as span_output:
            router_output = await self.router.route_async(
                request.message,
                uploaded_file_ids=request.uploaded_file_ids,
                agent_inputs=request.agent_inputs,
            )
            span_output["primary_intent"] = router_output.primary_intent
            span_output["confidence"] = router_output.confidence
        state.router_output = router_output
        state.current_agent = router_output.primary_intent
        return {**graph_state, "agent_state": state, "router_output": router_output}

    async def memory(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        request = graph_state["request"]
        state = graph_state["agent_state"]
        router_output = graph_state["router_output"]
        async with self._span(
            state,
            span_name="memory.build_context",
            span_type="memory",
            input_json={"conversation_id": state.conversation_id, "primary_intent": router_output.primary_intent},
        ) as span_output:
            memory_context = await self.memory_manager.build_context(
                request=request,
                conversation_id=state.conversation_id,
                router_output=router_output,
            )
            span_output["memory_source"] = memory_context.routing.memory_source
            span_output["long_term_count"] = len(memory_context.long_term_memories)
            span_output["memory_ids"] = [
                memory.id for memory in memory_context.long_term_memories if memory.id
            ]
            span_output["query_rewritten"] = memory_context.query_rewrite.changed
        state.memory_context = memory_context
        state.add_trace(
            "memory.context_prepared",
            {
                "source": memory_context.routing.memory_source,
                "namespaces": memory_context.routing.namespaces,
                "topic_relation": memory_context.topic.relation,
                "query_rewritten": memory_context.query_rewrite.changed,
                "long_term_count": len(memory_context.long_term_memories),
                "memory_ids": [memory.id for memory in memory_context.long_term_memories if memory.id],
            },
        )

        if memory_context.query_rewrite.changed:
            async with self._span(
                state,
                span_name="router.rewrite_route",
                span_type="router",
                input_json={"message_length": len(memory_context.query_rewrite.rewritten_query)},
            ) as span_output:
                router_output = await self.router.route_async(
                    memory_context.query_rewrite.rewritten_query,
                    uploaded_file_ids=request.uploaded_file_ids,
                    agent_inputs=request.agent_inputs,
                )
                span_output["primary_intent"] = router_output.primary_intent
                span_output["confidence"] = router_output.confidence

        state.router_output = router_output
        state.current_agent = router_output.primary_intent
        state.add_trace("router.completed", router_output.model_dump())
        return {**graph_state, "agent_state": state, "router_output": router_output}

    async def record_router_observation(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        if self.router_observations is None:
            return graph_state
        request = graph_state["request"]
        state = graph_state["agent_state"]
        router_output = graph_state["router_output"]
        try:
            async with self._span(
                state,
                span_name="observability.router_observation",
                span_type="db",
                input_json={"primary_intent": router_output.primary_intent},
            ) as span_output:
                observation_id = await self.router_observations.record(
                    user_id=state.user_id,
                    conversation_id=state.conversation_id,
                    trace_id=state.trace_id,
                    message=request.message,
                    router_output=router_output,
                )
                span_output["router_observation_id"] = observation_id
            state.add_trace("router.observation_recorded", {"router_observation_id": observation_id})
        except Exception as exc:
            state.add_trace("router.observation_failed", {"error": str(exc)})
        return {**graph_state, "agent_state": state}

    async def prepare_multi_intent(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        request = graph_state["request"]
        state = graph_state["agent_state"]
        router_output = graph_state["router_output"]
        if len(router_output.structured_intents) <= 1:
            return graph_state

        async with self._span(
            state,
            span_name="orchestrator.multi_intent_plan",
            span_type="planner",
            input_json={"intent_count": len(router_output.structured_intents)},
        ) as span_output:
            plan = MultiIntentExecutionPlanner().plan(
                MultiIntentExecutionRequest(
                    user_id=request.user_id,
                    message=request.message,
                    structured_intents=router_output.structured_intents,
                    agent_inputs=request.agent_inputs,
                )
            )
            span_output["step_count"] = len(plan.steps)
            span_output["email_reminders"] = len(plan.email_reminder_drafts)
        state.execution_plan = plan
        if plan.steps:
            state.add_artifact("Multi-Intent Execution Plan", "multi_intent_execution", plan.model_dump())
            state.add_trace(
                "multi_intent.plan_prepared",
                {
                    "steps": len(plan.steps),
                    "email_reminders": len(plan.email_reminder_drafts),
                    "unsupported": plan.unsupported_intents,
                },
            )
        return {**graph_state, "agent_state": state, "execution_plan": plan}

    async def dispatch_worker(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        request = graph_state["request"]
        state = graph_state["agent_state"]
        router_output = graph_state["router_output"]
        if state.execution_plan and state.execution_plan.steps:
            return await self._dispatch_execution_plan(graph_state)

        intent = router_output.primary_intent
        state.add_trace("orchestrator.dispatch", {"intent": intent})

        async with self._span(
            state,
            span_name=f"worker.{intent}",
            span_type="worker",
            input_json={"intent": intent},
        ) as span_output:
            worker = self.worker_registry.get(intent)
            if worker is None:
                result = not_implemented_result(intent)
                span_output["implemented"] = False
            else:
                state.add_trace(
                    "worker.selected",
                    {
                        "intent": worker.spec.intent,
                        "input_schema": worker.spec.input_schema,
                        "output_artifact_kind": worker.spec.output_artifact_kind,
                        "required_tools": worker.spec.required_tools,
                        "memory_namespaces": worker.spec.memory_namespaces,
                        "memory_count": _memory_count_for_worker(state, worker.spec.memory_namespaces),
                    },
                )
                agent_state = state.get_agent_state(worker.spec.intent)
                agent_state.begin_run(run_id=state.run_id, trace_id=state.trace_id, request=request)
                result = await worker.run(
                    WorkerContext(
                        request=request,
                        agent_state=agent_state,
                        memory_context=state.memory_context,
                        existing_artifacts=state.artifacts,
                    )
                )
                span_output["implemented"] = True
                span_output["artifact_count"] = len(result.artifacts)
                span_output["missing_information_count"] = len(result.missing_information)

        _apply_worker_result(state, result, agent_name=intent)
        return {**graph_state, "agent_state": state, "worker_result": result}

    async def _dispatch_execution_plan(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        request = graph_state["request"]
        state = graph_state["agent_state"]
        assert state.execution_plan is not None
        state.add_trace(
            "orchestrator.multi_worker_dispatch",
            {"steps": len(state.execution_plan.steps)},
        )

        final_steps: dict[int, ExecutionStep] = {}
        response_parts: list[str] = []
        completed_indexes: set[int] = {
            step.index for step in state.execution_plan.steps if step.status in {"completed", "skipped"}
        }
        executed_worker_keys: set[tuple[str, str]] = set()
        pending_steps: dict[int, ExecutionStep] = {}

        for step in state.execution_plan.steps:
            executable_step = step.model_copy(deep=True)
            if executable_step.status == "needs_input":
                final_steps[executable_step.index] = executable_step
                state.missing_information.extend(executable_step.missing_slots)
                continue
            if executable_step.status == "blocked":
                final_steps[executable_step.index] = executable_step
                continue
            if executable_step.status == "skipped":
                final_steps[executable_step.index] = executable_step
                completed_indexes.add(executable_step.index)
                continue
            pending_steps[executable_step.index] = executable_step

        while pending_steps:
            blocked_now = [
                step
                for step in pending_steps.values()
                if any(
                    dependency not in completed_indexes and dependency not in pending_steps
                    for dependency in step.depends_on
                )
            ]
            for step in blocked_now:
                missing_dependencies = [
                    dependency for dependency in step.depends_on if dependency not in completed_indexes
                ]
                blocked_step = step.model_copy(
                    update={
                        "status": "blocked",
                        "result_summary": f"Blocked by unfinished dependency step(s): {missing_dependencies}.",
                    }
                )
                final_steps[step.index] = blocked_step
                pending_steps.pop(step.index, None)
                state.add_trace(
                    "worker.step_blocked",
                    {"step": step.index, "dependencies": missing_dependencies},
                )

            runnable_steps = [
                step
                for step in sorted(pending_steps.values(), key=lambda item: item.index)
                if all(dependency in completed_indexes for dependency in step.depends_on)
            ]
            if not runnable_steps:
                for step in sorted(pending_steps.values(), key=lambda item: item.index):
                    blocked_step = step.model_copy(
                        update={
                            "status": "blocked",
                            "result_summary": "Blocked because no dependency-complete execution layer could be formed.",
                        }
                    )
                    final_steps[step.index] = blocked_step
                    state.add_trace("worker.step_blocked", {"step": step.index, "dependencies": step.depends_on})
                pending_steps.clear()
                break

            layer_results: list[WorkerStepExecutionResult] = []
            layer_worker_keys: set[tuple[str, str]] = set()
            for step in runnable_steps:
                worker = self.worker_registry.get(step.agent_intent)
                if worker is None:
                    blocked_step = step.model_copy(
                        update={
                            "status": "blocked",
                            "worker_intent": step.agent_intent,
                            "result_summary": f"No worker is registered for {step.agent_intent}.",
                        }
                    )
                    final_steps[step.index] = blocked_step
                    pending_steps.pop(step.index, None)
                    state.add_trace("worker.step_blocked", {"step": step.index, "intent": step.agent_intent})
                    continue

                worker_key = (worker.spec.intent, _stable_slots_key(step.slots))
                if worker_key in executed_worker_keys or worker_key in layer_worker_keys:
                    completed_step = step.model_copy(
                        update={
                            "status": "completed",
                            "worker_intent": worker.spec.intent,
                            "result_summary": "Worker already executed for the same intent and slots.",
                        }
                    )
                    final_steps[step.index] = completed_step
                    pending_steps.pop(step.index, None)
                    completed_indexes.add(step.index)
                    continue
                layer_worker_keys.add(worker_key)

            executable_steps = [
                step
                for step in runnable_steps
                if step.index in pending_steps
            ]
            state.add_trace(
                "orchestrator.worker_layer_started",
                {"steps": [step.index for step in executable_steps]},
            )
            layer_results = await asyncio.gather(
                *[
                    self._execute_worker_step(
                        state=state,
                        request=request,
                        step=step,
                        existing_artifacts_snapshot=list(state.artifacts),
                    )
                    for step in executable_steps
                ]
            )
            for execution in sorted(layer_results, key=lambda item: item.step.index):
                final_steps[execution.step.index] = execution.step
                pending_steps.pop(execution.step.index, None)
                for trace_event in execution.trace_events:
                    state.add_trace(trace_event.get("name", "worker.event"), trace_event.get("payload", {}))
                _apply_worker_result(
                    state,
                    execution.worker_result,
                    agent_name=execution.worker_key[0] if execution.worker_key else execution.step.agent_intent,
                )
                for tool_result in execution.tool_results:
                    tool_result_json = tool_result.model_dump(mode="json")
                    state.tool_results.append(tool_result_json)
                    state.get_agent_state(
                        execution.worker_key[0] if execution.worker_key else execution.step.agent_intent
                    ).tool_results.append(tool_result_json)
                if execution.worker_result.final_response:
                    response_parts.append(execution.worker_result.final_response)
                if execution.worker_key:
                    executed_worker_keys.add(execution.worker_key)
                if execution.step.status == "completed":
                    completed_indexes.add(execution.step.index)
                if execution.step.status == "needs_input":
                    state.missing_information.extend(execution.step.missing_slots)
            state.add_trace(
                "orchestrator.worker_layer_completed",
                {"steps": [result.step.index for result in layer_results]},
            )

        step_results = [
            final_steps[step.index]
            for step in state.execution_plan.steps
            if step.index in final_steps
        ]
        final_plan = state.execution_plan.model_copy(update={"steps": step_results})
        state.execution_plan = final_plan
        state.worker_execution_results = [step.model_dump(mode="json") for step in step_results]
        state.add_artifact(
            "Multi-Worker Execution Result",
            "multi_worker_execution_result",
            {
                "summary": _multi_worker_summary(step_results),
                "steps": state.worker_execution_results,
            },
        )
        state.add_trace(
            "orchestrator.multi_worker_completed",
            {
                "completed": len([step for step in step_results if step.status == "completed"]),
                "needs_input": len([step for step in step_results if step.status == "needs_input"]),
                "blocked": len([step for step in step_results if step.status == "blocked"]),
                "failed": len([step for step in step_results if step.status == "failed"]),
            },
        )
        if response_parts:
            state.final_response = "\n\n".join(response_parts)
        return {**graph_state, "agent_state": state}

    async def finalize_response(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        state = graph_state["agent_state"]
        router_output = graph_state["router_output"]
        if not state.final_response:
            state.final_response = _fallback_response(router_output.primary_intent, state)
        return {**graph_state, "agent_state": state}

    async def persist_run(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        request = graph_state["request"]
        state = graph_state["agent_state"]
        router_output = graph_state["router_output"]
        if not request.persist_agent_runs or self.recorder is None:
            return graph_state
        async with self._span(
            state,
            span_name="agent_run.persist",
            span_type="db",
            input_json={"primary_intent": router_output.primary_intent},
        ) as span_output:
            run_id = await self.recorder.record_completed_run(
                user_id=state.user_id,
                conversation_id=state.conversation_id,
                trace_id=state.trace_id,
                agent_name=router_output.primary_intent,
                router_output=router_output,
                input_json=request.model_dump(),
                output_json={
                    "final_response": state.final_response,
                    "artifacts": [artifact.model_dump() for artifact in state.artifacts],
                    "missing_information": state.missing_information,
                    "next_actions": state.next_actions,
                    "trace": [event.model_dump() for event in state.trace],
                },
                started_at=min((span.started_at for span in state.latency_spans), default=None),
                completed_at=max((span.completed_at for span in state.latency_spans), default=None),
            )
            span_output["agent_run_id"] = run_id
        state.persisted_agent_run_id = run_id
        for span in state.latency_spans:
            span.agent_run_id = run_id
        state.add_trace("agent_run.persisted", {"agent_run_id": run_id})
        return {**graph_state, "agent_state": state}

    async def update_memory(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        request = graph_state["request"]
        state = graph_state["agent_state"]
        router_output = graph_state["router_output"]
        async with self._span(
            state,
            span_name="memory.update_after_response",
            span_type="memory",
            input_json={"conversation_id": state.conversation_id, "primary_intent": router_output.primary_intent},
        ):
            await self.memory_manager.update_after_response(
                request=request,
                conversation_id=state.conversation_id,
                response_text=state.final_response,
                router_output=router_output,
                topic_summary=state.memory_context.topic.topic_summary if state.memory_context else None,
            )
        state.add_trace("memory.updated", {"conversation_id": state.conversation_id})
        return {**graph_state, "agent_state": state}

    async def persist_spans(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        state = graph_state["agent_state"]
        persisted = False
        if self.trace_spans is not None and state.latency_spans:
            for span in state.latency_spans:
                if state.persisted_agent_run_id and span.agent_run_id is None:
                    span.agent_run_id = state.persisted_agent_run_id
            try:
                count = await self.trace_spans.record_many(state.latency_spans)
                state.add_trace("trace_spans.persisted", {"count": count})
                persisted = True
            except Exception as exc:
                state.add_trace("trace_spans.persist_failed", {"error": str(exc)})
        state.latency_summary = summarize_latency_spans(
            state.trace_id,
            state.latency_spans,
            persisted=persisted,
        )
        return {**graph_state, "agent_state": state}

    async def build_response(self, graph_state: OrchestratorGraphState) -> OrchestratorGraphState:
        state = graph_state["agent_state"]
        router_output = graph_state["router_output"]
        response = ChatResponse(
            user_id=state.user_id,
            conversation_id=state.conversation_id,
            trace_id=state.trace_id,
            router=router_output,
            final_response=state.final_response,
            artifacts=state.artifacts,
            trace=state.trace,
            latency_summary=state.latency_summary,
            memory_context=state.memory_context.model_dump() if state.memory_context else None,
            missing_information=state.missing_information,
            next_actions=state.next_actions,
        )
        state.append_assistant_turn()
        return {**graph_state, "agent_state": state, "response": response}

    def _span(
        self,
        state: AgentState,
        *,
        span_name: str,
        span_type: str,
        input_json: dict[str, Any] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ):
        return capture_latency_span(
            state.latency_spans,
            trace_id=state.trace_id,
            user_id=state.user_id,
            conversation_id=state.conversation_id,
            span_name=span_name,
            span_type=span_type,
            input_json=input_json,
            metadata_json=metadata_json,
        )

    async def _execute_worker_step(
        self,
        *,
        state: AgentState,
        request: ChatRequest,
        step: ExecutionStep,
        existing_artifacts_snapshot: list,
    ) -> WorkerStepExecutionResult:
        worker = self.worker_registry.get(step.agent_intent)
        if worker is None:
            blocked_step = step.model_copy(
                update={
                    "status": "blocked",
                    "worker_intent": step.agent_intent,
                    "result_summary": f"No worker is registered for {step.agent_intent}.",
                }
            )
            return WorkerStepExecutionResult(
                step=blocked_step,
                worker_result=WorkerRunResult(),
                worker_key=None,
                tool_results=[],
                trace_events=[{"name": "worker.step_blocked", "payload": {"step": step.index, "intent": step.agent_intent}}],
            )

        tool_statuses = self._tool_statuses_for_worker(worker.spec.required_tools)
        tool_results, tool_trace_events = await self._run_worker_tool_calls(
            state=state,
            request=request,
            step=step,
            required_tools=worker.spec.required_tools,
        )
        step_request = _request_for_step(request, worker.spec.input_key, step)
        trace_events = [
            {
                "name": "worker.selected",
                "payload": {
                    "intent": worker.spec.intent,
                    "step": step.index,
                    "input_schema": worker.spec.input_schema,
                    "output_artifact_kind": worker.spec.output_artifact_kind,
                    "required_tools": worker.spec.required_tools,
                    "memory_namespaces": worker.spec.memory_namespaces,
                    "memory_count": _memory_count_for_worker(state, worker.spec.memory_namespaces),
                    "tool_statuses": tool_statuses,
                },
            },
            *tool_trace_events,
        ]
        async with self._span(
            state,
            span_name=f"worker.{worker.spec.intent}.step_{step.index}",
            span_type="worker",
            input_json={
                "step": step.index,
                "intent_name": step.intent_name,
                "worker_intent": worker.spec.intent,
            },
        ) as span_output:
            try:
                agent_state = state.get_agent_state(worker.spec.intent)
                agent_state.begin_run(run_id=state.run_id, trace_id=state.trace_id, request=step_request)
                worker_result = await worker.run(
                    WorkerContext(
                        request=step_request,
                        agent_state=agent_state,
                        memory_context=state.memory_context,
                        existing_artifacts=existing_artifacts_snapshot,
                        execution_step=step,
                        tool_statuses=tool_statuses,
                        tool_results=[result.model_dump(mode="json") for result in tool_results],
                    )
                )
                span_output["artifact_count"] = len(worker_result.artifacts)
                span_output["missing_information_count"] = len(worker_result.missing_information)
                status = "needs_input" if worker_result.missing_information else "completed"
            except Exception as exc:
                worker_result = WorkerRunResult(
                    final_response=f"{worker.spec.intent} worker 执行失败。",
                    trace_events=[
                        {
                            "name": "worker.failed",
                            "payload": {
                                "agent": worker.spec.intent,
                                "step": step.index,
                                "error": str(exc),
                            },
                        }
                    ],
                )
                span_output["error"] = str(exc)
                status = "failed"

        trace_events.extend(worker_result.trace_events)
        updated_step = step.model_copy(
            update={
                "status": status,
                "worker_intent": worker.spec.intent,
                "artifact_count": len(worker_result.artifacts),
                "tool_statuses": tool_statuses,
                "tool_results": [result.model_dump(mode="json") for result in tool_results],
                "missing_slots": worker_result.missing_information or step.missing_slots,
                "result_summary": worker_result.final_response or step.result_summary,
            }
        )
        return WorkerStepExecutionResult(
            step=updated_step,
            worker_result=worker_result,
            worker_key=(worker.spec.intent, _stable_slots_key(step.slots)),
            tool_results=tool_results,
            trace_events=trace_events,
        )

    def _tool_statuses_for_worker(self, required_tools: list[str]) -> list[dict[str, Any]]:
        if not required_tools:
            return []
        statuses_by_name = {
            status.name: status.model_dump(mode="json")
            for status in self.tool_registry.list_availability()
        }
        return [
            statuses_by_name.get(
                tool_name,
                {
                    "name": tool_name,
                    "capability": tool_name,
                    "available": False,
                    "status": "unregistered",
                    "permission_level": "none",
                    "missing_env": [],
                    "required_env": [],
                    "metadata": {},
                },
            )
            for tool_name in required_tools
        ]

    async def _run_worker_tool_calls(
        self,
        *,
        state: AgentState,
        request: ChatRequest,
        step: ExecutionStep,
        required_tools: list[str],
    ) -> tuple[list[ToolCallResult], list[dict[str, Any]]]:
        tool_inputs = _extract_tool_inputs(request, step)
        if not tool_inputs:
            return [], []
        results: list[ToolCallResult] = []
        trace_events: list[dict[str, Any]] = []
        executor = ToolExecutor(registry=self.tool_registry)
        allowed_tools = set(required_tools) | set(tool_inputs)
        for tool_name in sorted(allowed_tools):
            if tool_name not in tool_inputs:
                continue
            async with self._span(
                state,
                span_name=f"tool.{tool_name}.step_{step.index}",
                span_type="tool",
                input_json={"step": step.index, "tool_name": tool_name},
            ) as span_output:
                result = await executor.run(
                    ToolCallRequest(
                        tool_name=tool_name,
                        arguments=tool_inputs[tool_name],
                        approved=bool(tool_inputs[tool_name].get("approved", False)),
                        user_id=state.user_id,
                        conversation_id=state.conversation_id,
                        trace_id=state.trace_id,
                    )
                )
                span_output["success"] = result.success
                span_output["requires_approval"] = result.requires_approval
                if result.error:
                    span_output["error"] = result.error
                results.append(result)
                trace_events.append(
                    {
                        "name": "tool.executed",
                        "payload": {
                            "step": step.index,
                            "tool_name": tool_name,
                            "success": result.success,
                            "requires_approval": result.requires_approval,
                        },
                    }
                )
        return results, trace_events


def _apply_worker_result(state: AgentState, result: WorkerRunResult, *, agent_name: str | None = None) -> None:
    state.artifacts.extend(result.artifacts)
    state.missing_information.extend(result.missing_information)
    state.next_actions.extend(result.next_actions)
    if result.final_response:
        state.final_response = result.final_response
    if agent_name:
        agent_state = state.get_agent_state(agent_name)
        agent_state.artifacts.extend(result.artifacts)
        agent_state.missing_information.extend(result.missing_information)
        agent_state.next_actions.extend(result.next_actions)
        agent_state.append_assistant_turn(result.final_response)
    for event in result.trace_events:
        state.add_trace(event.get("name", "worker.event"), event.get("payload", {}))


def _fallback_response(intent: Intent, state: AgentState) -> str:
    if state.missing_information:
        return "需要补充信息后才能继续：" + "、".join(state.missing_information)
    return f"已完成 {intent} 路由，但当前没有产生可展示结果。"


def _request_for_step(request: ChatRequest, input_key: str | None, step: ExecutionStep) -> ChatRequest:
    if not input_key or not step.slots:
        return request
    agent_inputs = {
        key: dict(value)
        for key, value in request.agent_inputs.items()
    }
    existing_payload = agent_inputs.get(input_key, {})
    merged_payload = {
        **step.slots,
        **existing_payload,
    }
    agent_inputs[input_key] = merged_payload
    return request.model_copy(update={"agent_inputs": agent_inputs})


def _extract_tool_inputs(request: ChatRequest, step: ExecutionStep) -> dict[str, dict[str, Any]]:
    tool_inputs: dict[str, dict[str, Any]] = {}
    sources = [
        request.agent_inputs.get("tool_calls", {}),
        request.agent_inputs.get("tools", {}),
        step.slots.get("tool_calls", {}),
        step.slots.get("tools", {}),
    ]
    for source in sources:
        if isinstance(source, dict):
            for tool_name, payload in source.items():
                if isinstance(payload, dict):
                    tool_inputs[tool_name] = payload
    return tool_inputs


def _stable_slots_key(slots: dict[str, Any]) -> str:
    return json.dumps(slots, sort_keys=True, ensure_ascii=False, default=str)


def _memory_count_for_worker(state: AgentState, namespaces: list[str]) -> int:
    if state.memory_context is None:
        return 0
    allowed = set(namespaces)
    return len(
        [
            memory
            for memory in state.memory_context.long_term_memories
            if str(memory.namespace) in allowed
        ]
    )


def _multi_worker_summary(steps: list[ExecutionStep]) -> str:
    completed = len([step for step in steps if step.status == "completed"])
    needs_input = len([step for step in steps if step.status == "needs_input"])
    blocked = len([step for step in steps if step.status == "blocked"])
    failed = len([step for step in steps if step.status == "failed"])
    return (
        f"已执行 {completed} 个 Worker 步骤；"
        f"{needs_input} 个步骤需要补充信息，{blocked} 个步骤被依赖或能力边界阻塞，{failed} 个步骤失败。"
    )
