from app.agents.wellbeing.safety import WellbeingSafetyLayer
from app.schemas.wellbeing import WellbeingSupportRequest, WellbeingSupportResponse


class WellbeingAgentService:
    def __init__(self, safety_layer: WellbeingSafetyLayer | None = None) -> None:
        self.safety_layer = safety_layer or WellbeingSafetyLayer()

    def support(self, request: WellbeingSupportRequest) -> WellbeingSupportResponse:
        safety = self.safety_layer.assess(request.message, request.context)
        if safety.risk_level in {"crisis", "high"}:
            return WellbeingSupportResponse(
                safety=safety,
                supportive_message=(
                    "I am really sorry you are dealing with this. Your immediate safety matters more than solving "
                    "this alone right now."
                ),
                grounding_steps=[
                    "Move away from anything you could use to hurt yourself or someone else.",
                    "Contact a trusted person nearby and tell them you need immediate support.",
                    "If there is immediate danger, contact local emergency services now.",
                ],
                suggested_actions=[
                    "Contact your university wellbeing or student support team as soon as possible.",
                    "Reach out to a licensed mental health professional or urgent care service.",
                ],
                crisis_guidance=[
                    "This app cannot provide emergency care.",
                    "If you may act on harmful thoughts, call local emergency services or go to the nearest emergency department.",
                ],
                professional_help_notice=_professional_notice(),
                should_store_sensitive_content=False,
            )

        if safety.risk_level == "medium":
            return WellbeingSupportResponse(
                safety=safety,
                supportive_message=(
                    "It sounds like things are feeling heavy. We can keep this practical and focus on the next small step."
                ),
                grounding_steps=[
                    "Take three slow breaths and name five things you can see.",
                    "Drink water or eat something simple if you have skipped meals.",
                    "Write down the one concern that feels most urgent today.",
                ],
                suggested_actions=[
                    "Break the problem into a 20-minute task and a rest period.",
                    "Message a friend, classmate, tutor, or student support service for a check-in.",
                    "Consider booking an appointment with university counselling or a GP if this continues.",
                ],
                professional_help_notice=_professional_notice(),
                should_store_sensitive_content=request.allow_sensitive_memory,
            )

        return WellbeingSupportResponse(
            safety=safety,
            supportive_message=(
                "That makes sense. Studying abroad can make ordinary stress feel larger because everything is happening "
                "away from familiar support."
            ),
            grounding_steps=[
                "Choose one small action you can complete in the next 10 minutes.",
                "Step away from the screen briefly before returning to the task.",
                "Keep meals, sleep, and movement visible in today's plan.",
            ],
            suggested_actions=[
                "Use the planner to turn the concern into one concrete task.",
                "If this relates to coursework, check the assignment deadline and evidence first.",
                "If the feeling keeps intensifying, contact university wellbeing support.",
            ],
            professional_help_notice=_professional_notice(),
            should_store_sensitive_content=request.allow_sensitive_memory,
        )


def _professional_notice() -> str:
    return (
        "This support is not a diagnosis and cannot replace professional medical care, counselling, "
        "or psychotherapy."
    )
