from datetime import time

import pytest

from app.agents.fitness.service import FitnessAgentService
from app.agents.social_content.service import SocialContentAgentService
from app.agents.orchestrator.service import StudyAbroadOrchestrator
from app.schemas.chat import ChatRequest
from app.schemas.fitness import AvailableWorkoutSlot, FitnessPlanRequest
from app.schemas.social_content import SocialContentRequest


def test_fitness_agent_creates_workout_days_and_habits() -> None:
    request = FitnessPlanRequest(
        user_id="user_1",
        goal="strength",
        fitness_level="beginner",
        available_slots=[
            AvailableWorkoutSlot(day_of_week="mon", start_time=time(18, 0), duration_minutes=45),
            AvailableWorkoutSlot(day_of_week="thu", duration_minutes=40),
        ],
        equipment=["dumbbells"],
    )

    output = FitnessAgentService().create_plan(request)

    assert len(output.workout_days) == 2
    assert output.workout_days[0].blocks[1].name == "Full-body strength basics"
    assert output.habit_tasks
    assert len(output.schedule_tasks) == 2
    assert output.progression
    assert output.memory_candidates[0].namespace == "fitness"
    assert output.disclaimer.endswith("not medical advice.")


def test_fitness_agent_conservatively_handles_injury_constraints() -> None:
    request = FitnessPlanRequest(
        user_id="user_1",
        goal="cardio",
        constraints=["knee pain"],
        notes="I had an injury last month.",
    )

    output = FitnessAgentService().create_plan(request)

    assert output.workout_days[0].blocks[1].intensity == "low"
    assert any("professional" in note for note in output.risk_notes)


def test_social_content_agent_generates_copy_and_platform_notes() -> None:
    request = SocialContentRequest(
        user_id="user_1",
        topic="第一次独立处理英国租房账单",
        platform="xiaohongshu",
        key_points=["先核对收款方", "把 due date 放进日历", "付款前保存 invoice"],
    )

    output = SocialContentAgentService().create_content(request)

    assert output.safety.level == "ok"
    assert len(output.drafts) == 3
    assert output.drafts[0].platform == "xiaohongshu"
    assert output.drafts[0].variant == "balanced"
    assert "留学生真实记录" in (output.drafts[0].title or "")
    assert output.drafts[0].hashtags
    assert output.platform_standard is not None
    assert output.image_generation_tool is not None
    assert output.image_generation_tool.status == "designed_not_enabled"


def test_social_content_agent_flags_sensitive_details() -> None:
    request = SocialContentRequest(
        user_id="user_1",
        topic="分享我的住宿经历",
        personal_details=["My address is 10 Example Street and email me at test@example.com"],
    )

    output = SocialContentAgentService().create_content(request)

    assert output.safety.level == "needs_review"
    assert output.safety.issues
    assert output.drafts


def test_fitness_memory_candidates_require_confirmation_by_default() -> None:
    request = FitnessPlanRequest(
        user_id="user_1",
        goal="stress_relief",
        memory_preferences=["Prefers short evening workouts."],
    )

    output = FitnessAgentService().create_plan(request)

    assert output.memory_candidates
    assert all(candidate.requires_confirmation for candidate in output.memory_candidates)
    assert all(candidate.confirmed is False for candidate in output.memory_candidates)
    assert any("confirmation" in assumption.lower() for assumption in output.assumptions)


def test_social_content_multiple_draft_count_is_bounded_by_request() -> None:
    request = SocialContentRequest(
        user_id="user_1",
        topic="留学生如何准备 group project",
        platform="linkedin",
        draft_count=2,
        key_points=["Clarify roles early", "Document decisions", "Leave buffer before deadline"],
        language="en",
    )

    output = SocialContentAgentService().create_content(request)

    assert len(output.drafts) == 2
    assert output.platform_standard is not None
    assert output.platform_standard.platform == "linkedin"
    assert all(draft.platform_fit_notes for draft in output.drafts)


@pytest.mark.asyncio
async def test_orchestrator_dispatches_fitness_and_social_content() -> None:
    orchestrator = StudyAbroadOrchestrator()

    fitness = await orchestrator.handle_chat(
        ChatRequest(
            user_id="user_1",
            message="帮我安排每周健身训练",
            agent_inputs={
                "fitness": {
                    "goal": "general_fitness",
                    "available_slots": [{"day_of_week": "sat", "duration_minutes": 30}],
                }
            },
        )
    )
    social = await orchestrator.handle_chat(
        ChatRequest(
            user_id="user_1",
            message="帮我写一篇小红书文案",
            agent_inputs={
                "social_content": {
                    "topic": "留学第一周如何整理任务",
                    "platform": "xiaohongshu",
                    "key_points": ["列清单", "确认 deadline", "给自己留缓冲"],
                }
            },
        )
    )

    assert fitness.router.primary_intent == "fitness"
    assert any(artifact.kind == "fitness_plan" for artifact in fitness.artifacts)
    assert social.router.primary_intent == "social_content"
    assert any(artifact.kind == "social_content" for artifact in social.artifacts)
