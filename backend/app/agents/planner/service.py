from app.agents.planner.conflicts import ConflictChecker
from app.agents.planner.deadline_planner import AssignmentDeadlinePlanner
from app.agents.planner.global_planner import GlobalPlanner
from app.agents.planner.reminders import ReminderScheduler
from app.core.llm import get_stage_llm_client
from app.schemas.planner import AssignmentPlanningRequest, GlobalPlanningRequest, PlannerOutput


class TaskPlannerService:
    def __init__(
        self,
        deadline_planner: AssignmentDeadlinePlanner | None = None,
        global_planner: GlobalPlanner | None = None,
        conflict_checker: ConflictChecker | None = None,
        reminder_scheduler: ReminderScheduler | None = None,
    ) -> None:
        self.deadline_planner = deadline_planner or AssignmentDeadlinePlanner()
        self.global_planner = global_planner or GlobalPlanner(get_stage_llm_client("planner"))
        self.conflict_checker = conflict_checker or ConflictChecker()
        self.reminder_scheduler = reminder_scheduler or ReminderScheduler()

    def plan_assignment(self, request: AssignmentPlanningRequest) -> PlannerOutput:
        plan = self.deadline_planner.plan(
            assignment=request.assignment,
            source_id=request.source_id,
        )
        conflict_findings = self.conflict_checker.check(
            tasks=plan.tasks,
            events=plan.events,
            existing_blocks=request.existing_blocks,
        )
        reminders = self.reminder_scheduler.create_reminders(
            tasks=plan.tasks,
            events=plan.events,
        )
        return plan.model_copy(
            update={
                "reminders": reminders,
                "conflicts": [finding.message for finding in conflict_findings],
            }
        )

    async def plan_global(self, request: GlobalPlanningRequest) -> PlannerOutput:
        plan = await self.global_planner.plan(request)
        conflict_findings = self.conflict_checker.check(
            tasks=plan.tasks,
            events=plan.events,
            existing_blocks=request.existing_blocks,
        )
        reminders = self.reminder_scheduler.create_reminders(
            tasks=plan.tasks,
            events=plan.events,
        )
        return plan.model_copy(
            update={
                "reminders": reminders,
                "conflicts": [finding.message for finding in conflict_findings],
            }
        )
