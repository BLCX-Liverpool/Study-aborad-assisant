import asyncio
from datetime import UTC, date, datetime, time, timedelta

from app.agents.travel.checklist import TravelChecklistBuilder
from app.agents.travel.memory import build_travel_memory_candidates
from app.agents.travel.route_provider import TravelProviderResult, TravelRouteProvider
from app.schemas.action import ActionItem
from app.schemas.common import PlannedEvent
from app.schemas.tools import WeatherForecast, WeatherLookupRequest, WeatherLookupResponse
from app.schemas.travel import (
    RouteSuggestion,
    TravelBudgetItem,
    TravelInformationSource,
    TravelItineraryDay,
    TravelItineraryOutput,
    TravelItineraryRequest,
    TravelPlaceSuggestion,
)
from app.tools.models import ToolAvailabilityStatus
from app.tools.weather import WeatherLookupTool


class TravelItineraryGenerator:
    def __init__(
        self,
        checklist_builder: TravelChecklistBuilder | None = None,
        route_provider: TravelRouteProvider | None = None,
        weather_tool: WeatherLookupTool | None = None,
    ) -> None:
        self.checklist_builder = checklist_builder or TravelChecklistBuilder()
        self.route_provider = route_provider or TravelRouteProvider()
        self.weather_tool = weather_tool or WeatherLookupTool()

    def generate(self, request: TravelItineraryRequest) -> TravelItineraryOutput:
        provider_result = self.route_provider.collect(request)
        return self._build_output(request, provider_result=provider_result, weather=None)

    async def generate_async(self, request: TravelItineraryRequest) -> TravelItineraryOutput:
        weather_task = None
        if request.depart_at is not None and not request.weather_forecasts:
            weather_task = self.weather_tool.lookup(
                WeatherLookupRequest(
                    location=request.destination,
                    start_date=_ensure_aware(request.depart_at).date(),
                    days=_weather_days(request),
                )
            )
        provider_task = self.route_provider.collect_async(request)
        if weather_task is None:
            provider_result = await provider_task
            weather = None
        else:
            weather, provider_result = await asyncio.gather(weather_task, provider_task)
            request = request.model_copy(update={"weather_forecasts": weather.forecasts})
        return self._build_output(request, provider_result=provider_result, weather=weather)

    def _build_output(
        self,
        request: TravelItineraryRequest,
        *,
        provider_result: TravelProviderResult,
        weather: WeatherLookupResponse | None,
    ) -> TravelItineraryOutput:
        trip_dates = _trip_dates(request)
        weather_by_date = {forecast.date: forecast for forecast in request.weather_forecasts if forecast.date}
        days = [
            TravelItineraryDay(
                date=trip_date,
                theme=_day_theme(request, index, len(trip_dates)),
                events=_day_events(request, trip_date, index, len(trip_dates), provider_result),
                weather=weather_by_date.get(trip_date),
                notes=_day_notes(request, weather_by_date.get(trip_date), provider_result),
            )
            for index, trip_date in enumerate(trip_dates)
        ]
        tool_statuses = provider_result.tool_statuses or self.route_provider.statuses()
        if weather is not None:
            tool_statuses.append(_weather_status(weather))

        return TravelItineraryOutput(
            summary=_summary(request, days, provider_result, weather),
            days=days,
            budget_breakdown=_budget_breakdown(request, provider_result.route_suggestions),
            route_suggestions=provider_result.route_suggestions,
            place_suggestions=provider_result.place_suggestions,
            information_sources=_information_sources(request, provider_result, weather),
            tool_statuses=tool_statuses,
            memory_candidates=build_travel_memory_candidates(request),
            planner_items=_planner_items(request, provider_result.route_suggestions),
            checklist=self.checklist_builder.build_tasks(request),
            risk_notes=_risk_notes(request, provider_result),
            assumptions=_assumptions(request, days, provider_result, weather),
            requires_booking_approval=True,
        )


def _trip_dates(request: TravelItineraryRequest) -> list[date]:
    if request.depart_at is None:
        return []
    start = _ensure_aware(request.depart_at).date()
    if request.return_at is None:
        return [start]
    end = _ensure_aware(request.return_at).date()
    if end < start:
        return [start]
    days = min((end - start).days + 1, 14)
    return [start + timedelta(days=offset) for offset in range(days)]


def _weather_days(request: TravelItineraryRequest) -> int:
    if request.depart_at is None:
        return 1
    start = _ensure_aware(request.depart_at).date()
    if request.return_at is None:
        return 1
    end = _ensure_aware(request.return_at).date()
    if end < start:
        return 1
    return min((end - start).days + 1, 7)


def _day_theme(request: TravelItineraryRequest, index: int, total_days: int) -> str:
    if index == 0:
        return "Arrival and route setup"
    if index == total_days - 1 and request.return_at is not None:
        return "Return and buffer"
    if request.purpose == "academic_trip":
        return "Academic visit and local logistics"
    if request.purpose == "visa_or_immigration":
        return "Appointment preparation and buffer"
    if request.purpose == "home_visit":
        return "Family visit and travel buffer"
    return "Local orientation and essential errands"


def _day_events(
    request: TravelItineraryRequest,
    trip_date: date,
    index: int,
    total_days: int,
    provider_result: TravelProviderResult,
) -> list[PlannedEvent]:
    start = _day_start(request, trip_date, index)
    primary_route = _primary_route(provider_result.route_suggestions)
    events = [
        PlannedEvent(
            title="Local orientation buffer",
            description=_local_orientation_description(provider_result.place_suggestions),
            location=_first_place_location(provider_result.place_suggestions) or request.destination,
            start_time=start,
            end_time=start + timedelta(hours=1),
            source_type="travel",
        )
    ]

    if index == 0:
        events.insert(
            0,
            PlannedEvent(
                title=f"Travel from {request.origin} to {request.destination}",
                description=_route_description(primary_route, "Keep ticket, ID, and emergency contact details accessible."),
                location=primary_route.origin if primary_route else request.origin,
                start_time=_ensure_aware(request.depart_at) if request.depart_at else start,
                end_time=(_ensure_aware(request.depart_at) if request.depart_at else start)
                + timedelta(minutes=_route_minutes(primary_route, fallback_hours=3)),
                source_type="travel",
            ),
        )
    elif index == total_days - 1 and request.return_at is not None:
        return_time = _ensure_aware(request.return_at)
        events.append(
            PlannedEvent(
                title=f"Return to {request.origin}",
                description=_route_description(primary_route, "Leave a disruption buffer before any academic or immigration deadline."),
                location=primary_route.destination if primary_route else request.destination,
                start_time=return_time,
                end_time=return_time + timedelta(minutes=_route_minutes(primary_route, fallback_hours=3)),
                source_type="travel",
            )
        )
    else:
        events.append(_purpose_event(request, start + timedelta(hours=2), _place_for_day(provider_result.place_suggestions, index)))

    if request.accommodation_needed and index == 0:
        events.append(
            PlannedEvent(
                title="Accommodation check-in window",
                description="Confirm check-in time, deposit terms, cancellation policy, and address before arrival.",
                location=request.destination,
                start_time=start + timedelta(hours=4),
                end_time=start + timedelta(hours=5),
                source_type="travel",
            )
        )

    return events


def _purpose_event(
    request: TravelItineraryRequest,
    start_time: datetime,
    place: TravelPlaceSuggestion | None = None,
) -> PlannedEvent:
    title_by_purpose = {
        "academic_trip": "Academic activity block",
        "visa_or_immigration": "Appointment preparation block",
        "airport_arrival": "Arrival setup block",
        "home_visit": "Family visit block",
        "city_trip": "City orientation block",
        "other": "Main trip activity block",
    }
    return PlannedEvent(
        title=title_by_purpose.get(request.purpose, "Main trip activity block"),
        description=_purpose_description(place),
        location=place.location if place else request.destination,
        start_time=start_time,
        end_time=start_time + timedelta(hours=_activity_hours(request.preferred_pace)),
        source_type="travel",
    )


def _budget_breakdown(request: TravelItineraryRequest, routes: list[RouteSuggestion]) -> list[TravelBudgetItem]:
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

    if request.accommodation_needed:
        shares = {
            "transport": 0.35,
            "accommodation": 0.30,
            "food": 0.20,
            "local_transit": 0.05,
            "contingency": 0.10,
        }
    else:
        shares = {
            "transport": 0.45,
            "food": 0.25,
            "local_transit": 0.15,
            "contingency": 0.15,
        }
    return [
        TravelBudgetItem(
            category=category,
            estimated_amount=round(request.budget_amount * share, 2),
            currency=request.currency,
            notes=_budget_note(category),
            source="estimated",
            confidence=0.4 if any(route.source == "provider_verified" for route in routes) else 0.3,
            estimate_basis=_budget_basis(category, routes),
        )
        for category, share in shares.items()
        if share > 0
    ]


def _budget_note(category: str) -> str:
    notes = {
        "transport": "Compare route options before paying.",
        "accommodation": "Check cancellation policy and deposit terms.",
        "food": "Keep a modest daily allowance.",
        "local_transit": "Include airport/station transfers and city transport.",
        "contingency": "Reserve for delays, weather changes, or urgent supplies.",
    }
    return notes.get(category, "Student travel estimate.")


def _budget_basis(category: str, routes: list[RouteSuggestion]) -> str:
    provider_route = _primary_route(routes)
    if category == "transport" and provider_route is not None:
        detail = []
        if provider_route.estimated_minutes is not None:
            detail.append(f"{provider_route.estimated_minutes} minute route")
        if provider_route.distance_km is not None:
            detail.append(f"{provider_route.distance_km} km distance")
        return "Google Maps route context: " + ", ".join(detail) if detail else "Google Maps route context without price data"
    return "student travel planning ratio; price providers are not connected"


def _day_notes(
    request: TravelItineraryRequest,
    weather: WeatherForecast | None,
    provider_result: TravelProviderResult,
) -> list[str]:
    notes = []
    if request.constraints:
        notes.append("User constraints were treated as hard planning boundaries.")
    if weather is not None:
        notes.extend(weather.notes)
    if any(route.source == "provider_verified" for route in provider_result.route_suggestions):
        notes.append("Route timing is provider-informed by Google Maps Directions.")
    elif provider_result.route_suggestions:
        notes.append("Route timing uses local estimates because provider routes are unavailable.")
    if provider_result.place_suggestions:
        notes.append("Local activity options are provider-informed by Google Places.")
    if request.preferred_pace == "relaxed":
        notes.append("Leave additional rest and transit buffer between blocks.")
    return notes


def _risk_notes(request: TravelItineraryRequest, provider_result: TravelProviderResult) -> list[str]:
    notes = [
        "Bookings, payments, accommodation deposits, and third-party submissions require explicit user approval.",
        "Weather and venue details should be rechecked close to departure.",
    ]
    if any(status.recoverable_error for status in provider_result.tool_statuses):
        notes.append("One or more travel providers returned a recoverable error; affected sections are estimated or omitted.")
    if request.return_at is not None and request.depart_at is not None and request.return_at < request.depart_at:
        notes.append("Return time is earlier than departure time; itinerary was limited to the departure day.")
    return notes


def _assumptions(
    request: TravelItineraryRequest,
    days: list[TravelItineraryDay],
    provider_result: TravelProviderResult,
    weather: WeatherLookupResponse | None,
) -> list[str]:
    assumptions = [
        "No external booking, payment, map, or ticketing tool was called.",
        "Specific venues, prices, and disruption status should be rechecked before travel.",
    ]
    if any(route.source == "provider_verified" for route in provider_result.route_suggestions):
        assumptions[0] = "Google Maps was used for planning data only; no booking, payment, or ticketing action was performed."
    unavailable = [status.name for status in provider_result.tool_statuses if not status.available]
    if unavailable:
        assumptions.append(f"Unavailable or degraded providers: {', '.join(unavailable)}.")
    if not days:
        assumptions.append("Departure time is missing; itinerary days could not be generated.")
    if weather is not None and weather.recoverable_error:
        assumptions.append(f"Weather lookup degraded: {weather.recoverable_error}")
    if weather is not None and request.return_at is not None and len(days) > 7:
        assumptions.append("Weather lookup was limited to 7 days by provider request constraints.")
    if not request.weather_forecasts and weather is None:
        assumptions.append("No weather forecast was provided; call weather.lookup separately if weather is needed.")
    return assumptions


def _summary(
    request: TravelItineraryRequest,
    days: list[TravelItineraryDay],
    provider_result: TravelProviderResult,
    weather: WeatherLookupResponse | None,
) -> str:
    if not days:
        return f"Need a departure date before generating a day-by-day itinerary for {request.destination}."
    route_source = "provider-informed" if any(route.source == "provider_verified" for route in provider_result.route_suggestions) else "estimate-based"
    place_source = " with provider places" if provider_result.place_suggestions else ""
    weather_source = " and weather lookup" if weather is not None and weather.forecasts else ""
    return f"Generated a {len(days)} day {route_source} student itinerary for {request.destination}{place_source}{weather_source}."


def _day_start(request: TravelItineraryRequest, trip_date: date, index: int) -> datetime:
    if index == 0 and request.depart_at is not None:
        return _ensure_aware(request.depart_at)
    return datetime.combine(trip_date, time(hour=9), tzinfo=UTC)


def _activity_hours(pace: str) -> int:
    if pace == "relaxed":
        return 2
    if pace == "intensive":
        return 5
    return 3


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _planner_items(request: TravelItineraryRequest, routes: list[RouteSuggestion]) -> list[ActionItem]:
    items: list[ActionItem] = []
    primary_route = _primary_route(routes)
    if request.depart_at:
        items.append(
            ActionItem(
                title=f"Travel to {request.destination}",
                action_type="travel_event",
                source_type="travel",
                description=_route_description(primary_route, f"Travel from {request.origin} to {request.destination}."),
                start_time=_ensure_aware(request.depart_at),
                end_time=_ensure_aware(request.depart_at) + timedelta(minutes=_route_minutes(primary_route, fallback_hours=3)),
                location=request.origin,
                priority="medium",
            )
        )
    if request.accommodation_needed:
        items.append(
            ActionItem(
                title="Confirm accommodation check-in and deposit terms",
                action_type="tenancy_action",
                source_type="travel",
                description="Review accommodation address, check-in time, cancellation policy, and deposit terms.",
                deadline=_ensure_aware(request.depart_at) - timedelta(days=2) if request.depart_at else None,
                priority="high",
            )
        )
    return items


def _information_sources(
    request: TravelItineraryRequest,
    provider_result: TravelProviderResult,
    weather: WeatherLookupResponse | None,
) -> list[TravelInformationSource]:
    sources = [
        TravelInformationSource(
            name="user_trip_request",
            source_type="user_provided",
            description=f"Origin={request.origin}; destination={request.destination}; purpose={request.purpose}.",
            confidence=1.0,
        )
    ]
    if provider_result.route_suggestions:
        verified = any(route.source == "provider_verified" for route in provider_result.route_suggestions)
        sources.append(
            TravelInformationSource(
                name="route_suggestions",
                source_type="provider_verified" if verified else "estimated",
                description="Route timing and distance suggestions used to schedule travel blocks.",
                confidence=max(route.confidence for route in provider_result.route_suggestions),
                tool_name="travel.maps.directions" if verified else None,
            )
        )
    if provider_result.place_suggestions:
        sources.append(
            TravelInformationSource(
                name="place_suggestions",
                source_type="provider_verified",
                description="Local places used to populate orientation and activity blocks.",
                confidence=max(place.confidence for place in provider_result.place_suggestions),
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


def _primary_route(routes: list[RouteSuggestion]) -> RouteSuggestion | None:
    if not routes:
        return None
    return sorted(routes, key=lambda route: (route.source != "provider_verified", route.estimated_minutes or 10_000))[0]


def _route_minutes(route: RouteSuggestion | None, fallback_hours: int) -> int:
    if route is None or route.estimated_minutes is None:
        return fallback_hours * 60
    return max(route.estimated_minutes, 30)


def _route_description(route: RouteSuggestion | None, fallback: str) -> str:
    if route is None:
        return fallback
    details = []
    if route.estimated_minutes is not None:
        details.append(f"estimated {route.estimated_minutes} minutes")
    if route.distance_km is not None:
        details.append(f"{route.distance_km} km")
    source = "Google Maps" if route.source == "provider_verified" else "local estimate"
    joined = ", ".join(details) if details else "duration unavailable"
    return f"{fallback} Planning basis: {source}, {joined}; no booking is performed by the agent."


def _local_orientation_description(places: list[TravelPlaceSuggestion]) -> str:
    if not places:
        return "Confirm practical transport, food, pharmacy, and emergency options near the destination."
    names = ", ".join(place.name for place in places[:3])
    return f"Use provider-suggested nearby options for orientation: {names}. Verify opening times before relying on them."


def _first_place_location(places: list[TravelPlaceSuggestion]) -> str | None:
    if not places:
        return None
    return places[0].location


def _place_for_day(places: list[TravelPlaceSuggestion], index: int) -> TravelPlaceSuggestion | None:
    if not places:
        return None
    return places[(index - 1) % len(places)]


def _purpose_description(place: TravelPlaceSuggestion | None) -> str:
    if place is None:
        return "Keep the plan flexible and verify exact venue opening times from official sources."
    return f"Provider-suggested activity anchor: {place.name}. Verify opening times, access rules, and suitability before committing."
