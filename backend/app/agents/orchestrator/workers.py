from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from app.agents.assignment.extractor import AssignmentRequirementExtractor
from app.agents.assignment.service import AssignmentAnalysisService
from app.agents.assignment.verifier import AssignmentVerifier
from app.agents.email.draft_generator import EmailDraftGenerator
from app.agents.email.input_extractor import EmailInputExtractor
from app.agents.email.service import EmailAgentService
from app.agents.finance.input_extractor import FinanceInputExtractor
from app.agents.finance.service import FinanceAgentService
from app.agents.fitness.input_extractor import FitnessInputExtractor
from app.agents.fitness.service import FitnessAgentService
from app.agents.notice.llm_extractor import LlmNoticeExtractor
from app.agents.orchestrator.state import AgentScopedState
from app.agents.notice.parser import NoticeActionParser
from app.agents.planner.input_extractor import PlanningInputExtractor
from app.agents.planner.service import TaskPlannerService
from app.agents.research.workflow import AssignmentResearchWorkflow
from app.agents.social_content.input_extractor import SocialContentInputExtractor
from app.agents.social_content.llm_generator import LlmSocialCopyGenerator
from app.agents.social_content.service import SocialContentAgentService
from app.agents.travel.input_extractor import TravelInputExtractor
from app.agents.travel.purpose_classifier import TravelPurposeClassifier
from app.agents.travel.service import TravelAgentService
from app.agents.wellbeing.service import WellbeingAgentService
from app.core.llm import get_stage_llm_client
from app.documents.parser import DoclingDocumentParser
from app.schemas.execution import ExecutionStep
from app.schemas.action import ActionItem, NoticeParseRequest
from app.schemas.assignment import AssignmentAnalysis
from app.schemas.chat import AgentArtifact, ChatRequest
from app.schemas.email import EmailDraftRequest
from app.schemas.finance import FinancePlanRequest
from app.schemas.fitness import FitnessPlanRequest
from app.schemas.memory import MemoryContext
from app.schemas.planner import AssignmentPlanningRequest, GlobalPlanningRequest, ScheduleBlock
from app.schemas.research import ResearchWorkflowRequest
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
    agent_state: AgentScopedState | None = None
    memory_context: MemoryContext | None = None
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

    def __init__(
        self,
        purpose_classifier: TravelPurposeClassifier | None = None,
        input_extractor: TravelInputExtractor | None = None,
    ) -> None:
        self.purpose_classifier = purpose_classifier or TravelPurposeClassifier()
        self.input_extractor = input_extractor or TravelInputExtractor()

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        explicit_payload = _with_user_id(context.request.agent_inputs.get("travel"), context.request.user_id)
        extraction = await self.input_extractor.extract(
            message=context.request.message,
            existing_payload=explicit_payload,
            memory_preferences=_memory_preferences_for(context, ["travel"]),
        )
        payload = _merge_agent_payloads(extraction.payload, explicit_payload, context.request.user_id)
        if context.agent_state is not None:
            context.agent_state.metadata["last_travel_input_extraction"] = extraction.model_dump()
        if context.request.message and "notes" not in payload:
            payload["notes"] = context.request.message
        payload = _merge_memory_preferences(payload, context, ["travel"])
        missing = _travel_missing_information(payload, extraction.missing_information)
        if missing:
            questions = _travel_clarification_questions(missing, extraction.clarification_questions)
            return WorkerRunResult(
                missing_information=missing,
                final_response="需要补充旅行信息后才能生成可靠行程计划：" + "；".join(questions),
                next_actions=questions,
                trace_events=[
                    {
                        "name": "travel.input_needs_clarification",
                        "payload": {
                            "agent": "travel",
                            "missing": missing,
                            "extractor_confidence": extraction.confidence,
                            "recoverable_error": extraction.recoverable_error,
                        },
                    }
                ],
            )

        purpose_classification = None
        if payload.get("purpose") in {None, "", "other"}:
            purpose_classification = await self.purpose_classifier.classify(
                message=context.request.message,
                origin=str(payload["origin"]),
                destination=str(payload["destination"]),
                notes=payload.get("notes"),
                constraints=payload.get("constraints") if isinstance(payload.get("constraints"), list) else [],
            )
            payload["purpose"] = purpose_classification.purpose
            if context.agent_state is not None:
                context.agent_state.metadata["last_purpose_classification"] = purpose_classification.model_dump()

        travel_request = TravelPlanRequest.model_validate(payload)
        plan = await TravelAgentService().plan_async(travel_request)
        trace_events = [
            {
                "name": "worker.completed",
                "payload": {"agent": "travel", "tasks": len(plan.checklist), "purpose": travel_request.purpose},
            }
        ]
        if purpose_classification is not None:
            trace_events.insert(
                0,
                {
                    "name": "travel.purpose_classified",
                    "payload": {
                        "purpose": purpose_classification.purpose,
                        "confidence": purpose_classification.confidence,
                        "source": purpose_classification.source,
                        "recoverable_error": purpose_classification.recoverable_error,
                    },
                },
            )
        return WorkerRunResult(
            final_response=plan.summary,
            artifacts=[AgentArtifact(name="Travel Plan", kind="travel_plan", payload=plan.model_dump())],
            next_actions=plan.booking_questions,
            trace_events=trace_events,
        )


class FinanceWorker:
    spec = WorkerAgentSpec(
        intent="finance",
        input_key="finance",
        input_schema="FinancePlanRequest",
        output_artifact_kind="finance_plan",
        required_tools=["finance.exchange_rate"],
        memory_namespaces=["finance"],
    )

    def __init__(self, input_extractor: FinanceInputExtractor | None = None) -> None:
        self.input_extractor = input_extractor or FinanceInputExtractor()

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        explicit_payload = _with_user_id(context.request.agent_inputs.get("finance"), context.request.user_id)
        extraction = await self.input_extractor.extract(
            message=context.request.message,
            existing_payload=explicit_payload,
            memory_preferences=_memory_preferences_for(context, ["finance"]),
        )
        payload = _merge_finance_payloads(extraction.payload, explicit_payload, context.request.user_id)
        if context.agent_state is not None:
            context.agent_state.metadata["last_finance_input_extraction"] = extraction.model_dump()
        if context.request.message and "notes" not in payload:
            payload["notes"] = context.request.message
        payload = _merge_memory_preferences(payload, context, ["finance"])
        payload = _merge_travel_budget_handoff(payload, context)
        missing_information = _finance_missing_information(payload, extraction.missing_information)
        if missing_information:
            questions = _finance_clarification_questions(missing_information, extraction.clarification_questions)
            return WorkerRunResult(
                final_response="需要补充财务信息后才能生成可靠预算分析：" + "；".join(questions),
                missing_information=missing_information,
                next_actions=questions,
                trace_events=[
                    {
                        "name": "finance.input_needs_clarification",
                        "payload": {
                            "missing_information": missing_information,
                            "extractor_confidence": extraction.confidence,
                            "recoverable_error": extraction.recoverable_error,
                        },
                    }
                ],
            )
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
                        "extracted": bool(extraction.payload),
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

    def __init__(self, input_extractor: FitnessInputExtractor | None = None) -> None:
        self.input_extractor = input_extractor or FitnessInputExtractor()

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        explicit_payload = _with_user_id(context.request.agent_inputs.get("fitness"), context.request.user_id)
        extraction = await self.input_extractor.extract(
            message=context.request.message,
            existing_payload=explicit_payload,
            memory_preferences=_memory_preferences_for(context, ["fitness"]),
        )
        payload = _merge_agent_payloads(extraction.payload, explicit_payload, context.request.user_id)
        if context.agent_state is not None:
            context.agent_state.metadata["last_fitness_input_extraction"] = extraction.model_dump()
        if context.request.message and "notes" not in payload:
            payload["notes"] = context.request.message
        payload = _merge_memory_preferences(payload, context, ["fitness"])
        missing = _fitness_missing_information(payload, extraction.missing_information)
        if missing:
            questions = _fitness_clarification_questions(missing, extraction.clarification_questions)
            return WorkerRunResult(
                final_response="需要补充健身计划信息后才能生成可靠安排：" + "；".join(questions),
                missing_information=missing,
                next_actions=questions,
                trace_events=[
                    {
                        "name": "fitness.input_needs_clarification",
                        "payload": {
                            "agent": "fitness",
                            "missing": missing,
                            "extractor_confidence": extraction.confidence,
                            "recoverable_error": extraction.recoverable_error,
                        },
                    }
                ],
            )
        fitness_request = FitnessPlanRequest.model_validate(payload)
        plan = await FitnessAgentService(llm=get_stage_llm_client("fitness")).create_plan_async(fitness_request)
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

    def __init__(self, input_extractor: SocialContentInputExtractor | None = None) -> None:
        self.input_extractor = input_extractor or SocialContentInputExtractor()

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        explicit_payload = _with_user_id(context.request.agent_inputs.get("social_content"), context.request.user_id)
        extraction = await self.input_extractor.extract(
            message=context.request.message,
            existing_payload=explicit_payload,
            memory_preferences=_memory_preferences_for(context, ["social_content"]),
        )
        payload = _merge_agent_payloads(extraction.payload, explicit_payload, context.request.user_id)
        if context.agent_state is not None:
            context.agent_state.metadata["last_social_content_input_extraction"] = extraction.model_dump()
        if not payload.get("topic"):
            payload["topic"] = context.request.message
        if context.request.message and "notes" not in payload:
            payload["notes"] = context.request.message
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
                        "extracted": bool(extraction.payload),
                        "extractor_confidence": extraction.confidence,
                        "recoverable_error": extraction.recoverable_error,
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

    def __init__(self, input_extractor: PlanningInputExtractor | None = None) -> None:
        self.input_extractor = input_extractor or PlanningInputExtractor()

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
            explicit_planner_payload = payload or {}
            extraction = await self.input_extractor.extract(
                message=context.request.message,
                existing_payload=payload,
                memory_preferences=_memory_preferences_for(context, ["planner"]),
            )
            if context.agent_state is not None:
                context.agent_state.metadata["last_planner_input_extraction"] = extraction.model_dump()
            action_items = _valid_action_items(explicit_planner_payload.get("items") or extraction.items)
            existing_blocks = _valid_schedule_blocks(
                explicit_planner_payload.get("existing_blocks") or extraction.existing_blocks
            )
            missing = _planner_missing_information(action_items, extraction.missing_information)
            if missing:
                questions = _planner_clarification_questions(missing, extraction.clarification_questions)
                return WorkerRunResult(
                    final_response="需要补充任务规划信息后才能生成可靠计划：" + "；".join(questions),
                    missing_information=missing,
                    next_actions=questions,
                    trace_events=[
                        {
                            "name": "planner.input_needs_clarification",
                            "payload": {
                                "agent": "planner",
                                "missing": missing,
                                "extractor_confidence": extraction.confidence,
                                "recoverable_error": extraction.recoverable_error,
                            },
                        }
                    ],
                )
            planning_request = GlobalPlanningRequest(
                user_id=context.request.user_id,
                items=action_items,
                planning_horizon_days=explicit_planner_payload.get("planning_horizon_days")
                or extraction.planning_horizon_days
                or 30,
                existing_blocks=existing_blocks,
                memory_preferences=_memory_preferences_for(context, ["planner"]),
            )
            plan = await TaskPlannerService().plan_global(planning_request)
            return WorkerRunResult(
                final_response=f"已生成全局任务计划：{len(plan.tasks)} 个任务，{len(plan.events)} 个事件，{len(plan.reminders)} 个提醒草稿。",
                artifacts=[AgentArtifact(name="Task Plan", kind="planner_output", payload=plan.model_dump())],
                trace_events=[
                    {
                        "name": "worker.completed",
                        "payload": {
                            "agent": "planner",
                            "mode": "global",
                            "tasks": len(plan.tasks),
                            "events": len(plan.events),
                            "reminders": len(plan.reminders),
                        },
                    }
                ],
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

    def __init__(self, input_extractor: EmailInputExtractor | None = None) -> None:
        self.input_extractor = input_extractor or EmailInputExtractor()

    async def run(self, context: WorkerContext) -> WorkerRunResult:
        explicit_payload = _with_user_id(context.request.agent_inputs.get("email"), context.request.user_id)
        extraction = await self.input_extractor.extract(
            message=context.request.message,
            existing_payload=explicit_payload,
        )
        payload = _merge_agent_payloads(extraction.payload, explicit_payload, context.request.user_id)
        if context.agent_state is not None:
            context.agent_state.metadata["last_email_input_extraction"] = extraction.model_dump()
        if not payload.get("purpose"):
            payload["purpose"] = context.request.message
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
        artifacts = [AgentArtifact(name="Assignment Analysis", kind="assignment_analysis", payload=artifact_payload)]
        next_actions = []
        trace_events = [{"name": "worker.completed", "payload": {"agent": "assignment"}}]
        try:
            research = await AssignmentResearchWorkflow().run(
                ResearchWorkflowRequest(
                    user_id=context.request.user_id,
                    assignment=result.analysis,
                    include_web=False,
                    include_arxiv=True,
                    max_results_per_query=3,
                )
            )
            artifacts.append(
                AgentArtifact(
                    name="ArXiv Paper Candidates",
                    kind="arxiv_source_candidates",
                    payload={
                        "status": "needs_user_selection",
                        "queries": research.queries,
                        "sources": [source.model_dump() for source in research.sources],
                        "assumptions": [
                            *research.assumptions,
                            "Select papers to download and index before using them as assignment evidence.",
                        ],
                    },
                )
            )
            if research.sources:
                next_actions.append("Select ArXiv papers to download, parse, and index into RAG.")
            trace_events.append(
                {
                    "name": "assignment.arxiv_candidates_ready",
                    "payload": {"queries": len(research.queries), "sources": len(research.sources)},
                }
            )
        except Exception as exc:
            next_actions.append("ArXiv candidate search failed; run research search manually or retry later.")
            trace_events.append(
                {
                    "name": "assignment.arxiv_candidates_failed",
                    "payload": {"error": str(exc)},
                }
            )
        return WorkerRunResult(
            final_response="已完成作业要求分析，并生成 ArXiv 论文候选；请选择需要下载并进入 RAG 的论文。",
            artifacts=artifacts,
            next_actions=next_actions,
            trace_events=trace_events,
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
            plan = await TaskPlannerService().plan_global(
                GlobalPlanningRequest(
                    user_id=context.request.user_id,
                    items=parsed.action_items,
                    existing_blocks=[],
                    memory_preferences=_memory_preferences_for(context, ["planner", "finance"]),
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


def _memory_preferences_for(context: WorkerContext, namespaces: list[str]) -> list[str]:
    if context.memory_context is None:
        return []
    allowed = set(namespaces)
    return [
        memory.content
        for memory in context.memory_context.long_term_memories
        if str(memory.namespace) in allowed
    ]


def _merge_memory_preferences(
    payload: dict[str, Any],
    context: WorkerContext,
    namespaces: list[str],
) -> dict[str, Any]:
    preferences = _memory_preferences_for(context, namespaces)
    if not preferences:
        return payload
    existing = payload.get("memory_preferences") or []
    return {**payload, "memory_preferences": [*existing, *preferences]}


def _merge_travel_budget_handoff(payload: dict[str, Any], context: WorkerContext) -> dict[str, Any]:
    existing_items = list(payload.get("travel_budget_items") or [])
    for artifact in context.existing_artifacts:
        if artifact.kind not in {"travel_plan", "travel_itinerary"}:
            continue
        for item in artifact.payload.get("budget_breakdown", []) or []:
            if not isinstance(item, dict):
                continue
            existing_items.append(
                {
                    "category": item.get("category", "travel"),
                    "estimated_amount": item.get("estimated_amount"),
                    "currency": item.get("currency", payload.get("currency", "GBP")),
                    "notes": item.get("notes"),
                    "source": "user_provided" if item.get("source") == "user_provided" else "static_estimate",
                    "confidence": item.get("confidence", 0.5),
                    "trip_name": artifact.name,
                }
            )
    if not existing_items:
        return payload
    return {**payload, "travel_budget_items": existing_items}


def _merge_finance_payloads(
    extracted_payload: dict[str, Any],
    explicit_payload: dict[str, Any] | None,
    user_id: str,
) -> dict[str, Any]:
    return _merge_agent_payloads(extracted_payload, explicit_payload, user_id)


def _merge_agent_payloads(
    extracted_payload: dict[str, Any],
    explicit_payload: dict[str, Any] | None,
    user_id: str,
) -> dict[str, Any]:
    merged = {"user_id": user_id}
    merged.update(extracted_payload or {})
    if explicit_payload:
        for key, value in explicit_payload.items():
            if value is not None and value != "":
                merged[key] = value
    return merged


def _travel_missing_information(payload: dict[str, Any], extractor_missing: list[str]) -> list[str]:
    missing: list[str] = []
    if not payload.get("origin"):
        missing.append("travel.origin")
    if not payload.get("destination"):
        missing.append("travel.destination")
    if _positive_number(payload.get("budget_amount")) and not payload.get("currency"):
        missing.append("travel.currency")
    for item in extractor_missing:
        normalized = str(item)
        if _should_keep_travel_missing(normalized, payload) and normalized not in missing:
            missing.append(normalized)
    return missing


def _should_keep_travel_missing(item: str, payload: dict[str, Any]) -> bool:
    if not item.startswith("travel."):
        return False
    if item == "travel.origin":
        return not payload.get("origin")
    if item == "travel.destination":
        return not payload.get("destination")
    if item == "travel.currency":
        return _positive_number(payload.get("budget_amount")) and not payload.get("currency")
    return True


def _travel_clarification_questions(
    missing_information: list[str],
    extractor_questions: list[str],
) -> list[str]:
    if extractor_questions:
        return extractor_questions
    questions = []
    if "travel.origin" in missing_information:
        questions.append("请提供出发地。")
    if "travel.destination" in missing_information:
        questions.append("请提供目的地。")
    if "travel.currency" in missing_information:
        questions.append("请说明预算金额使用的币种，例如 GBP、USD、EUR 或 CNY。")
    return questions or ["请补充出发地、目的地、日期、预算和住宿需求等关键旅行信息。"]


def _fitness_missing_information(payload: dict[str, Any], extractor_missing: list[str]) -> list[str]:
    missing: list[str] = []
    if not payload.get("goal"):
        missing.append("fitness.goal")
    if not payload.get("available_slots"):
        missing.append("fitness.available_slots")
    if not payload.get("equipment"):
        missing.append("fitness.equipment")
    for item in extractor_missing:
        normalized = str(item)
        if _should_keep_fitness_missing(normalized, payload) and normalized not in missing:
            missing.append(normalized)
    return missing


def _should_keep_fitness_missing(item: str, payload: dict[str, Any]) -> bool:
    if not item.startswith("fitness."):
        return False
    if item == "fitness.goal":
        return not payload.get("goal")
    if item == "fitness.available_slots":
        return not payload.get("available_slots")
    if item == "fitness.equipment":
        return not payload.get("equipment")
    return True


def _fitness_clarification_questions(
    missing_information: list[str],
    extractor_questions: list[str],
) -> list[str]:
    if extractor_questions:
        return extractor_questions
    questions = []
    if "fitness.goal" in missing_information:
        questions.append("请说明这次健身计划的主要目标，例如增肌、有氧、灵活性、减压或体重管理。")
    if "fitness.available_slots" in missing_information:
        questions.append("请提供每周可训练的日期、时间或每次可训练时长。")
    if "fitness.equipment" in missing_information:
        questions.append("请说明可用器械，或者明确说明只能徒手训练。")
    return questions or ["请补充健身目标、训练时间、器械条件、强度偏好和限制条件。"]


def _valid_action_items(items: list[dict[str, Any]]) -> list[ActionItem]:
    valid: list[ActionItem] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            valid.append(ActionItem.model_validate(item))
        except Exception:
            continue
    return valid


def _valid_schedule_blocks(items: list[dict[str, Any]]) -> list[ScheduleBlock]:
    valid: list[ScheduleBlock] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            valid.append(ScheduleBlock.model_validate(item))
        except Exception:
            continue
    return valid


def _planner_missing_information(action_items: list[ActionItem], extractor_missing: list[str]) -> list[str]:
    missing: list[str] = []
    if not action_items:
        missing.append("planner.item_scope")
    for item in extractor_missing:
        normalized = str(item)
        if _should_keep_planner_missing(normalized, action_items) and normalized not in missing:
            missing.append(normalized)
    return missing


def _should_keep_planner_missing(item: str, action_items: list[ActionItem]) -> bool:
    if not item.startswith("planner."):
        return False
    if item == "planner.item_scope":
        return not action_items
    return True


def _planner_clarification_questions(
    missing_information: list[str],
    extractor_questions: list[str],
) -> list[str]:
    if extractor_questions:
        return extractor_questions
    questions = []
    if "planner.item_scope" in missing_information:
        questions.append("请说明要安排哪些具体任务、事项或截止日期。")
    if "planner.deadline_or_horizon" in missing_information:
        questions.append("请说明希望安排到哪一天完成，或希望规划未来几天/几周。")
    return questions or ["请补充任务内容、截止时间、优先级和已有日程冲突信息。"]


def _finance_missing_information(payload: dict[str, Any], extractor_missing: list[str]) -> list[str]:
    missing: list[str] = []
    if not _has_finance_income_context(payload):
        missing.append("finance.monthly_income_or_savings_balance")
    if not _has_finance_cost_context(payload):
        missing.append("finance.expenses_or_obligations")
    if _has_finance_amount_context(payload) and not payload.get("currency") and _nested_amounts_missing_currency(payload):
        missing.append("finance.currency")
    for item in extractor_missing:
        normalized = str(item)
        if _should_keep_extractor_missing(normalized, payload) and normalized not in missing:
            missing.append(normalized)
    return missing


def _should_keep_extractor_missing(item: str, payload: dict[str, Any]) -> bool:
    if not item.startswith("finance."):
        return False
    if item in {"finance.monthly_income", "finance.monthly_income_or_savings_balance", "finance.savings_balance"}:
        return not _has_finance_income_context(payload)
    if item in {"finance.expenses", "finance.obligations", "finance.expenses_or_obligations"}:
        return not _has_finance_cost_context(payload)
    if item == "finance.currency":
        return _has_finance_amount_context(payload) and not payload.get("currency")
    return True


def _has_finance_income_context(payload: dict[str, Any]) -> bool:
    return _positive_number(payload.get("monthly_income")) or _positive_number(payload.get("savings_balance"))


def _has_finance_cost_context(payload: dict[str, Any]) -> bool:
    return any(
        [
            bool(payload.get("expense_csv")),
            bool(payload.get("expenses")),
            bool(payload.get("obligations")),
            bool(payload.get("travel_budget_items")),
        ]
    )


def _has_finance_amount_context(payload: dict[str, Any]) -> bool:
    if _positive_number(payload.get("monthly_income")) or _positive_number(payload.get("savings_balance")):
        return True
    for key in ("expenses", "obligations", "travel_budget_items"):
        for item in payload.get(key) or []:
            if isinstance(item, dict) and (
                _positive_number(item.get("amount")) or _positive_number(item.get("estimated_amount"))
            ):
                return True
    return False


def _nested_amounts_missing_currency(payload: dict[str, Any]) -> bool:
    if (_positive_number(payload.get("monthly_income")) or _positive_number(payload.get("savings_balance"))) and not payload.get("currency"):
        return True
    for key in ("expenses", "obligations", "travel_budget_items"):
        for item in payload.get(key) or []:
            if not isinstance(item, dict):
                continue
            has_amount = _positive_number(item.get("amount")) or _positive_number(item.get("estimated_amount"))
            if has_amount and not item.get("currency"):
                return True
    return False


def _positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _finance_clarification_questions(
    missing_information: list[str],
    extractor_questions: list[str],
) -> list[str]:
    if extractor_questions:
        return extractor_questions
    questions = []
    if "finance.monthly_income_or_savings_balance" in missing_information:
        questions.append("请提供每月收入，或当前可用于预算规划的储蓄余额。")
    if "finance.expenses_or_obligations" in missing_information:
        questions.append("请提供至少一项固定支出、账单、欠款、学费、房租或即将到期的付款义务。")
    if "finance.currency" in missing_information:
        questions.append("请说明这些金额使用的币种，例如 GBP、USD、EUR 或 CNY。")
    return questions or ["请补充收入、支出、账单金额、币种和到期时间等关键财务信息。"]
