from datetime import UTC, datetime

from app.agents.travel.service import TravelAgentService
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
