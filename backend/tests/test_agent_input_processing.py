from datetime import UTC, datetime

import pytest

from app.agents.email.input_extractor import EmailInputExtraction
from app.agents.orchestrator.state import AgentScopedState
from app.agents.orchestrator.workers import EmailWorker, TaskPlanningWorker, WorkerContext
from app.agents.planner.input_extractor import PlanningInputExtraction
from app.schemas.chat import ChatRequest
from app.schemas.email import EmailApprovalGateResult, EmailDraft, EmailDraftResponse
from app.schemas.planner import PlannerOutput


@pytest.mark.asyncio
async def test_task_planning_worker_extracts_items_for_global_planning(monkeypatch) -> None:
    class FakePlanningInputExtractor:
        async def extract(self, **kwargs):
            return PlanningInputExtraction(
                items=[
                    {
                        "title": "完成数据库课程作业",
                        "action_type": "assignment_deadline",
                        "source_type": "user_request",
                        "deadline": "2026-10-10T16:00:00Z",
                        "priority": "high",
                    }
                ],
                planning_horizon_days=14,
                confidence=0.9,
            )

    class FakeTaskPlannerService:
        async def plan_global(self, request):
            assert request.user_id == "user_1"
            assert request.planning_horizon_days == 14
            assert request.items[0].title == "完成数据库课程作业"
            return PlannerOutput(tasks=[], events=[], reminders=[], selected_strategy="test")

    monkeypatch.setattr("app.agents.orchestrator.workers.TaskPlannerService", FakeTaskPlannerService)
    agent_state = AgentScopedState(agent_name="planner")

    result = await TaskPlanningWorker(input_extractor=FakePlanningInputExtractor()).run(
        WorkerContext(
            request=ChatRequest(user_id="user_1", message="帮我安排数据库课程作业，10月10日下午4点截止。"),
            agent_state=agent_state,
        )
    )

    assert result.missing_information == []
    assert result.artifacts[0].kind == "planner_output"
    assert agent_state.metadata["last_planner_input_extraction"]["confidence"] == 0.9


@pytest.mark.asyncio
async def test_task_planning_worker_asks_for_missing_item_scope() -> None:
    class FakePlanningInputExtractor:
        async def extract(self, **kwargs):
            return PlanningInputExtraction(
                items=[],
                missing_information=["planner.item_scope", "planner.deadline_or_horizon"],
                clarification_questions=["请说明要安排的具体任务和规划周期。"],
                confidence=0.62,
            )

    result = await TaskPlanningWorker(input_extractor=FakePlanningInputExtractor()).run(
        WorkerContext(request=ChatRequest(user_id="user_1", message="帮我安排一下。"))
    )

    assert result.artifacts == []
    assert result.missing_information == ["planner.item_scope", "planner.deadline_or_horizon"]
    assert "具体任务" in result.final_response


@pytest.mark.asyncio
async def test_email_worker_extracts_structured_context_before_drafting(monkeypatch) -> None:
    class FakeEmailInputExtractor:
        async def extract(self, **kwargs):
            return EmailInputExtraction(
                payload={
                    "purpose": "Request an extension for a coursework deadline.",
                    "recipient_hint": "professor",
                    "language": "en",
                    "tone_hint": "formal",
                    "context": {
                        "recipient_name": "Dr Smith",
                        "course_code": "COMP702",
                        "assignment_title": "database report",
                        "deadline": "2026-10-10",
                        "additional_context": "I need two more days due to illness.",
                    },
                },
                confidence=0.88,
            )

    class FakeEmailAgentService:
        def __init__(self, draft_generator=None):
            self.draft_generator = draft_generator

        async def create_draft(self, request):
            assert request.recipient_hint == "professor"
            assert request.context.course_code == "COMP702"
            return EmailDraftResponse(
                draft=EmailDraft(
                    recipient_type="professor",
                    subject="Extension request for COMP702 database report",
                    body="Dear Dr Smith, ...",
                    tone="formal",
                ),
                approval=EmailApprovalGateResult(),
            )

    monkeypatch.setattr("app.agents.orchestrator.workers.EmailAgentService", FakeEmailAgentService)
    agent_state = AgentScopedState(agent_name="email")

    result = await EmailWorker(input_extractor=FakeEmailInputExtractor()).run(
        WorkerContext(
            request=ChatRequest(
                user_id="user_1",
                message="帮我给Dr Smith写邮件，COMP702数据库报告想延期两天。",
            ),
            agent_state=agent_state,
        )
    )

    assert result.missing_information == []
    assert result.artifacts[0].kind == "email_draft"
    assert agent_state.metadata["last_email_input_extraction"]["confidence"] == 0.88
