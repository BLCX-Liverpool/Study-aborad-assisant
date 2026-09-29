import json

import pytest

from app.agents.fitness.service import FitnessAgentService
from app.agents.social_content.llm_generator import LlmSocialCopyGenerator
from app.core.llm import ChatResponse
from app.schemas.fitness import AvailableWorkoutSlot, FitnessPlanRequest
from app.schemas.social_content import PlatformStandard, SocialContentRequest
from app.skills import SkillLoader


class CapturingLlm:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def chat(self, request):
        self.requests.append(request)
        return ChatResponse(content=json.dumps(self.payload), model="fake")


def test_skill_loader_reads_social_skill_and_references() -> None:
    skill = SkillLoader().load("social-content-writing", include_references=True)

    assert skill is not None
    assert skill.metadata["name"] == "social-content-writing"
    assert "Social Content Writing Skill" in skill.content
    assert "references/privacy_rules.md" in skill.references


@pytest.mark.asyncio
async def test_social_llm_generator_injects_social_content_skill() -> None:
    llm = CapturingLlm(
        {
            "drafts": [
                {
                    "platform": "xiaohongshu",
                    "variant": "skill_guided",
                    "title": "留学第一周任务整理",
                    "body": "先列清单，再确认 deadline，最后给自己留缓冲。",
                    "hashtags": ["留学生活", "学习计划"],
                    "call_to_action": "收藏起来开学用",
                    "platform_fit_notes": ["短段落", "经验感"],
                }
            ]
        }
    )

    drafts = await LlmSocialCopyGenerator(llm=llm).generate(
        SocialContentRequest(user_id="user_1", topic="留学第一周如何整理任务", platform="xiaohongshu"),
        "xiaohongshu",
        PlatformStandard(platform="xiaohongshu", recommended_length="short"),
    )

    assert drafts[0].variant == "skill_guided"
    assert "Social Content Writing Skill" in llm.requests[0].messages[0].content
    assert "privacy_rules" in llm.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_fitness_service_uses_tanchengyi_skill_for_llm_plan() -> None:
    llm = CapturingLlm(
        {
            "summary": "Generated a skill-guided strength plan.",
            "workout_days": [
                {
                    "day_of_week": "mon",
                    "focus": "动作质量优先的推训练",
                    "duration_minutes": 45,
                    "blocks": [
                        {
                            "name": "Warm-up",
                            "duration_minutes": 8,
                            "intensity": "low",
                            "instructions": ["肩胛控制", "轻重量热身"],
                        },
                        {
                            "name": "哑铃推举跟练",
                            "duration_minutes": 30,
                            "intensity": "moderate",
                            "instructions": ["3 组 x 8-12 次", "控制离心", "避免耸肩借力"],
                        },
                        {
                            "name": "Cool-down",
                            "duration_minutes": 7,
                            "intensity": "low",
                            "instructions": ["胸肩轻拉伸", "慢呼吸"],
                        },
                    ],
                    "safety_notes": ["保留 1-2 次余力。"],
                }
            ],
            "habit_tasks": [],
            "schedule_tasks": [],
            "progression": [],
            "memory_candidates": [],
            "missing_information": [],
            "risk_notes": [],
            "assumptions": [],
            "disclaimer": "This is general fitness planning support and is not medical advice.",
        }
    )

    output = await FitnessAgentService(llm=llm).create_plan_async(
        FitnessPlanRequest(
            user_id="user_1",
            goal="strength",
            fitness_level="intermediate",
            available_slots=[AvailableWorkoutSlot(day_of_week="mon", duration_minutes=45)],
            equipment=["dumbbells"],
        )
    )

    assert output.workout_days[0].blocks[1].name == "哑铃推举跟练"
    assert output.schedule_tasks
    assert output.progression
    assert any("tanchengyi-fitness" in assumption for assumption in output.assumptions)
    assert "谭成义健身 Skill" in llm.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_fitness_service_falls_back_when_skill_llm_output_is_invalid() -> None:
    llm = CapturingLlm({"not_a_plan": True})

    output = await FitnessAgentService(llm=llm).create_plan_async(
        FitnessPlanRequest(
            user_id="user_1",
            goal="strength",
            available_slots=[AvailableWorkoutSlot(day_of_week="mon", duration_minutes=45)],
            equipment=["bodyweight"],
        )
    )

    assert output.workout_days[0].blocks[1].name == "Full-body strength basics"
    assert output.assumptions
