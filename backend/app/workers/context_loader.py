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
from app.tools.models import ToolCallResult
from app.tools.registry import ToolRegistry, build_default_tool_registry
from app.tools.runtime import AgentToolRuntime
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
        memory_json = (workflow.plan_json or {}).get("memory_context")
        memory_context = MemoryContext.model_validate(memory_json) if memory_json else None
        request = _request_with_rewritten_query(request, memory_context)
        request = _request_for_step(request, worker.spec.input_key, step.input_json or {})
        artifact_records = await self.repository.list_artifacts(
            workflow.id,
            artifact_ids=command.dependency_artifact_ids,
        )
        artifacts = [
            AgentArtifact(name=record.name, kind=record.kind, payload=record.payload_json or {})
            for record in artifact_records
        ]
        tool_statuses = self._tool_statuses(worker.spec.allowed_tools)
        tool_runtime = AgentToolRuntime(
            agent_name=worker.spec.intent,
            allowed_tools=worker.spec.allowed_tools,
            request=request,
            registry=self.tool_registry,
            step_slots=step.input_json or {},
            workflow_id=workflow.id,
            step_id=step.id,
            trace_id=workflow.trace_id,
            cancellation_check=lambda: self._raise_if_cancelled(workflow.id),
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
                tool_runtime=tool_runtime,
            ),
            [],
        )

    def _tool_statuses(self, allowed_tools: list[str]) -> list[dict[str, Any]]:
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
            for name in allowed_tools
        ]

    async def _raise_if_cancelled(self, workflow_id: str) -> None:
        status = await self.session.scalar(
            select(WorkflowRun.status).where(WorkflowRun.id == workflow_id)
        )
        if status in {"cancel_requested", "cancelled"}:
            raise asyncio.CancelledError("Workflow cancellation requested before tool execution")


def _request_for_step(request: ChatRequest, input_key: str | None, slots: dict) -> ChatRequest:
    if not input_key or not slots:
        return request
    agent_inputs = {key: dict(value) for key, value in request.agent_inputs.items()}
    agent_inputs[input_key] = {**slots, **agent_inputs.get(input_key, {})}
    return request.model_copy(update={"agent_inputs": agent_inputs})


def _request_with_rewritten_query(
    request: ChatRequest,
    memory_context: MemoryContext | None,
) -> ChatRequest:
    if memory_context is None or not memory_context.query_rewrite.changed:
        return request
    rewritten_query = memory_context.query_rewrite.rewritten_query.strip()
    if not rewritten_query or rewritten_query == request.message:
        return request
    return request.model_copy(update={"message": rewritten_query})
