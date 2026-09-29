import pytest

from app.agents.orchestrator.service import StudyAbroadOrchestrator
from app.schemas.chat import ChatRequest
from app.schemas.planner import PlannerOutput


@pytest.mark.asyncio
async def test_orchestrator_routes_wellbeing_to_worker() -> None:
    response = await StudyAbroadOrchestrator().handle_chat(
        ChatRequest(
            user_id="user_1",
            message="I feel overwhelmed and cannot sleep before exams.",
        )
    )

    assert response.router.primary_intent == "wellbeing"
    assert response.artifacts[0].kind == "wellbeing_support"
    assert "not a diagnosis" in response.artifacts[0].payload["professional_help_notice"]
    assert response.trace


@pytest.mark.asyncio
async def test_orchestrator_calls_travel_with_structured_input() -> None:
    response = await StudyAbroadOrchestrator().handle_chat(
        ChatRequest(
            user_id="user_1",
            message="帮我规划一下去曼彻斯特的学术旅行",
            agent_inputs={
                "travel": {
                    "origin": "London",
                        "destination": "Manchester",
                        "purpose": "academic_trip",
                        "budget_amount": 120,
                        "currency": "GBP",
                    }
                },
            )
    )

    assert response.router.primary_intent == "travel"
    assert response.artifacts[0].kind == "travel_plan"
    assert response.artifacts[0].payload["requires_booking_approval"] is True


@pytest.mark.asyncio
async def test_orchestrator_reports_missing_assignment_input() -> None:
    response = await StudyAbroadOrchestrator().handle_chat(
        ChatRequest(
            user_id="user_1",
            message="分析这个 coursework brief",
            uploaded_file_ids=["file_1"],
        )
    )

    assert response.router.primary_intent == "assignment"
    assert "assignment.source_path" in response.missing_information
    assert response.artifacts == []


@pytest.mark.asyncio
async def test_orchestrator_uses_history_for_reference_routing() -> None:
    response = await StudyAbroadOrchestrator().handle_chat(
        ChatRequest(
            user_id="user_1",
            message="那个 deadline 怎么安排？",
            history=[
                {
                    "role": "user",
                    "content": "我正在处理 COMP702 coursework，deadline 是 10 月 10 日。",
                }
            ],
        )
    )

    assert response.memory_context is not None
    assert response.memory_context["query_rewrite"]["changed"] is True
    assert response.router.primary_intent == "assignment"
    assert "assignment.source_path" in response.missing_information


@pytest.mark.asyncio
async def test_orchestrator_notice_action_pipeline(monkeypatch) -> None:
    class FakeTaskPlannerService:
        async def plan_global(self, request):
            return PlannerOutput(
                tasks=[
                    {
                        "title": "Pay rent",
                        "source_type": "bill_due",
                        "deadline": "2026-10-10T00:00:00Z",
                        "estimated_minutes": 30,
                        "priority": "high",
                        "evidence": [],
                    }
                ],
                assumptions=["Fake LLM-ToT planner output for orchestrator test."],
                selected_strategy="fake_llm_tot",
            )

    monkeypatch.setattr("app.agents.orchestrator.workers.TaskPlannerService", FakeTaskPlannerService)

    response = await StudyAbroadOrchestrator().handle_chat(
        ChatRequest(
            user_id="user_1",
            message="Your rent bill of £900 is due on 2026-10-10.",
        )
    )

    assert response.router.primary_intent == "notice_action"
    artifact_kinds = {artifact.kind for artifact in response.artifacts}
    assert "notice_parse" in artifact_kinds
    assert "planner_output" in artifact_kinds
