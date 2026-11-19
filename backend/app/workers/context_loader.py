from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.orchestrator.state import AgentScopedState
from app.agents.orchestrator.workers import WorkerAgent, WorkerContext
from app.db.models import WorkflowRun
from app.schemas.chat import AgentArtifact, ChatRequest
from app.schemas.execution import ExecutionStep
from app.schemas.memory import MemoryContext
from app.schemas.messages import AgentTaskCommand
from app.tools.executor import ToolExecutor
from app.tools.models import ToolCallRequest, ToolCallResult
from app.tools.registry import ToolRegistry, build_default_tool_registry
from app.workflows.repository import WorkflowRepository


class WorkerContextLoader:
    def __init__(
        self,
        session: AsyncSession,
        *,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.session = session
        self.repository = WorkflowRepository(session)
        self.tool_registry = tool_registry or build_default_tool_registry()

    async def load(
        self,
        command: AgentTaskCommand,
        worker: WorkerAgent,
    ) -> tuple[WorkerContext, list[ToolCallResult]]:
        workflow = await self.repository.get(command.workflow_id)
        step = await self.repository.get_step(command.step_id, workflow_id=workflow.id)
        request = ChatRequest.model_validate(workflow.input_json["chat_request"])
        request = _request_for_step(request, worker.spec.input_key, step.input_json or {})
        artifact_records = await self.repository.list_artifacts(
            workflow.id,
            artifact_ids=command.dependency_artifact_ids,
        )
        artifacts = [
            AgentArtifact(name=record.name, kind=record.kind, payload=record.payload_json or {})
            for record in artifact_records
        ]
        memory_json = (workflow.plan_json or {}).get("memory_context")
        memory_context = MemoryContext.model_validate(memory_json) if memory_json else None
        tool_statuses = self._tool_statuses(worker.spec.required_tools)
        tool_results = await self._run_tools(
            request=request,
            slots=step.input_json or {},
            allowed_tools=set(worker.spec.required_tools),
            command=command,
        )
        execution_step = ExecutionStep(
            index=int(step.step_key) if step.step_key.isdigit() else 0,
            intent_name=step.intent_name,
            agent_intent=step.agent_intent,
            status="planned",
            slots=step.input_json or {},
            result_summary=step.result_summary,
        )
        agent_state = AgentScopedState(agent_name=worker.spec.intent)
        agent_state.begin_run(
            run_id=workflow.id,
            trace_id=workflow.trace_id,
            request=request,
        )
        return (
            WorkerContext(
                request=request,
                agent_state=agent_state,
                memory_context=memory_context,
                existing_artifacts=artifacts,
                execution_step=execution_step,
                tool_statuses=tool_statuses,
                tool_results=[result.model_dump(mode="json") for result in tool_results],
            ),
            tool_results,
        )

    def _tool_statuses(self, required_tools: list[str]) -> list[dict[str, Any]]:
        statuses = {
            status.name: status.model_dump(mode="json")
            for status in self.tool_registry.list_availability()
        }
        return [
            statuses.get(
                name,
                {
                    "name": name,
                    "available": False,
                    "status": "unregistered",
                    "permission_level": "none",
                    "missing_env": [],
                    "required_env": [],
                    "metadata": {},
                },
            )
            for name in required_tools
        ]

    async def _run_tools(
        self,
        *,
        request: ChatRequest,
        slots: dict[str, Any],
        allowed_tools: set[str],
        command: AgentTaskCommand,
    ) -> list[ToolCallResult]:
        inputs = _extract_tool_inputs(request, slots)
        executor = ToolExecutor(registry=self.tool_registry)
        results: list[ToolCallResult] = []
        for tool_name in sorted(inputs):
            if tool_name not in allowed_tools:
                continue
            status = await self.session.scalar(
                select(WorkflowRun.status).where(WorkflowRun.id == command.workflow_id)
            )
            if status in {"cancel_requested", "cancelled"}:
                raise asyncio.CancelledError("Workflow cancellation requested before tool execution")
            arguments = inputs[tool_name]
            results.append(
                await executor.run(
                    ToolCallRequest(
                        tool_name=tool_name,
                        arguments=arguments,
                        approved=bool(arguments.get("approved", False)),
                        user_id=request.user_id,
                        conversation_id=request.conversation_id,
                        trace_id=command.trace_id,
                    )
                )
            )
        return results


def _request_for_step(request: ChatRequest, input_key: str | None, slots: dict) -> ChatRequest:
    if not input_key or not slots:
        return request
    agent_inputs = {key: dict(value) for key, value in request.agent_inputs.items()}
    agent_inputs[input_key] = {**slots, **agent_inputs.get(input_key, {})}
    return request.model_copy(update={"agent_inputs": agent_inputs})


def _extract_tool_inputs(request: ChatRequest, slots: dict[str, Any]) -> dict[str, dict[str, Any]]:
    inputs: dict[str, dict[str, Any]] = {}
    for source in (
        request.agent_inputs.get("tool_calls", {}),
        request.agent_inputs.get("tools", {}),
        slots.get("tool_calls", {}),
        slots.get("tools", {}),
    ):
        if isinstance(source, dict):
            for name, payload in source.items():
                if isinstance(payload, dict):
                    inputs[name] = payload
    return inputs
