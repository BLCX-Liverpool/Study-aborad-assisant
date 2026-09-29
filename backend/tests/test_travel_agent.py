import json
from datetime import UTC, datetime

import pytest

from app.agents.orchestrator.state import AgentScopedState
from app.agents.orchestrator.workers import TravelWorker, WorkerContext
from app.agents.travel.input_extractor import TravelInputExtraction
from app.agents.travel.purpose_classifier import TravelPurposeClassifier
from app.agents.travel.service import TravelAgentService
from app.core.llm import ChatResponse
from app.schemas.chat import ChatRequest
from app.schemas.travel import TravelPlanRequest


def test_travel_agent_creates_student_checklist_and_requires_approval(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    request = TravelPlanRequest(
        user_id="user_1",
        origin="London",
        destination="Manchester",
        depart_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
        purpose="academic_trip",
        budget_amount=120,
        accommodation_needed=True,
    )

    plan = TravelAgentService().plan(request)

    assert plan.requires_booking_approval is True
    assert plan.checklist
    assert plan.itinerary[0].title == "Travel to Manchester"
    assert "Student ID" in plan.required_documents
    assert any("approval" in note for note in plan.risk_notes)


def test_travel_agent_collects_missing_booking_questions(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    request = TravelPlanRequest(
        user_id="user_1",
        origin="Campus",
        destination="Airport",
        purpose="airport_arrival",
    )

    plan = TravelAgentService().plan(request)

    assert plan.itinerary == []
    assert any("departure date" in question for question in plan.booking_questions)


@pytest.mark.asyncio
async def test_travel_purpose_classifier_uses_llm_json_response() -> None:
    class FakeTravelPurposeLlm:
        async def chat(self, request):
            assert request.response_format == {"type": "json_object"}
            assert "allowed purpose values" in request.messages[0].content.lower()
            return ChatResponse(
                content=json.dumps(
                    {
                        "purpose": "visa_or_immigration",
                        "confidence": 0.91,
                        "rationale": "The user is travelling for a visa appointment.",
                    }
                ),
                model="fake-travel",
            )

    result = await TravelPurposeClassifier(llm=FakeTravelPurposeLlm()).classify(
        message="I need to go to the embassy for my visa appointment.",
        origin="Campus",
        destination="London Embassy",
    )

    assert result.purpose == "visa_or_immigration"
    assert result.confidence == 0.91
    assert result.source == "llm"


@pytest.mark.asyncio
async def test_travel_worker_classifies_missing_purpose_with_llm(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    class FakeTravelPurposeLlm:
        async def chat(self, request):
            return ChatResponse(
                content=json.dumps(
                    {
                        "purpose": "academic_trip",
                        "confidence": 0.88,
                        "rationale": "The user mentions a campus research seminar.",
                    }
                ),
                model="fake-travel",
            )

    agent_state = AgentScopedState(agent_name="travel")
    result = await TravelWorker(
        purpose_classifier=TravelPurposeClassifier(llm=FakeTravelPurposeLlm())
    ).run(
        WorkerContext(
            request=ChatRequest(
                user_id="user_1",
                message="帮我规划去 Manchester campus 参加 research seminar 的行程",
                agent_inputs={
                    "travel": {
                        "origin": "London",
                        "destination": "Manchester",
                        "budget_amount": 120,
                        "currency": "GBP",
                    }
                },
            ),
            agent_state=agent_state,
        )
    )

    travel_plan = result.artifacts[0].payload
    assert travel_plan["information_sources"][0]["description"].endswith("purpose=academic_trip.")
    assert "University trip confirmation or invitation letter" in travel_plan["required_documents"]
    assert agent_state.metadata["last_purpose_classification"]["purpose"] == "academic_trip"
    assert any(event["name"] == "travel.purpose_classified" for event in result.trace_events)


@pytest.mark.asyncio
async def test_travel_worker_extracts_natural_language_input(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    class FakeTravelInputExtractor:
        async def extract(self, **kwargs):
            return TravelInputExtraction(
                payload={
                    "origin": "London",
                    "destination": "Manchester",
                    "depart_at": "2026-10-03T09:00:00Z",
                    "purpose": "academic_trip",
                    "budget_amount": 120,
                    "currency": "GBP",
                    "accommodation_needed": True,
                },
                confidence=0.93,
            )

    agent_state = AgentScopedState(agent_name="travel")
    result = await TravelWorker(input_extractor=FakeTravelInputExtractor()).run(
        WorkerContext(
            request=ChatRequest(
                user_id="user_1",
                message="我10月3日上午从伦敦去曼彻斯特参加学术活动，预算120镑，需要住宿。",
            ),
            agent_state=agent_state,
        )
    )

    assert result.missing_information == []
    assert result.artifacts[0].kind == "travel_plan"
    assert result.artifacts[0].payload["required_documents"]
    assert agent_state.metadata["last_travel_input_extraction"]["confidence"] == 0.93


@pytest.mark.asyncio
async def test_travel_worker_asks_for_missing_natural_language_fields() -> None:
    class FakeTravelInputExtractor:
        async def extract(self, **kwargs):
            return TravelInputExtraction(
                payload={"budget_amount": 200},
                missing_information=["travel.origin", "travel.destination", "travel.currency"],
                clarification_questions=["请提供出发地、目的地和预算币种。"],
                confidence=0.7,
            )

    result = await TravelWorker(input_extractor=FakeTravelInputExtractor()).run(
        WorkerContext(
            request=ChatRequest(user_id="user_1", message="帮我规划一次200预算的旅行。"),
        )
    )

    assert result.artifacts == []
    assert result.missing_information == ["travel.origin", "travel.destination", "travel.currency"]
    assert "请提供出发地、目的地和预算币种" in result.final_response
