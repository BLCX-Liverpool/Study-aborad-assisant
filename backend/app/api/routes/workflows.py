from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session, get_session_factory
from app.schemas.workflow import (
    WorkflowActionResult,
    WorkflowArtifactView,
    WorkflowInputSubmission,
    WorkflowStepView,
    WorkflowView,
)
from app.workflows.repository import WorkflowNotFound, WorkflowRepository
from app.workflows.service import WorkflowService, artifact_view, workflow_view
from app.workflows.state_machine import StepStatus, WorkflowStatus


router = APIRouter()
TERMINAL_WORKFLOW_STATUSES = {
    "completed",
    "partial_failed",
    "failed",
    "cancelled",
    "dead_lettered",
}


@router.get("/{workflow_id}", response_model=WorkflowView)
async def get_workflow(
    workflow_id: str,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> WorkflowView:
    try:
        return await WorkflowService(session).view(workflow_id, user_id=user_id)
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc


@router.get("/{workflow_id}/steps", response_model=list[WorkflowStepView])
async def get_workflow_steps(
    workflow_id: str,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> list[WorkflowStepView]:
    workflow = await _owned_workflow(session, workflow_id, user_id)
    return workflow_view(workflow, await WorkflowRepository(session).list_steps(workflow.id)).steps


@router.get("/{workflow_id}/artifacts", response_model=list[WorkflowArtifactView])
async def get_workflow_artifacts(
    workflow_id: str,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> list[WorkflowArtifactView]:
    workflow = await _owned_workflow(session, workflow_id, user_id)
    return [artifact_view(item) for item in await WorkflowRepository(session).list_artifacts(workflow.id)]


@router.get("/{workflow_id}/events")
async def stream_workflow_events(
    workflow_id: str,
    user_id: str = Query(...),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    await _owned_workflow(session, workflow_id, user_id)
    try:
        cursor = int(last_event_id or 0)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer") from exc

    async def events():
        nonlocal cursor
        settings = get_settings()
        deadline = asyncio.get_running_loop().time() + settings.workflow_sse_timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            terminal = False
            async with get_session_factory()() as poll_session:
                repository = WorkflowRepository(poll_session)
                workflow = await repository.get(workflow_id, user_id=user_id)
                rows = await repository.list_events(workflow_id, after_id=cursor)
                terminal = workflow.status in TERMINAL_WORKFLOW_STATUSES
            for row in rows:
                cursor = row.id
                data = json.dumps(row.payload_json, ensure_ascii=False, default=str)
                yield f"id: {row.id}\nevent: {row.event_type}\ndata: {data}\n\n"
            if terminal and not rows:
                break
            if not rows:
                yield ": keep-alive\n\n"
            await asyncio.sleep(settings.workflow_sse_poll_seconds)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{workflow_id}/inputs", response_model=WorkflowActionResult)
async def submit_workflow_input(
    workflow_id: str,
    request: WorkflowInputSubmission,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> WorkflowActionResult:
    repository = WorkflowRepository(session)
    workflow = await _owned_workflow(session, workflow_id, user_id)
    step = await repository.get_step(request.step_id, workflow_id=workflow.id)
    if step.status != StepStatus.NEEDS_INPUT.value:
        raise HTTPException(status_code=409, detail="Step is not waiting for input")
    chat_request = dict(workflow.input_json["chat_request"])
    agent_inputs = dict(chat_request.get("agent_inputs") or {})
    for key, value in request.agent_inputs.items():
        agent_inputs[key] = {**agent_inputs.get(key, {}), **value}
    chat_request["agent_inputs"] = agent_inputs
    workflow.input_json = {**workflow.input_json, "chat_request": chat_request}
    step.input_json = {
        **(step.input_json or {}),
        **request.agent_inputs.get(step.agent_intent, {}),
    }
    await repository.transition_step(
        step,
        StepStatus.PENDING,
        missing_information_json=[],
        last_error_code=None,
        last_error_message=None,
    )
    if workflow.status == WorkflowStatus.WAITING_INPUT.value:
        await repository.transition_workflow(workflow, WorkflowStatus.RUNNING)
    await WorkflowService(session).queue_ready_steps(workflow)
    await session.commit()
    return WorkflowActionResult(workflow_id=workflow.id, status=workflow.status, changed=True)


@router.post("/{workflow_id}/cancel", response_model=WorkflowActionResult)
async def cancel_workflow(
    workflow_id: str,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> WorkflowActionResult:
    repository = WorkflowRepository(session)
    workflow = await _owned_workflow(session, workflow_id, user_id)
    if workflow.status in TERMINAL_WORKFLOW_STATUSES:
        return WorkflowActionResult(workflow_id=workflow.id, status=workflow.status, changed=False)
    changed = await repository.transition_workflow(workflow, WorkflowStatus.CANCEL_REQUESTED)
    running = False
    for step in await repository.list_steps(workflow.id):
        if step.status == StepStatus.RUNNING.value:
            running = True
        elif step.status in {
            StepStatus.PENDING.value,
            StepStatus.QUEUED.value,
            StepStatus.RETRY_WAIT.value,
            StepStatus.NEEDS_INPUT.value,
        }:
            await repository.transition_step(step, StepStatus.CANCELLED)
    if not running:
        await repository.transition_workflow(workflow, WorkflowStatus.CANCELLED)
    await session.commit()
    return WorkflowActionResult(workflow_id=workflow.id, status=workflow.status, changed=changed)


@router.post("/{workflow_id}/retry", response_model=WorkflowActionResult)
async def retry_workflow(
    workflow_id: str,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> WorkflowActionResult:
    repository = WorkflowRepository(session)
    workflow = await _owned_workflow(session, workflow_id, user_id)
    if workflow.status not in {"failed", "partial_failed", "dead_lettered"}:
        raise HTTPException(status_code=409, detail="Workflow is not retryable")
    await repository.transition_workflow(workflow, WorkflowStatus.RUNNING)
    changed = False
    service = WorkflowService(session)
    for step in await repository.list_steps(workflow.id):
        if step.status in {StepStatus.FAILED.value, StepStatus.DEAD_LETTERED.value}:
            changed = await service.enqueue_step(workflow, step) or changed
    await session.commit()
    return WorkflowActionResult(workflow_id=workflow.id, status=workflow.status, changed=changed)


@router.post("/{workflow_id}/steps/{step_id}/retry", response_model=WorkflowActionResult)
async def retry_workflow_step(
    workflow_id: str,
    step_id: str,
    user_id: str = Query(...),
    session: AsyncSession = Depends(get_session),
) -> WorkflowActionResult:
    repository = WorkflowRepository(session)
    workflow = await _owned_workflow(session, workflow_id, user_id)
    step = await repository.get_step(step_id, workflow_id=workflow.id)
    if step.status not in {StepStatus.FAILED.value, StepStatus.DEAD_LETTERED.value}:
        raise HTTPException(status_code=409, detail="Step is not retryable")
    if workflow.status in {"failed", "partial_failed", "dead_lettered"}:
        await repository.transition_workflow(workflow, WorkflowStatus.RUNNING)
    changed = await WorkflowService(session).enqueue_step(workflow, step)
    await session.commit()
    return WorkflowActionResult(workflow_id=workflow.id, status=workflow.status, changed=changed)


async def _owned_workflow(session: AsyncSession, workflow_id: str, user_id: str):
    try:
        return await WorkflowRepository(session).get(workflow_id, user_id=user_id)
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail="Workflow not found") from exc
