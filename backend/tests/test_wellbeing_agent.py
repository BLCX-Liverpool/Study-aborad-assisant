from app.agents.wellbeing.safety import WellbeingSafetyLayer
from app.agents.wellbeing.service import WellbeingAgentService
from app.schemas.wellbeing import WellbeingSupportRequest


def test_wellbeing_safety_layer_detects_crisis_language() -> None:
    assessment = WellbeingSafetyLayer().assess("I want to die and end my life.")

    assert assessment.risk_level == "crisis"
    assert assessment.should_escalate is True


def test_wellbeing_agent_does_not_store_sensitive_content_by_default() -> None:
    request = WellbeingSupportRequest(
        user_id="user_1",
        message="I feel overwhelmed and cannot sleep before exams.",
    )

    response = WellbeingAgentService().support(request)

    assert response.safety.risk_level == "medium"
    assert response.should_store_sensitive_content is False
    assert "not a diagnosis" in response.professional_help_notice


def test_wellbeing_agent_escalates_high_risk_support() -> None:
    request = WellbeingSupportRequest(
        user_id="user_1",
        message="I might hurt myself tonight.",
        allow_sensitive_memory=True,
    )

    response = WellbeingAgentService().support(request)

    assert response.safety.should_escalate is True
    assert response.should_store_sensitive_content is False
    assert response.crisis_guidance
