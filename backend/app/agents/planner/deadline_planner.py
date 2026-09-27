from datetime import UTC, datetime, timedelta

from app.schemas.assignment import AssignmentAnalysis
from app.schemas.common import EvidenceRef, PlannedTask
from app.schemas.planner import PlannerOutput


DEFAULT_TASKS = [
    ("Understand requirements", 9, 90),
    ("Research sources and collect evidence", 7, 180),
    ("Create outline and choose idea", 5, 120),
    ("Draft assignment", 3, 240),
    ("Review against marking criteria", 1, 120),
    ("Prepare and submit", 0, 60),
]


class AssignmentDeadlinePlanner:
    def plan(
        self,
        assignment: AssignmentAnalysis,
        source_id: str | None = None,
    ) -> PlannerOutput:
        assumptions: list[str] = []

        if assignment.action_plan:
            tasks = [
                task.model_copy(
                    update={
                        "source_type": task.source_type or "assignment",
                        "source_id": task.source_id or source_id,
                    }
                )
                for task in assignment.action_plan
            ]
            assumptions.append("Used action_plan from AssignmentAnalysis.")
            return PlannerOutput(tasks=tasks, assumptions=assumptions)

        if assignment.deadline is None:
            assumptions.append("Assignment deadline is missing; generated only an initial review task.")
            return PlannerOutput(
                tasks=[
                    PlannedTask(
                        title=_task_title(assignment, "Review assignment requirements"),
                        description="Review extracted requirements and fill missing information before scheduling.",
                        source_type="assignment",
                        source_id=source_id,
                        priority="high",
                        estimated_minutes=90,
                        evidence=_collect_evidence(assignment),
                    )
                ],
                assumptions=assumptions,
            )

        deadline = _ensure_aware(assignment.deadline)
        tasks: list[PlannedTask] = []
        evidence = _collect_evidence(assignment)

        for label, days_before, estimated_minutes in DEFAULT_TASKS:
            task_deadline = deadline - timedelta(days=days_before)
            if task_deadline > deadline:
                task_deadline = deadline
            start_time = task_deadline - timedelta(minutes=estimated_minutes)
            tasks.append(
                PlannedTask(
                    title=_task_title(assignment, label),
                    description=_task_description(label, assignment),
                    source_type="assignment",
                    source_id=source_id,
                    start_time=start_time,
                    deadline=task_deadline,
                    estimated_minutes=estimated_minutes,
                    priority="urgent" if days_before <= 1 else "high",
                    evidence=evidence,
                )
            )

        assumptions.append("Generated default coursework timeline from assignment deadline.")
        return PlannerOutput(tasks=tasks, assumptions=assumptions)


def _task_title(assignment: AssignmentAnalysis, label: str) -> str:
    prefix = assignment.course_code or assignment.title or "Assignment"
    return f"{prefix}: {label}"


def _task_description(label: str, assignment: AssignmentAnalysis) -> str:
    if label == "Understand requirements":
        return "Read objective, deliverables, constraints, and missing information."
    if label == "Research sources and collect evidence":
        return "Use extracted research queries and source requirements to collect supporting material."
    if label == "Create outline and choose idea":
        return "Select one feasible idea and map it to the required assignment structure."
    if label == "Draft assignment":
        return "Create the main draft based on the suggested structure and marking criteria."
    if label == "Review against marking criteria":
        return "Check the draft against marking criteria, constraints, word limit, and evidence requirements."
    return "Prepare final files and submit before the deadline."


def _collect_evidence(assignment: AssignmentAnalysis) -> list[EvidenceRef]:
    evidence: list[EvidenceRef] = []
    for requirement in [*assignment.marking_criteria, *assignment.constraints]:
        evidence.extend(requirement.evidence)
    evidence.extend(assignment.research_sources)
    return evidence


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value

