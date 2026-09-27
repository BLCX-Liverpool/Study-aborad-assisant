from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.agents.assignment.extractor import AssignmentRequirementExtractor
from app.agents.assignment.service import AssignmentAnalysisService
from app.agents.assignment.verifier import AssignmentVerifier
from app.agents.email.draft_generator import EmailDraftGenerator
from app.agents.email.service import EmailAgentService
from app.agents.finance.service import FinanceAgentService
from app.agents.fitness.service import FitnessAgentService
from app.agents.notice.llm_extractor import LlmNoticeExtractor
from app.agents.notice.parser import NoticeActionParser
from app.agents.planner.service import TaskPlannerService
from app.agents.social_content.llm_generator import LlmSocialCopyGenerator
from app.agents.social_content.service import SocialContentAgentService
from app.agents.travel.service import TravelAgentService
from app.agents.wellbeing.service import WellbeingAgentService
from app.core.llm import get_stage_llm_client
from app.documents.parser import DoclingDocumentParser
from app.schemas.execution import ExecutionStep
from app.schemas.action import NoticeParseRequest
from app.schemas.assignment import AssignmentAnalysis
from app.schemas.chat import AgentArtifact, ChatRequest
from app.schemas.email import EmailDraftRequest
from app.schemas.finance import FinancePlanRequest
from app.schemas.fitness import FitnessPlanRequest
from app.schemas.planner import AssignmentPlanningRequest, GlobalPlanningRequest
from app.schemas.router import Intent
from app.schemas.social_content import SocialContentRequest
from app.schemas.travel import TravelPlanRequest
from app.schemas.wellbeing import WellbeingSupportRequest


class WorkerAgentSpec(BaseModel):
    intent: Intent
    input_key: str | None = None
    input_schema: str
    output_artifact_kind: str | None = None
    required_tools: list[str] = Field(default_factory=list)
    missing_information_contract: list[str] = Field(default_factory=list)
    memory_namespaces: list[str] = Field(default_factory=list)


class WorkerContext(BaseModel):
    request: ChatRequest
    existing_artifacts: list[AgentArtifact] = Field(default_factory=list)
    execution_step: ExecutionStep | None = None
    tool_statuses: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)


class WorkerRunResult(BaseModel):
    final_response: str = ""
    artifacts: list[AgentArtifact] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    trace_events: list[dict[str, Any]] = Field(default_factory=list)


class WorkerAgent(Protocol):
    spec: WorkerAgentSpec

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        ...


class WorkerRegistry:
    def __init__(self, workers: list[WorkerAgent] | None = None) -> None:
        self._workers: dict[Intent, WorkerAgent] = {}
        for worker in workers or build_default_workers():
            self.register(worker)

    def register(self, worker: WorkerAgent) -> None:
        self._workers[worker.spec.intent] = worker

    def get(self, intent: Intent) -> WorkerAgent | None:
        return self._workers.get(intent)

    def list_specs(self) -> list[WorkerAgentSpec]:
        return [worker.spec for worker in self._workers.values()]


class WellbeingWorker:
    spec = WorkerAgentSpec(
        intent="wellbeing",
        input_key="wellbeing",
        input_schema="WellbeingSupportRequest",
        output_artifact_kind="wellbeing_support",
        memory_namespaces=["wellbeing"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        payload = {
            "user_id": context.request.user_id,
            "message": context.request.message,
            **context.request.agent_inputs.get("wellbeing", {}),
        }
        support_request = WellbeingSupportRequest.model_validate(payload)
        response = WellbeingAgentService().support(support_request)
        return WorkerRunResult(
            final_response=response.supportive_message,
            artifacts=[
                AgentArtifact(name="Wellbeing Support", kind="wellbeing_support", payload=response.model_dump())
            ],
            next_actions=response.crisis_guidance if response.safety.should_escalate else [],
            trace_events=[
                {"name": "worker.completed", "payload": {"agent": "wellbeing", "risk_level": response.safety.risk_level}}
            ],
        )


class TravelWorker:
    spec = WorkerAgentSpec(
        intent="travel",
        input_key="travel",
        input_schema="TravelPlanRequest",
        output_artifact_kind="travel_plan",
        required_tools=["weather.lookup", "travel.maps.directions", "travel.maps.places"],
        memory_namespaces=["travel"],
        missing_information_contract=["travel.origin", "travel.destination"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        payload = _with_user_id(context.request.agent_inputs.get("travel"), context.request.user_id)
        if not payload or "origin" not in payload or "destination" not in payload:
            missing = ["travel.origin", "travel.destination"]
            return WorkerRunResult(
                missing_information=missing,
                next_actions=["Provide travel.origin and travel.destination in agent_inputs.travel."],
                trace_events=[{"name": "worker.needs_input", "payload": {"agent": "travel", "missing": missing}}],
            )

        travel_request = TravelPlanRequest.model_validate(payload)
        plan = await TravelAgentService().plan_async(travel_request)
        return WorkerRunResult(
            final_response=plan.summary,
            artifacts=[AgentArtifact(name="Travel Plan", kind="travel_plan", payload=plan.model_dump())],
            next_actions=plan.booking_questions,
            trace_events=[{"name": "worker.completed", "payload": {"agent": "travel", "tasks": len(plan.checklist)}}],
        )


class FinanceWorker:
    spec = WorkerAgentSpec(
        intent="finance",
        input_key="finance",
        input_schema="FinancePlanRequest",
        output_artifact_kind="finance_plan",
        memory_namespaces=["finance"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        payload = _with_user_id(context.request.agent_inputs.get("finance"), context.request.user_id)
        if not payload:
            payload = {"user_id": context.request.user_id, "notes": context.request.message}
        finance_request = FinancePlanRequest.model_validate(payload)
        plan = FinanceAgentService().plan_budget(finance_request)
        return WorkerRunResult(
            final_response=f"已生成预算分析：预计月结余为 {plan.currency} {plan.projected_monthly_balance:.2f}。",
            artifacts=[AgentArtifact(name="Finance Budget", kind="finance_plan", payload=plan.model_dump())],
            next_actions=[item.title for item in plan.action_items[:3]],
            trace_events=[
                {
                    "name": "worker.completed",
                    "payload": {
                        "agent": "finance",
                        "monthly_expense": plan.total_monthly_expense,
                        "monthly_balance": plan.projected_monthly_balance,
                    },
                }
            ],
        )


class FitnessWorker:
    spec = WorkerAgentSpec(
        intent="fitness",
        input_key="fitness",
        input_schema="FitnessPlanRequest",
        output_artifact_kind="fitness_plan",
        memory_namespaces=["fitness"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        payload = _with_user_id(context.request.agent_inputs.get("fitness"), context.request.user_id)
        if not payload:
            payload = {"user_id": context.request.user_id, "notes": context.request.message}
        fitness_request = FitnessPlanRequest.model_validate(payload)
        plan = FitnessAgentService().create_plan(fitness_request)
        return WorkerRunResult(
            final_response=f"已生成健身计划：{len(plan.workout_days)} 个训练日，{len(plan.habit_tasks)} 个习惯任务。",
            artifacts=[AgentArtifact(name="Fitness Plan", kind="fitness_plan", payload=plan.model_dump())],
            missing_information=plan.missing_information,
            next_actions=[item.title for item in plan.habit_tasks[:3]],
            trace_events=[
                {
                    "name": "worker.completed",
                    "payload": {
                        "agent": "fitness",
                        "workout_days": len(plan.workout_days),
                        "habits": len(plan.habit_tasks),
                    },
                }
            ],
        )


class SocialContentWorker:
    spec = WorkerAgentSpec(
        intent="social_content",
        input_key="social_content",
        input_schema="SocialContentRequest",
        output_artifact_kind="social_content",
        memory_namespaces=["social_content"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        payload = _with_user_id(context.request.agent_inputs.get("social_content"), context.request.user_id)
        if not payload:
            payload = {"user_id": context.request.user_id, "topic": context.request.message}
        social_request = SocialContentRequest.model_validate(payload)
        output = await SocialContentAgentService(
            llm_generator=LlmSocialCopyGenerator(get_stage_llm_client("social"))
        ).create_content_async(social_request)
        return WorkerRunResult(
            final_response=output.summary,
            artifacts=[AgentArtifact(name="Social Content Draft", kind="social_content", payload=output.model_dump())],
            next_actions=output.safety.issues,
            trace_events=[
                {
                    "name": "worker.completed",
                    "payload": {
                        "agent": "social_content",
                        "drafts": len(output.drafts),
                        "safety": output.safety.level,
                    },
                }
            ],
        )


class TaskPlanningWorker:
    spec = WorkerAgentSpec(
        intent="task_planning",
        input_key="planner",
        input_schema="AssignmentPlanningRequest | MultiIntentExecutionPlan",
        output_artifact_kind="planner_output",
        required_tools=["reminder.draft", "calendar.event.draft"],
        memory_namespaces=["planner"],
        missing_information_contract=["planner.assignment"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        execution_artifact = next(
            (artifact for artifact in context.existing_artifacts if artifact.kind == "multi_intent_execution"),
            None,
        )
        if execution_artifact is not None:
            payload = execution_artifact.payload
            if payload.get("planner_output"):
                return WorkerRunResult(
                    final_response=payload.get("summary", "已生成多意图执行计划。"),
                    artifacts=[
                        AgentArtifact(
                            name="Task Plan",
                            kind="planner_output",
                            payload=payload["planner_output"],
                        )
                    ],
                    next_actions=[reminder["title"] for reminder in payload.get("email_reminder_drafts", [])[:3]],
                    trace_events=[
                        {
                            "name": "worker.completed",
                            "payload": {
                                "agent": "multi_intent_executor",
                                "tasks": len(payload["planner_output"].get("tasks", [])),
                                "reminders": len(payload.get("email_reminder_drafts", [])),
                            },
                        }
                    ],
                )

        payload = _with_user_id(context.request.agent_inputs.get("planner"), context.request.user_id)
        if not payload or "assignment" not in payload:
            missing = ["planner.assignment"]
            return WorkerRunResult(
                missing_information=missing,
                next_actions=[
                    "Current Task Planner requires planner.assignment. Global PlanningItem support is Phase 9."
                ],
                trace_events=[{"name": "worker.needs_input", "payload": {"agent": "planner", "missing": missing}}],
            )

        planning_request = AssignmentPlanningRequest.model_validate(payload)
        plan = TaskPlannerService().plan_assignment(planning_request)
        return WorkerRunResult(
            final_response=f"已生成学习计划：{len(plan.tasks)} 个任务，{len(plan.reminders)} 个提醒草稿。",
            artifacts=[AgentArtifact(name="Task Plan", kind="planner_output", payload=plan.model_dump())],
            trace_events=[
                {
                    "name": "worker.completed",
                    "payload": {"agent": "planner", "tasks": len(plan.tasks), "reminders": len(plan.reminders)},
                }
            ],
        )


class EmailWorker:
    spec = WorkerAgentSpec(
        intent="email",
        input_key="email",
        input_schema="EmailDraftRequest",
        output_artifact_kind="email_draft",
        memory_namespaces=["email"],
        missing_information_contract=["email.llm_or_required_context"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        payload = _with_user_id(context.request.agent_inputs.get("email"), context.request.user_id)
        if not payload:
            payload = {"user_id": context.request.user_id, "purpose": context.request.message}
        try:
            draft_request = EmailDraftRequest.model_validate(payload)
            service = EmailAgentService(draft_generator=EmailDraftGenerator(get_stage_llm_client("email")))
            response = await service.create_draft(draft_request)
        except Exception as exc:
            return WorkerRunResult(
                final_response="邮件草稿需要 LLM 配置和更完整的邮件上下文；当前没有执行发送动作。",
                missing_information=["email.llm_or_required_context"],
                next_actions=["Configure LLM_API_KEY and provide email context before generating a draft."],
                trace_events=[{"name": "worker.failed", "payload": {"agent": "email", "error": str(exc)}}],
            )

        return WorkerRunResult(
            final_response="已生成邮件草稿；发送动作仍需要用户显式审批。",
            artifacts=[AgentArtifact(name="Email Draft", kind="email_draft", payload=response.model_dump())],
            trace_events=[{"name": "worker.completed", "payload": {"agent": "email", "requires_approval": True}}],
        )


class AssignmentWorker:
    spec = WorkerAgentSpec(
        intent="assignment",
        input_key="assignment",
        input_schema="AssignmentAnalysisRequest",
        output_artifact_kind="assignment_analysis",
        required_tools=["research.arxiv.search", "research.web.search", "browser.mcp.search_extract"],
        memory_namespaces=["assignment"],
        missing_information_contract=["assignment.source_path", "assignment.file_id"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        payload = _with_user_id(context.request.agent_inputs.get("assignment"), context.request.user_id)
        if not payload or "source_path" not in payload or "file_id" not in payload:
            missing = ["assignment.source_path", "assignment.file_id"]
            return WorkerRunResult(
                missing_information=missing,
                next_actions=[
                    "Provide assignment.source_path and assignment.file_id, or use RAG indexing before analysis."
                ],
                trace_events=[{"name": "worker.needs_input", "payload": {"agent": "assignment", "missing": missing}}],
            )

        try:
            service = AssignmentAnalysisService(
                parser=DoclingDocumentParser(),
                extractor=AssignmentRequirementExtractor(get_stage_llm_client("assignment")),
                verifier=AssignmentVerifier(),
            )
            result = await service.analyze_file(
                source_path=Path(payload["source_path"]),
                file_id=payload["file_id"],
                source_name=payload.get("source_name"),
                mime_type=payload.get("mime_type"),
            )
        except Exception as exc:
            return WorkerRunResult(
                final_response="作业分析没有完成；请确认文件路径、解析依赖和 LLM 配置。",
                trace_events=[{"name": "worker.failed", "payload": {"agent": "assignment", "error": str(exc)}}],
            )

        artifact_payload = {
            "analysis": result.analysis.model_dump(),
            "verification": result.verification.model_dump(),
        }
        return WorkerRunResult(
            final_response="已完成作业要求分析，并生成了 evidence-aware 的结构化结果。",
            artifacts=[AgentArtifact(name="Assignment Analysis", kind="assignment_analysis", payload=artifact_payload)],
            trace_events=[{"name": "worker.completed", "payload": {"agent": "assignment"}}],
        )


class NoticeActionWorker:
    spec = WorkerAgentSpec(
        intent="notice_action",
        input_key="notice",
        input_schema="NoticeParseRequest",
        output_artifact_kind="notice_parse",
        required_tools=["reminder.draft", "calendar.event.draft"],
        memory_namespaces=["planner", "email", "finance"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        payload = {
            "user_id": context.request.user_id,
            "text": context.request.message,
            **context.request.agent_inputs.get("notice", {}),
        }
        parsed = await NoticeActionParser(
            llm_extractor=LlmNoticeExtractor(get_stage_llm_client("notice"))
        ).parse_async(NoticeParseRequest.model_validate(payload))

        artifacts = [AgentArtifact(name="Notice Actions", kind="notice_parse", payload=parsed.model_dump())]
        trace_events = [{"name": "worker.completed", "payload": {"agent": "notice_action", "items": len(parsed.action_items)}}]

        if parsed.action_items:
            plan = TaskPlannerService().plan_global(
                GlobalPlanningRequest(
                    user_id=context.request.user_id,
                    items=parsed.action_items,
                    existing_blocks=[],
                )
            )
            artifacts.append(AgentArtifact(name="Global Plan", kind="planner_output", payload=plan.model_dump()))
            trace_events.append(
                {
                    "name": "worker.completed",
                    "payload": {"agent": "global_planner", "tasks": len(plan.tasks), "events": len(plan.events)},
                }
            )

        return WorkerRunResult(
            final_response=f"已从通知中识别出 {len(parsed.action_items)} 个待办/事件，并生成了初步计划。",
            artifacts=artifacts,
            missing_information=parsed.missing_information,
            trace_events=trace_events,
        )


class GeneralChatWorker:
    spec = WorkerAgentSpec(
        intent="general_chat",
        input_schema="ChatRequest",
        output_artifact_kind=None,
        memory_namespaces=["general"],
    )

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        return WorkerRunResult(
            final_response="我已经收到你的问题。当前统一入口会优先路由到具体 Agent；普通聊天将在多轮对话阶段补强。",
            trace_events=[{"name": "orchestrator.general_chat", "payload": {}}],
        )


def build_default_workers() -> list[WorkerAgent]:
    return [
        WellbeingWorker(),
        TravelWorker(),
        FinanceWorker(),
        FitnessWorker(),
        SocialContentWorker(),
        TaskPlanningWorker(),
        EmailWorker(),
        AssignmentWorker(),
        NoticeActionWorker(),
        GeneralChatWorker(),
    ]


def not_implemented_result(intent: Intent) -> WorkerRunResult:
    return WorkerRunResult(
        final_response=f"{intent} 已在规划中，但当前阶段尚未实现运行时。",
        missing_information=[f"{intent}.runtime"],
        next_actions=[f"{intent} is listed in the plan but will be implemented in a later phase."],
        trace_events=[{"name": "worker.not_implemented", "payload": {"intent": intent}}],
    )


def _with_user_id(payload: dict[str, Any] | None, user_id: str) -> dict[str, Any] | None:
    if payload is None:
        return None
    return {"user_id": user_id, **payload}
