from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import and_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    AgentArtifactRecord,
    MessageInbox,
    WorkflowEventLog,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepDependency,
)
from app.schemas.chat import AgentArtifact
from app.workflows.state_machine import (
    StepStateMachine,
    StepStatus,
    WorkflowStateMachine,
    WorkflowStatus,
)


class WorkflowNotFound(LookupError):
    pass


class WorkflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_request_id(self, *, user_id: str, request_id: str) -> WorkflowRun | None:
        result = await self.session.execute(
            select(WorkflowRun).where(
                WorkflowRun.user_id == user_id,
                WorkflowRun.request_id == request_id,
            )
        )
        return result.scalar_one_or_none()

    async def get(self, workflow_id: str, *, user_id: str | None = None) -> WorkflowRun:
        statement = select(WorkflowRun).where(WorkflowRun.id == workflow_id)
        if user_id is not None:
            statement = statement.where(WorkflowRun.user_id == user_id)
        result = await self.session.execute(statement)
        workflow = result.scalar_one_or_none()
        if workflow is None:
            raise WorkflowNotFound(workflow_id)
        return workflow

    async def create(
        self,
        *,
        user_id: str,
        conversation_id: str,
        trace_id: str,
        request_id: str,
        workflow_type: str,
        input_json: dict,
    ) -> WorkflowRun:
        workflow = WorkflowRun(
            id=str(uuid4()),
            user_id=user_id,
            conversation_id=conversation_id,
            trace_id=trace_id,
            request_id=request_id,
            workflow_type=workflow_type,
            status=WorkflowStatus.CREATED.value,
            input_json=input_json,
        )
        self.session.add(workflow)
        await self.session.flush()
        await self.append_event(workflow.id, "workflow.created", {"status": workflow.status})
        return workflow

    async def transition_workflow(
        self,
        workflow: WorkflowRun,
        target: WorkflowStatus,
        *,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> bool:
        WorkflowStateMachine.transition(workflow.status, target)
        now = datetime.now(UTC)
        values: dict = {
            "status": target.value,
            "version": workflow.version + 1,
            "updated_at": now,
        }
        if target in {WorkflowStatus.PLANNING, WorkflowStatus.RUNNING} and workflow.started_at is None:
            values["started_at"] = now
        if target in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.PARTIAL_FAILED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
            WorkflowStatus.DEAD_LETTERED,
        }:
            values["completed_at"] = now
        if target == WorkflowStatus.CANCEL_REQUESTED:
            values["cancel_requested_at"] = now
        if error_code is not None:
            values["error_code"] = error_code
        if error_message is not None:
            values["error_message"] = error_message
        result = await self.session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == workflow.id,
                WorkflowRun.status == workflow.status,
                WorkflowRun.version == workflow.version,
            )
            .values(**values)
        )
        changed = bool(result.rowcount)
        if changed:
            for key, value in values.items():
                setattr(workflow, key, value)
            await self.append_event(workflow.id, f"workflow.{target.value}", {"status": target.value})
        return changed

    async def create_steps(self, workflow_id: str, steps: list[dict]) -> dict[int, WorkflowStep]:
        by_index: dict[int, WorkflowStep] = {}
        for item in steps:
            source_status = item.get("status", "planned")
            if source_status == "needs_input":
                status = StepStatus.NEEDS_INPUT.value
            elif source_status in {"failed", "blocked"}:
                status = StepStatus.FAILED.value
            elif source_status in {"completed", "skipped"}:
                status = StepStatus.COMPLETED.value
            else:
                status = StepStatus.PENDING.value
            index = int(item["index"])
            step = WorkflowStep(
                id=str(uuid4()),
                workflow_id=workflow_id,
                step_key=str(item.get("step_key", index)),
                intent_name=str(item["intent_name"]),
                agent_intent=str(item["agent_intent"]),
                status=status,
                input_json=dict(item.get("slots") or {}),
                input_ref=f"workflow-input:{workflow_id}",
                result_summary=item.get("result_summary"),
                missing_information_json=list(item.get("missing_slots") or []),
                max_attempts=int(item.get("max_attempts", 3)),
            )
            self.session.add(step)
            by_index[index] = step
        await self.session.flush()
        for item in steps:
            step = by_index[int(item["index"])]
            for dependency_index in item.get("depends_on", []):
                dependency = by_index.get(int(dependency_index))
                if dependency is None:
                    step.status = StepStatus.FAILED.value
                    step.last_error_code = "missing_dependency"
                    step.last_error_message = f"Dependency step {dependency_index} does not exist"
                    continue
                self.session.add(
                    WorkflowStepDependency(
                        id=str(uuid4()),
                        step_id=step.id,
                        depends_on_step_id=dependency.id,
                        condition_json={"expression": item.get("condition")} if item.get("condition") else None,
                    )
                )
        await self.session.flush()
        return by_index

    async def list_steps(self, workflow_id: str) -> list[WorkflowStep]:
        result = await self.session.execute(
            select(WorkflowStep)
            .where(WorkflowStep.workflow_id == workflow_id)
            .order_by(WorkflowStep.created_at, WorkflowStep.step_key)
        )
        return list(result.scalars().all())

    async def get_step(self, step_id: str, *, workflow_id: str | None = None) -> WorkflowStep:
        statement = select(WorkflowStep).where(WorkflowStep.id == step_id)
        if workflow_id is not None:
            statement = statement.where(WorkflowStep.workflow_id == workflow_id)
        result = await self.session.execute(statement)
        step = result.scalar_one_or_none()
        if step is None:
            raise WorkflowNotFound(step_id)
        return step

    async def ready_steps(self, workflow_id: str) -> list[WorkflowStep]:
        steps = await self.list_steps(workflow_id)
        result = await self.session.execute(
            select(WorkflowStepDependency).where(
                WorkflowStepDependency.step_id.in_([step.id for step in steps])
            )
        ) if steps else None
        dependencies = list(result.scalars().all()) if result is not None else []
        statuses = {step.id: step.status for step in steps}
        dependency_ids: dict[str, list[str]] = {}
        for dependency in dependencies:
            dependency_ids.setdefault(dependency.step_id, []).append(dependency.depends_on_step_id)
        return [
            step
            for step in steps
            if step.status == StepStatus.PENDING.value
            and all(statuses.get(dep_id) == StepStatus.COMPLETED.value for dep_id in dependency_ids.get(step.id, []))
        ]

    async def cancel_blocked_steps(self, workflow_id: str) -> int:
        """Recursively terminate pending DAG branches whose dependencies cannot succeed."""
        cancelled = 0
        blocking_statuses = {
            StepStatus.FAILED.value,
            StepStatus.DEAD_LETTERED.value,
            StepStatus.CANCELLED.value,
        }
        while True:
            steps = await self.list_steps(workflow_id)
            if not steps:
                return cancelled
            result = await self.session.execute(
                select(WorkflowStepDependency).where(
                    WorkflowStepDependency.step_id.in_([step.id for step in steps])
                )
            )
            dependencies = list(result.scalars().all())
            statuses = {step.id: step.status for step in steps}
            blocked_ids = {
                dependency.step_id
                for dependency in dependencies
                if statuses.get(dependency.depends_on_step_id) in blocking_statuses
            }
            changed_this_round = 0
            for step in steps:
                if step.id in blocked_ids and step.status == StepStatus.PENDING.value:
                    changed = await self.transition_step(
                        step,
                        StepStatus.CANCELLED,
                        last_error_code="dependency_failed",
                        last_error_message="A required upstream step did not complete successfully.",
                    )
                    changed_this_round += int(changed)
            cancelled += changed_this_round
            if changed_this_round == 0:
                return cancelled

    async def transition_step(
        self,
        step: WorkflowStep,
        target: StepStatus,
        **extra_values,
    ) -> bool:
        StepStateMachine.transition(step.status, target)
        now = datetime.now(UTC)
        values = {
            "status": target.value,
            "version": step.version + 1,
            "updated_at": now,
            **extra_values,
        }
        if target == StepStatus.QUEUED:
            values["queued_at"] = now
        if target == StepStatus.RUNNING:
            values["started_at"] = now
        if target in {
            StepStatus.COMPLETED,
            StepStatus.FAILED,
            StepStatus.DEAD_LETTERED,
            StepStatus.CANCELLED,
        }:
            values["completed_at"] = now
            values["lease_owner"] = None
            values["lease_expires_at"] = None
        result = await self.session.execute(
            update(WorkflowStep)
            .where(
                WorkflowStep.id == step.id,
                WorkflowStep.status == step.status,
                WorkflowStep.version == step.version,
            )
            .values(**values)
        )
        changed = bool(result.rowcount)
        if changed:
            for key, value in values.items():
                setattr(step, key, value)
            await self.append_event(
                step.workflow_id,
                f"step.{target.value}",
                {"step_id": step.id, "agent": step.agent_intent, "status": target.value},
                step_id=step.id,
            )
        return changed

    async def claim_step(self, step: WorkflowStep, *, worker_id: str, lease_seconds: int) -> bool:
        return await self.transition_step(
            step,
            StepStatus.RUNNING,
            attempt_count=step.attempt_count + 1,
            lease_owner=worker_id,
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
        )

    async def heartbeat_step(self, step_id: str, *, worker_id: str, lease_seconds: int) -> bool:
        result = await self.session.execute(
            update(WorkflowStep)
            .where(
                WorkflowStep.id == step_id,
                WorkflowStep.status == StepStatus.RUNNING.value,
                WorkflowStep.lease_owner == worker_id,
            )
            .values(
                lease_expires_at=datetime.now(UTC) + timedelta(seconds=lease_seconds),
                updated_at=datetime.now(UTC),
            )
        )
        return bool(result.rowcount)

    async def append_event(
        self,
        workflow_id: str,
        event_type: str,
        payload: dict,
        *,
        step_id: str | None = None,
    ) -> WorkflowEventLog:
        event = WorkflowEventLog(
            workflow_id=workflow_id,
            step_id=step_id,
            event_type=event_type,
            payload_json=payload,
        )
        self.session.add(event)
        await self.session.flush()
        return event

    async def list_events(self, workflow_id: str, *, after_id: int = 0, limit: int = 200) -> list[WorkflowEventLog]:
        result = await self.session.execute(
            select(WorkflowEventLog)
            .where(WorkflowEventLog.workflow_id == workflow_id, WorkflowEventLog.id > after_id)
            .order_by(WorkflowEventLog.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def add_artifacts(
        self,
        *,
        workflow: WorkflowRun,
        step: WorkflowStep,
        artifacts: list[AgentArtifact],
    ) -> list[AgentArtifactRecord]:
        records: list[AgentArtifactRecord] = []
        for artifact in artifacts:
            record = AgentArtifactRecord(
                id=str(uuid4()),
                workflow_id=workflow.id,
                step_id=step.id,
                user_id=workflow.user_id,
                name=artifact.name,
                kind=artifact.kind,
                payload_json=artifact.payload,
                schema_version=1,
            )
            self.session.add(record)
            records.append(record)
        await self.session.flush()
        for record in records:
            await self.append_event(
                workflow.id,
                "artifact.created",
                {"artifact_id": record.id, "kind": record.kind, "step_id": step.id},
                step_id=step.id,
            )
        return records

    async def list_artifacts(
        self,
        workflow_id: str,
        *,
        artifact_ids: list[str] | None = None,
    ) -> list[AgentArtifactRecord]:
        statement = select(AgentArtifactRecord).where(AgentArtifactRecord.workflow_id == workflow_id)
        if artifact_ids is not None:
            if not artifact_ids:
                return []
            statement = statement.where(AgentArtifactRecord.id.in_(artifact_ids))
        result = await self.session.execute(statement.order_by(AgentArtifactRecord.created_at))
        return list(result.scalars().all())

    async def dependency_artifact_ids(self, step_id: str) -> list[str]:
        dependency_result = await self.session.execute(
            select(WorkflowStepDependency.depends_on_step_id).where(
                WorkflowStepDependency.step_id == step_id
            )
        )
        dependency_step_ids = list(dependency_result.scalars().all())
        if not dependency_step_ids:
            return []
        artifact_result = await self.session.execute(
            select(AgentArtifactRecord.id).where(AgentArtifactRecord.step_id.in_(dependency_step_ids))
        )
        return list(artifact_result.scalars().all())


class InboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def begin(
        self,
        *,
        consumer_name: str,
        message_id: str,
        workflow_id: str | None,
        step_id: str | None,
    ) -> bool:
        try:
            async with self.session.begin_nested():
                self.session.add(
                    MessageInbox(
                        consumer_name=consumer_name,
                        message_id=message_id,
                        workflow_id=workflow_id,
                        step_id=step_id,
                        status="processing",
                    )
                )
                await self.session.flush()
        except IntegrityError:
            return False
        return True

    async def complete(self, consumer_name: str, message_id: str) -> None:
        await self.session.execute(
            update(MessageInbox)
            .where(
                MessageInbox.consumer_name == consumer_name,
                MessageInbox.message_id == message_id,
            )
            .values(status="processed", processed_at=datetime.now(UTC), error=None)
        )

    async def fail(self, consumer_name: str, message_id: str, error: str, *, dead: bool = False) -> None:
        await self.session.execute(
            update(MessageInbox)
            .where(
                MessageInbox.consumer_name == consumer_name,
                MessageInbox.message_id == message_id,
            )
            .values(
                status="dead_lettered" if dead else "failed",
                processed_at=datetime.now(UTC),
                error=error[:4000],
            )
        )
