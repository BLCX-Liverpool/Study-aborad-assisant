import asyncio
from datetime import timedelta

from app.agents.travel.checklist import TravelChecklistBuilder
from app.agents.travel.memory import build_travel_memory_candidates
from app.agents.travel.route_provider import TravelProviderResult, TravelRouteProvider
from app.schemas.tools import WeatherLookupRequest, WeatherLookupResponse
from app.schemas.travel import (
    TravelBudgetItem,
    TravelInformationSource,
    TravelPlanOutput,
    TravelPlanRequest,
)
from app.tools.models import ToolAvailabilityStatus
from app.tools.weather import WeatherLookupTool


class TravelAgentService:
    def __init__(
        self,
        checklist_builder: TravelChecklistBuilder | None = None,
        route_provider: TravelRouteProvider | None = None,
        weather_tool: WeatherLookupTool | None = None,
    ) -> None:
        self.checklist_builder = checklist_builder or TravelChecklistBuilder()
        self.route_provider = route_provider or TravelRouteProvider()
        self.weather_tool = weather_tool or WeatherLookupTool()

    def plan(self, request: TravelPlanRequest) -> TravelPlanOutput:
        provider_result = self.route_provider.collect(request)
        return self._build_plan(request, weather=None, provider_result=provider_result)

    async def plan_async(self, request: TravelPlanRequest) -> TravelPlanOutput:
        weather_task = None
        if request.depart_at is not None:
            days = 1
            if request.return_at is not None and request.return_at.date() >= request.depart_at.date():
                days = min((request.return_at.date() - request.depart_at.date()).days + 1, 7)
            weather_task = self.weather_tool.lookup(
                WeatherLookupRequest(
                    location=request.destination,
                    start_date=request.depart_at.date(),
                    days=days,
                )
            )
        provider_task = self.route_provider.collect_async(request)
        if weather_task is None:
            provider_result = await provider_task
            weather = None
        else:
            weather, provider_result = await asyncio.gather(weather_task, provider_task)
        return self._build_plan(request, weather=weather, provider_result=provider_result)

    def _build_plan(
        self,
        request: TravelPlanRequest,
        weather: WeatherLookupResponse | None,
        provider_result: TravelProviderResult,
    ) -> TravelPlanOutput:
        tasks = self.checklist_builder.build_tasks(request)
        itinerary = self.checklist_builder.build_itinerary(request)
        route_suggestions = provider_result.route_suggestions
        place_suggestions = provider_result.place_suggestions
        tool_statuses = provider_result.tool_statuses or self.route_provider.statuses()
        if weather is not None:
            tool_statuses.append(_weather_status(weather))

        return TravelPlanOutput(
            summary=_summary(request, route_suggestions, place_suggestions, weather),
            checklist=tasks,
            itinerary=itinerary,
            route_suggestions=route_suggestions,
            place_suggestions=place_suggestions,
            weather_forecasts=weather.forecasts if weather is not None else [],
            budget_breakdown=_budget_breakdown(request),
            information_sources=_information_sources(request, route_suggestions, place_suggestions, weather),
            tool_statuses=tool_statuses,
            memory_candidates=build_travel_memory_candidates(request),
            required_documents=_required_documents(request),
            budget_notes=_budget_notes(request),
            risk_notes=_risk_notes(request),
            booking_questions=_booking_questions(request),
            assumptions=_assumptions(request, weather, tool_statuses),
            requires_booking_approval=True,
        )


def _summary(request: TravelPlanRequest, route_suggestions, place_suggestions, weather: WeatherLookupResponse | None) -> str:
    route_source = "provider route" if any(item.source == "provider_verified" for item in route_suggestions) else "local route estimates"
    place_note = " and provider places" if place_suggestions else ""
    weather_note = " with weather lookup" if weather is not None and weather.forecasts else ""
    return f"Prepared a student travel plan from {request.origin} to {request.destination} using {route_source}{place_note}{weather_note}."


def _required_documents(request: TravelPlanRequest) -> list[str]:
    documents = ["Passport or national ID", "Student ID", "Travel ticket or booking reference"]
    if request.purpose == "visa_or_immigration":
        documents.extend(["Visa/BRP documents", "Appointment confirmation", "Proof of address"])
    if request.purpose == "academic_trip":
        documents.append("University trip confirmation or invitation letter")
    return documents


def _budget_breakdown(request: TravelPlanRequest) -> list[TravelBudgetItem]:
    if request.budget_amount is None:
        return [
            TravelBudgetItem(
                category="planning_gap",
                estimated_amount=None,
                currency=request.currency,
                notes="Budget is missing; collect transport, accommodation, food, local transit, and emergency buffer.",
                estimate_basis="missing_user_budget",
                confidence=0.0,
            )
        ]

    shares = {
        "transport": 0.35 if request.accommodation_needed else 0.45,
        "food": 0.20 if request.accommodation_needed else 0.25,
        "local_transit": 0.05 if request.accommodation_needed else 0.15,
        "contingency": 0.10 if request.accommodation_needed else 0.15,
    }
    if request.accommodation_needed:
        shares["accommodation"] = 0.30
    return [
        TravelBudgetItem(
            category=category,
            estimated_amount=round(request.budget_amount * share, 2),
            currency=request.currency,
            notes=_budget_note(category),
            source="estimated",
            confidence=0.35,
            estimate_basis="fixed student travel planning ratio; provider prices unavailable",
        )
        for category, share in shares.items()
        if share > 0
    ]


def _budget_notes(request: TravelPlanRequest) -> list[str]:
    if request.budget_amount is None:
        return ["Budget is missing; compare transport, accommodation, food, local transit, and emergency buffer."]
    return [
        f"Use {request.currency} {request.budget_amount:.2f} as the total planning ceiling.",
        "Budget breakdown is an estimate until route, accommodation, venue, and food providers are available.",
        "Reserve a small emergency buffer before booking non-refundable options.",
    ]


def _budget_note(category: str) -> str:
    notes = {
        "transport": "Estimate only; verify provider route prices before booking.",
        "accommodation": "Estimate only; check cancellation policy and deposit terms.",
        "food": "Keep a modest daily allowance.",
        "local_transit": "Include station/airport transfers and city transport.",
        "contingency": "Reserve for delays, weather changes, or urgent supplies.",
    }
    return notes.get(category, "Student travel estimate.")


def _risk_notes(request: TravelPlanRequest) -> list[str]:
    notes = [
        "Bookings and payments are external actions and require explicit user approval.",
        "Check cancellation policy and arrival time before paying.",
        "Routes, places, prices, and weather must show their source before being treated as verified.",
    ]
    if request.depart_at is None:
        notes.append("Departure time is missing, so reminder deadlines are approximate.")
    if request.accommodation_needed:
        notes.append("Avoid transferring deposits outside trusted accommodation platforms or official contracts.")
    return notes


def _booking_questions(request: TravelPlanRequest) -> list[str]:
    questions = []
    if request.depart_at is None:
        questions.append("What departure date and time should be used?")
    if request.return_at is None and request.purpose not in {"airport_arrival", "visa_or_immigration"}:
        questions.append("Is this a one-way trip, or should a return journey be planned?")
    if request.budget_amount is None:
        questions.append("What is the maximum budget for transport, accommodation, and local expenses?")
    return questions


def _assumptions(
    request: TravelPlanRequest,
    weather: WeatherLookupResponse | None,
    tool_statuses: list[ToolAvailabilityStatus],
) -> list[str]:
    assumptions = [
        "No booking, payment, accommodation deposit, or external submission was performed.",
        "Provider-verified route/place data is only used when the relevant provider reports available.",
    ]
    unavailable = [status.name for status in tool_statuses if not status.available]
    if unavailable:
        assumptions.append(f"Unavailable providers: {', '.join(unavailable)}.")
    if weather is None:
        assumptions.append("Weather lookup was not attempted because departure date is missing.")
    elif weather.recoverable_error:
        assumptions.append(f"Weather lookup degraded: {weather.recoverable_error}")
    if request.notes:
        assumptions.append("User notes were treated as soft planning constraints.")
    if request.constraints:
        assumptions.append("User-provided constraints were not overridden by the agent.")
    return assumptions


def _information_sources(request: TravelPlanRequest, route_suggestions, place_suggestions, weather: WeatherLookupResponse | None):
    sources = [
        TravelInformationSource(
            name="user_trip_request",
            source_type="user_provided",
            description=f"Origin={request.origin}; destination={request.destination}; purpose={request.purpose}.",
            confidence=1.0,
        )
    ]
    if route_suggestions:
        route_verified = any(item.source == "provider_verified" for item in route_suggestions)
        sources.append(
            TravelInformationSource(
                name="route_suggestions",
                source_type="provider_verified" if route_verified else "estimated",
                description="Route suggestions attached to this plan.",
                confidence=max(item.confidence for item in route_suggestions),
                tool_name="travel.maps.directions" if route_verified else None,
            )
        )
    if place_suggestions:
        sources.append(
            TravelInformationSource(
                name="place_suggestions",
                source_type="provider_verified",
                description="Places were resolved through Google Places Text Search.",
                confidence=max(item.confidence for item in place_suggestions),
                tool_name="travel.maps.places",
            )
        )
    if weather is not None:
        sources.append(
            TravelInformationSource(
                name="weather",
                source_type="provider_verified" if weather.forecasts else "unavailable",
                description=f"Weather source: {weather.source}.",
                confidence=0.8 if weather.forecasts else 0.0,
                tool_name="weather.lookup",
            )
        )
    return sources


def _weather_status(weather: WeatherLookupResponse) -> ToolAvailabilityStatus:
    return ToolAvailabilityStatus(
        name="weather.lookup",
        capability="weather_forecast",
        available=not bool(weather.recoverable_error),
        status="available" if not weather.recoverable_error else "degraded",
        permission_level=WeatherLookupTool.spec.permission_level,
        recoverable_error=weather.recoverable_error,
        metadata={"source": weather.source, "forecast_count": len(weather.forecasts)},
    )
