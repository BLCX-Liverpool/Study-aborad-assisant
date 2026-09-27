import asyncio
from dataclasses import dataclass, field

from app.schemas.travel import (
    RouteSuggestion,
    TravelItineraryRequest,
    TravelPlaceSuggestion,
    TravelPlanRequest,
)
from app.tools.mcp_adapters import GoogleMapsDirectionsTool, GoogleMapsPlacesTool
from app.tools.models import ToolAvailabilityStatus


@dataclass
class TravelProviderResult:
    route_suggestions: list[RouteSuggestion] = field(default_factory=list)
    place_suggestions: list[TravelPlaceSuggestion] = field(default_factory=list)
    tool_statuses: list[ToolAvailabilityStatus] = field(default_factory=list)


class GoogleMapsTravelProvider:
    def __init__(
        self,
        directions_tool: GoogleMapsDirectionsTool | None = None,
        places_tool: GoogleMapsPlacesTool | None = None,
    ) -> None:
        self.directions_tool = directions_tool or GoogleMapsDirectionsTool()
        self.places_tool = places_tool or GoogleMapsPlacesTool()

    def route_status(self) -> ToolAvailabilityStatus:
        return self.directions_tool.availability()

    def places_status(self) -> ToolAvailabilityStatus:
        return self.places_tool.availability()

    def collect(self, request: TravelPlanRequest | TravelItineraryRequest) -> TravelProviderResult:
        route_payloads = [
            self.directions_tool.lookup_sync(
                origin=request.origin,
                destination=request.destination,
                mode=mode,
                depart_at=request.depart_at.isoformat() if request.depart_at else None,
            )
            for mode in _route_modes(request)
        ]
        place_payloads = [
            self.places_tool.search_sync(
                location=request.destination,
                query=query,
                category=category,
                max_results=2,
            )
            for query, category in _place_queries(request)
        ]
        return _provider_result_from_payloads(route_payloads, place_payloads)

    async def collect_async(self, request: TravelPlanRequest | TravelItineraryRequest) -> TravelProviderResult:
        route_tasks = [
            self.directions_tool.lookup_async(
                origin=request.origin,
                destination=request.destination,
                mode=mode,
                depart_at=request.depart_at.isoformat() if request.depart_at else None,
            )
            for mode in _route_modes(request)
        ]
        place_tasks = [
            self.places_tool.search_async(
                location=request.destination,
                query=query,
                category=category,
                max_results=2,
            )
            for query, category in _place_queries(request)
        ]
        route_payloads, place_payloads = await asyncio.gather(
            asyncio.gather(*route_tasks),
            asyncio.gather(*place_tasks),
        )
        return _provider_result_from_payloads(list(route_payloads), list(place_payloads))


class LocalRouteEstimateProvider:
    def collect(self, request: TravelPlanRequest | TravelItineraryRequest) -> TravelProviderResult:
        suggestions = [
            RouteSuggestion(
                origin=request.origin,
                destination=request.destination,
                mode="public_transport_estimate",
                estimated_minutes=90,
                source="estimated",
                confidence=0.25,
                provider_name="local_estimate",
                notes=[
                    "This is a local planning estimate, not a maps-provider route.",
                    "Verify transport duration and disruptions with official transit or maps tools before travel.",
                ],
            )
        ]
        if request.budget_amount is not None:
            suggestions.append(
                RouteSuggestion(
                    origin=request.origin,
                    destination=request.destination,
                    mode="budget_option_estimate",
                    estimated_minutes=120,
                    source="estimated",
                    confidence=0.2,
                    provider_name="local_estimate",
                    notes=[
                        "Budget route is an estimate only.",
                        "Compare coach, railcard, off-peak rail, or shared transfer before paying.",
                    ],
                )
            )
        return TravelProviderResult(route_suggestions=suggestions)


class TravelRouteProvider:
    def __init__(
        self,
        maps_provider: GoogleMapsTravelProvider | None = None,
        local_estimate_provider: LocalRouteEstimateProvider | None = None,
    ) -> None:
        self.maps_provider = maps_provider or GoogleMapsTravelProvider()
        self.local_estimate_provider = local_estimate_provider or LocalRouteEstimateProvider()

    def statuses(self) -> list[ToolAvailabilityStatus]:
        return [self.maps_provider.route_status(), self.maps_provider.places_status()]

    def collect(self, request: TravelPlanRequest | TravelItineraryRequest) -> TravelProviderResult:
        provider_result = self.maps_provider.collect(request)
        return self._with_local_fallback(request, provider_result)

    async def collect_async(self, request: TravelPlanRequest | TravelItineraryRequest) -> TravelProviderResult:
        provider_result = await self.maps_provider.collect_async(request)
        return self._with_local_fallback(request, provider_result)

    def suggest(self, request: TravelPlanRequest | TravelItineraryRequest) -> list[RouteSuggestion]:
        return self.collect(request).route_suggestions

    def suggest_places(self, request: TravelPlanRequest | TravelItineraryRequest) -> list[TravelPlaceSuggestion]:
        return self.collect(request).place_suggestions

    def _with_local_fallback(
        self,
        request: TravelPlanRequest | TravelItineraryRequest,
        provider_result: TravelProviderResult,
    ) -> TravelProviderResult:
        if provider_result.route_suggestions:
            return provider_result
        local_result = self.local_estimate_provider.collect(request)
        return TravelProviderResult(
            route_suggestions=local_result.route_suggestions,
            place_suggestions=provider_result.place_suggestions,
            tool_statuses=provider_result.tool_statuses or self.statuses(),
        )


def _provider_result_from_payloads(route_payloads: list[dict], place_payloads: list[dict]) -> TravelProviderResult:
    routes = []
    places = []
    statuses = []
    for payload in route_payloads:
        statuses.append(ToolAvailabilityStatus.model_validate(payload["provider_status"]))
        routes.extend(_routes_from_payload(payload))
    for payload in place_payloads:
        statuses.append(ToolAvailabilityStatus.model_validate(payload["provider_status"]))
        places.extend(_places_from_payload(payload))
    return TravelProviderResult(
        route_suggestions=_dedupe_routes(routes),
        place_suggestions=_dedupe_places(places),
        tool_statuses=_dedupe_statuses(statuses),
    )


def _routes_from_payload(payload: dict) -> list[RouteSuggestion]:
    provider_status = payload.get("provider_status") or {}
    if not provider_status.get("available"):
        return []
    suggestions = []
    for item in payload.get("routes") or []:
        suggestions.append(
            RouteSuggestion(
                origin=item.get("origin") or "",
                destination=item.get("destination") or "",
                mode=item.get("mode") or "transit",
                estimated_minutes=item.get("estimated_minutes"),
                distance_km=item.get("distance_km"),
                source="provider_verified",
                confidence=0.85,
                provider_name="google_maps",
                provider_metadata=item.get("provider_metadata") or {},
                notes=_route_notes(item),
            )
        )
    return suggestions


def _places_from_payload(payload: dict) -> list[TravelPlaceSuggestion]:
    provider_status = payload.get("provider_status") or {}
    if not provider_status.get("available"):
        return []
    suggestions = []
    for item in payload.get("places") or []:
        rating = item.get("rating")
        count = item.get("user_rating_count")
        suggestions.append(
            TravelPlaceSuggestion(
                name=item.get("name") or "Unknown place",
                category=item.get("category") or "place",
                location=item.get("location") or "",
                source="provider_verified",
                confidence=_place_confidence(rating, count),
                provider_name="google_maps",
                notes=_place_notes(item),
                provider_metadata=item.get("provider_metadata") or {},
            )
        )
    return suggestions


def _route_notes(item: dict) -> list[str]:
    notes = ["Route duration and distance came from Google Maps Directions."]
    if item.get("summary"):
        notes.append(f"Route summary: {item['summary']}.")
    if item.get("warnings"):
        notes.extend(str(warning) for warning in item["warnings"][:2])
    if item.get("steps"):
        notes.append("Detailed step instructions are retained in provider metadata/tool output, not treated as booking confirmation.")
    return notes


def _place_notes(item: dict) -> list[str]:
    notes = ["Place came from Google Places Text Search."]
    if item.get("rating") is not None:
        notes.append(f"Rating: {item['rating']} based on {item.get('user_rating_count') or 0} reviews.")
    if item.get("google_maps_uri"):
        notes.append(f"Google Maps URL: {item['google_maps_uri']}")
    return notes


def _place_confidence(rating: float | None, user_rating_count: int | None) -> float:
    if rating is None:
        return 0.65
    count_bonus = 0.1 if user_rating_count and user_rating_count >= 50 else 0.0
    return min(0.9, 0.65 + count_bonus + max(0, (rating - 3.5) * 0.05))


def _route_modes(request: TravelPlanRequest | TravelItineraryRequest) -> list[str]:
    lowered_constraints = " ".join(request.constraints).lower()
    if "walk" in lowered_constraints or "walking" in lowered_constraints:
        return ["walking", "transit"]
    if "drive" in lowered_constraints or "taxi" in lowered_constraints:
        return ["driving", "transit"]
    if request.purpose in {"airport_arrival", "home_visit"}:
        return ["transit", "driving"]
    if request.purpose == "city_trip":
        return ["transit", "walking"]
    return ["transit"]


def _place_queries(request: TravelPlanRequest | TravelItineraryRequest) -> list[tuple[str, str | None]]:
    if request.purpose == "academic_trip":
        return [("university campus services", None), ("student friendly restaurant", "restaurant"), ("pharmacy", "pharmacy")]
    if request.purpose == "visa_or_immigration":
        return [("visa application centre", None), ("print shop", None), ("cafe near appointment area", "cafe")]
    if request.purpose == "airport_arrival":
        return [("train station airport transfer", None), ("mobile sim card shop", None), ("currency exchange", None)]
    if request.purpose == "city_trip":
        return [("student friendly attraction", "tourist_attraction"), ("affordable restaurant", "restaurant"), ("public transport station", None)]
    return [("student friendly restaurant", "restaurant"), ("pharmacy", "pharmacy"), ("public transport station", None)]


def _dedupe_routes(routes: list[RouteSuggestion]) -> list[RouteSuggestion]:
    seen = set()
    unique = []
    for route in routes:
        key = (route.mode, route.estimated_minutes, route.distance_km)
        if key in seen:
            continue
        seen.add(key)
        unique.append(route)
    return unique[:4]


def _dedupe_places(places: list[TravelPlaceSuggestion]) -> list[TravelPlaceSuggestion]:
    seen = set()
    unique = []
    for place in places:
        key = (place.name.lower(), place.location.lower())
        if key in seen:
            continue
        seen.add(key)
        unique.append(place)
    return unique[:6]


def _dedupe_statuses(statuses: list[ToolAvailabilityStatus]) -> list[ToolAvailabilityStatus]:
    by_name: dict[str, ToolAvailabilityStatus] = {}
    for status in statuses:
        current = by_name.get(status.name)
        if current is None or _status_rank(status.status) > _status_rank(current.status):
            by_name[status.name] = status
    return list(by_name.values())


def _status_rank(status: str) -> int:
    return {"degraded": 4, "available": 3, "not_connected": 1, "unavailable": 0}.get(status, 0)
