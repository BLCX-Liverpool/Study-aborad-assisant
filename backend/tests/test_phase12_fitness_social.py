from datetime import time

import pytest

from app.agents.fitness.input_extractor import FitnessInputExtraction
from app.agents.orchestrator.state import AgentScopedState
from app.agents.orchestrator.workers import FitnessWorker, SocialContentWorker, WorkerContext
from app.agents.fitness.service import FitnessAgentService
from app.agents.social_content.input_extractor import SocialContentInputExtraction
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
    assert output.memory_candidates
    assert output.memory_candidates[0].namespace == "social_content"


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


def test_social_content_memory_candidates_require_confirmation_by_default() -> None:
    request = SocialContentRequest(
        user_id="user_1",
        topic="留学生做饭省钱",
        platform="wechat_moments",
        tone="practical",
        audience="同城留学生朋友",
        notes="希望以后文案都保持实用、自然的风格。",
    )

    output = SocialContentAgentService().create_content(request)

    assert output.memory_candidates
    assert all(candidate.requires_confirmation for candidate in output.memory_candidates)
    assert all(candidate.confirmed is False for candidate in output.memory_candidates)
    assert any("audience" in candidate.content.lower() for candidate in output.memory_candidates)


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
                    "equipment": ["bodyweight"],
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


@pytest.mark.asyncio
async def test_fitness_worker_extracts_natural_language_input() -> None:
    class FakeFitnessInputExtractor:
        async def extract(self, **kwargs):
            return FitnessInputExtraction(
                payload={
                    "goal": "strength",
                    "fitness_level": "beginner",
                    "available_slots": [{"day_of_week": "mon", "start_time": "18:00", "duration_minutes": 45}],
                    "equipment": ["dumbbells"],
                    "preferred_intensity": "moderate",
                    "plan_weeks": 4,
                },
                confidence=0.91,
            )

    agent_state = AgentScopedState(agent_name="fitness")
    result = await FitnessWorker(input_extractor=FakeFitnessInputExtractor()).run(
        WorkerContext(
            request=ChatRequest(
                user_id="user_1",
                message="帮我做一个4周初级力量训练计划，周一晚上6点练45分钟，有哑铃。",
            ),
            agent_state=agent_state,
        )
    )

    assert result.missing_information == []
    assert result.artifacts[0].kind == "fitness_plan"
    assert agent_state.metadata["last_fitness_input_extraction"]["confidence"] == 0.91


@pytest.mark.asyncio
async def test_fitness_worker_asks_for_missing_training_context() -> None:
    class FakeFitnessInputExtractor:
        async def extract(self, **kwargs):
            return FitnessInputExtraction(
                payload={"goal": "strength"},
                missing_information=["fitness.available_slots", "fitness.equipment"],
                clarification_questions=["请提供每周可训练时间和可用器械。"],
                confidence=0.77,
            )

    result = await FitnessWorker(input_extractor=FakeFitnessInputExtractor()).run(
        WorkerContext(request=ChatRequest(user_id="user_1", message="帮我练力量。"))
    )

    assert result.artifacts == []
    assert result.missing_information == ["fitness.available_slots", "fitness.equipment"]
    assert "每周可训练时间" in result.final_response


@pytest.mark.asyncio
async def test_social_content_worker_extracts_natural_language_input() -> None:
    class FakeSocialContentInputExtractor:
        async def extract(self, **kwargs):
            return SocialContentInputExtraction(
                payload={
                    "topic": "留学第一周如何整理任务",
                    "platform": "xiaohongshu",
                    "tone": "practical",
                    "key_points": ["列清单", "确认 deadline", "给自己留缓冲"],
                    "draft_count": 2,
                    "language": "zh",
                },
                confidence=0.92,
            )

    agent_state = AgentScopedState(agent_name="social_content")
    result = await SocialContentWorker(input_extractor=FakeSocialContentInputExtractor()).run(
        WorkerContext(
            request=ChatRequest(
                user_id="user_1",
                message="帮我写小红书，主题是留学第一周如何整理任务，风格实用一点，提到列清单、确认deadline和留缓冲。",
            ),
            agent_state=agent_state,
        )
    )

    payload = result.artifacts[0].payload
    assert result.missing_information == []
    assert result.artifacts[0].kind == "social_content"
    assert len(payload["drafts"]) == 2
    assert payload["platform_standard"]["platform"] == "xiaohongshu"
    assert agent_state.metadata["last_social_content_input_extraction"]["confidence"] == 0.92
    assert result.trace_events[0]["payload"]["extracted"] is True


@pytest.mark.asyncio
async def test_social_content_worker_uses_defaults_when_extraction_is_empty() -> None:
    class FakeSocialContentInputExtractor:
        async def extract(self, **kwargs):
            return SocialContentInputExtraction(
                payload={},
                missing_information=["social_content.topic"],
                confidence=0.2,
                recoverable_error="LLM unavailable",
            )

    result = await SocialContentWorker(input_extractor=FakeSocialContentInputExtractor()).run(
        WorkerContext(
            request=ChatRequest(user_id="user_1", message="帮我写一篇关于留学生省钱做饭的文案。")
        )
    )

    payload = result.artifacts[0].payload
    assert result.missing_information == []
    assert payload["drafts"]
    assert payload["drafts"][0]["platform"] == "general"
    assert result.trace_events[0]["payload"]["recoverable_error"] == "LLM unavailable"
