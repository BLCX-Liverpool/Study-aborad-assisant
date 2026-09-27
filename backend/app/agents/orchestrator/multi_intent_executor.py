from datetime import UTC, datetime, timedelta

from app.schemas.common import PlannedTask
from app.schemas.execution import ExecutionStep, MultiIntentExecutionPlan, MultiIntentExecutionRequest
from app.schemas.planner import PlannerOutput, ReminderDraft
from app.schemas.router import StructuredIntent


class MultiIntentExecutionPlanner:
    """Build an executable plan from structured router intents.

    Calendar writes are intentionally not performed here. Calendar-like requests
    become local planning tasks plus email reminder drafts.
    """

    def plan(self, request: MultiIntentExecutionRequest) -> MultiIntentExecutionPlan:
        if len(request.structured_intents) <= 1:
            return MultiIntentExecutionPlan(
                summary="No multi-intent execution plan was needed.",
                steps=[],
                assumptions=["Router returned a single structured intent."],
            )

        executable_intents = _select_executable_intents(request.structured_intents)
        if len(executable_intents) <= 1:
            return MultiIntentExecutionPlan(
                summary="No multi-intent execution plan was needed after confidence and dependency gating.",
                steps=[],
                assumptions=[
                    "Router returned multiple structured intents, but only one passed execution gating."
                ],
            )
        steps = [
            _step_for_intent(index=index, intent=intent, agent_inputs=request.agent_inputs)
            for index, intent in executable_intents
        ]
        planner_output = _planner_output_for_calendar(request)
        email_reminders = planner_output.reminders if planner_output else []
        unsupported = [
            intent.name
            for _, intent in executable_intents
            if intent.name not in SUPPORTED_INTENT_NAMES
        ]
        return MultiIntentExecutionPlan(
            summary=_summary(steps, planner_output, unsupported),
            steps=steps,
            planner_output=planner_output,
            email_reminder_drafts=email_reminders,
            assumptions=[
                "Execution planner uses router structured intents and dependency metadata.",
                "Calendar provider is not connected; meeting-like actions are converted to local tasks and email reminder drafts.",
            ],
            unsupported_intents=unsupported,
        )


SUPPORTED_INTENT_NAMES = {
    "assignment.analyze",
    "calendar.query_availability",
    "calendar.create_event",
    "email.draft",
    "finance.review_budget",
    "fitness.create_plan",
    "general_chat.respond",
    "notice.parse_actions",
    "planner.create_or_update_plan",
    "social_content.create_drafts",
    "travel.plan",
    "wellbeing.support",
}


def _step_for_intent(index: int, intent: StructuredIntent, agent_inputs: dict[str, dict]) -> ExecutionStep:
    slots = _merged_slots(intent, agent_inputs)
    missing_slots = _resolved_missing_slots(intent, slots)
    if missing_slots:
        status = "needs_input"
        result = "Missing required slots; execution is paused for clarification."
    elif intent.name == "calendar.query_availability":
        status = "skipped"
        result = "Calendar provider is not connected; availability was not queried."
    elif intent.name == "calendar.create_event":
        status = "planned"
        result = "Prepared local planning task and email reminder draft instead of writing a calendar event."
    elif intent.name in SUPPORTED_INTENT_NAMES:
        status = "planned"
        result = f"Prepared worker execution step for {intent.agent_intent}."
    else:
        status = "blocked"
        result = "No executor is registered for this structured intent yet."
    return ExecutionStep(
        index=index,
        intent_name=intent.name,
        agent_intent=intent.agent_intent,
        status=status,
        depends_on=intent.depends_on,
        condition=intent.condition,
        slots=slots,
        missing_slots=missing_slots,
        result_summary=result,
    )


def _planner_output_for_calendar(request: MultiIntentExecutionRequest) -> PlannerOutput | None:
    create_intents = [
        intent for intent in request.structured_intents if intent.name == "calendar.create_event"
    ]
    if not create_intents:
        return None
    tasks: list[PlannedTask] = []
    reminders: list[ReminderDraft] = []
    for intent in create_intents:
        event_name = intent.slots.get("event_name") or "待确认会议"
        date_label = intent.slots.get("date") or _paired_query_slot(request.structured_intents, "date") or "待确认日期"
        time_label = intent.slots.get("time_range") or _paired_query_slot(request.structured_intents, "time_range") or "待确认时间"
        remind_at = datetime.now(UTC) + timedelta(hours=1)
        task_title = f"安排会议：{event_name}"
        tasks.append(
            PlannedTask(
                title=task_title,
                description=(
                    f"根据多意图请求创建会议准备任务。目标时间：{date_label} {time_label}。"
                    "由于未接入 Calendar provider，本阶段通过任务和邮件提醒草稿承接。"
                ),
                source_type="multi_intent_calendar",
                estimated_minutes=20,
                priority="medium",
            )
        )
        reminders.append(
            ReminderDraft(
                title=f"邮件提醒：确认{event_name}",
                remind_at=remind_at,
                channel="email",
                task_title=task_title,
            )
        )
    return PlannerOutput(
        tasks=tasks,
        events=[],
        reminders=reminders,
        conflicts=[],
        assumptions=["Calendar provider is bypassed; email reminder drafts are prepared instead."],
    )


def _paired_query_slot(intents: list[StructuredIntent], slot_name: str) -> str | None:
    for intent in intents:
        if intent.name == "calendar.query_availability" and slot_name in intent.slots:
            return str(intent.slots[slot_name])
    return None


def _select_executable_intents(intents: list[StructuredIntent]) -> list[tuple[int, StructuredIntent]]:
    selected: list[tuple[int, StructuredIntent]] = []
    for index, intent in enumerate(intents):
        if index == 0 or intent.depends_on or intent.condition:
            selected.append((index, intent))
            continue
        if intent.confidence >= 0.65:
            selected.append((index, intent))
            continue
        if intent.slots:
            selected.append((index, intent))
    return selected


INPUT_KEY_BY_AGENT_INTENT = {
    "assignment": "assignment",
    "email": "email",
    "finance": "finance",
    "fitness": "fitness",
    "notice_action": "notice",
    "social_content": "social_content",
    "task_planning": "planner",
    "travel": "travel",
    "wellbeing": "wellbeing",
}


def _merged_slots(intent: StructuredIntent, agent_inputs: dict[str, dict]) -> dict:
    input_key = INPUT_KEY_BY_AGENT_INTENT.get(intent.agent_intent, intent.agent_intent)
    input_payload = agent_inputs.get(input_key, {})
    return {**intent.slots, **input_payload}


def _resolved_missing_slots(intent: StructuredIntent, slots: dict) -> list[str]:
    return [slot for slot in intent.missing_slots if slot not in slots or slots.get(slot) in {None, ""}]


def _summary(
    steps: list[ExecutionStep],
    planner_output: PlannerOutput | None,
    unsupported: list[str],
) -> str:
    planned = len([step for step in steps if step.status in {"planned", "completed", "skipped"}])
    if planner_output:
        return f"Prepared {planned} execution step(s), {len(planner_output.tasks)} task(s), and {len(planner_output.reminders)} email reminder draft(s)."
    if unsupported:
        return f"Prepared {planned} execution step(s); {len(unsupported)} intent(s) still need an executor."
    return f"Prepared {planned} execution step(s)."
