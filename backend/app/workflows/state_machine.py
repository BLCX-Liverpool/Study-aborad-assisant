from enum import StrEnum


class InvalidStateTransition(ValueError):
    pass


class WorkflowStatus(StrEnum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    PARTIAL_FAILED = "partial_failed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    DEAD_LETTERED = "dead_lettered"


class StepStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    NEEDS_INPUT = "needs_input"
    RETRY_WAIT = "retry_wait"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"
    CANCELLED = "cancelled"


WORKFLOW_TRANSITIONS: dict[WorkflowStatus, set[WorkflowStatus]] = {
    WorkflowStatus.CREATED: {WorkflowStatus.PLANNING, WorkflowStatus.CANCEL_REQUESTED},
    WorkflowStatus.PLANNING: {
        WorkflowStatus.RUNNING,
        WorkflowStatus.WAITING_INPUT,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCEL_REQUESTED,
        WorkflowStatus.DEAD_LETTERED,
    },
    WorkflowStatus.RUNNING: {
        WorkflowStatus.WAITING_INPUT,
        WorkflowStatus.COMPLETED,
        WorkflowStatus.PARTIAL_FAILED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCEL_REQUESTED,
        WorkflowStatus.DEAD_LETTERED,
    },
    WorkflowStatus.WAITING_INPUT: {
        WorkflowStatus.RUNNING,
        WorkflowStatus.CANCEL_REQUESTED,
        WorkflowStatus.FAILED,
    },
    WorkflowStatus.CANCEL_REQUESTED: {WorkflowStatus.CANCELLED},
    WorkflowStatus.PARTIAL_FAILED: {WorkflowStatus.RUNNING, WorkflowStatus.CANCEL_REQUESTED},
    WorkflowStatus.COMPLETED: set(),
    WorkflowStatus.FAILED: {WorkflowStatus.RUNNING},
    WorkflowStatus.CANCELLED: set(),
    WorkflowStatus.DEAD_LETTERED: {WorkflowStatus.RUNNING},
}


STEP_TRANSITIONS: dict[StepStatus, set[StepStatus]] = {
    StepStatus.PENDING: {StepStatus.QUEUED, StepStatus.CANCELLED},
    StepStatus.QUEUED: {StepStatus.RUNNING, StepStatus.CANCELLED},
    StepStatus.RUNNING: {
        StepStatus.COMPLETED,
        StepStatus.NEEDS_INPUT,
        StepStatus.RETRY_WAIT,
        StepStatus.FAILED,
        StepStatus.DEAD_LETTERED,
        StepStatus.CANCELLED,
    },
    StepStatus.NEEDS_INPUT: {StepStatus.PENDING, StepStatus.CANCELLED},
    StepStatus.RETRY_WAIT: {StepStatus.QUEUED, StepStatus.DEAD_LETTERED, StepStatus.CANCELLED},
    StepStatus.FAILED: {StepStatus.QUEUED, StepStatus.DEAD_LETTERED},
    StepStatus.COMPLETED: set(),
    StepStatus.DEAD_LETTERED: {StepStatus.QUEUED},
    StepStatus.CANCELLED: set(),
}


class WorkflowStateMachine:
    @staticmethod
    def transition(current: str | WorkflowStatus, target: str | WorkflowStatus) -> WorkflowStatus:
        current_status = WorkflowStatus(current)
        target_status = WorkflowStatus(target)
        if target_status not in WORKFLOW_TRANSITIONS[current_status]:
            raise InvalidStateTransition(f"Workflow cannot transition from {current_status} to {target_status}")
        return target_status


class StepStateMachine:
    @staticmethod
    def transition(current: str | StepStatus, target: str | StepStatus) -> StepStatus:
        current_status = StepStatus(current)
        target_status = StepStatus(target)
        if target_status not in STEP_TRANSITIONS[current_status]:
            raise InvalidStateTransition(f"Step cannot transition from {current_status} to {target_status}")
        return target_status
