import os
from datetime import datetime
from typing import Any

import httpx

from app.core.permissions import PermissionLevel
from app.tools.browser_mcp import BrowserMcpRuntime
from app.tools.models import ToolAvailabilityStatus, ToolSpec

GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.googleMapsUri",
        "places.rating",
        "places.userRatingCount",
        "places.types",
        "places.businessStatus",
        "places.location",
    ]
)


class BrowserMcpSearchExtractTool(BrowserMcpRuntime):
    pass


class GoogleMapsDirectionsTool:
    spec = ToolSpec(
        name="travel.maps.directions",
        description="Look up route distance and duration through a Google Maps-compatible provider. Returns unavailable when provider credentials/runtime are missing.",
        permission_level=PermissionLevel.SEARCH,
        capability="travel_route_directions",
        provider_name="google_maps",
        required_env=["GOOGLE_MAPS_API_KEY"],
        input_schema={
            "type": "object",
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "mode": {"type": "string"},
                "depart_at": {"type": "string"},
                "alternatives": {"type": "boolean"},
            },
            "required": ["origin", "destination"],
        },
    )

    def availability(self) -> ToolAvailabilityStatus:
        missing = [name for name in self.spec.required_env if not os.getenv(name)]
        return ToolAvailabilityStatus(
            name=self.spec.name,
            capability=self.spec.capability or self.spec.name,
            available=not missing,
            status="unavailable" if missing else "available",
            permission_level=self.spec.permission_level,
            required_env=self.spec.required_env,
            missing_env=missing,
            recoverable_error=(
                "GOOGLE_MAPS_API_KEY is not configured."
                if missing
                else None
            ),
            metadata={"provider_name": self.spec.provider_name},
        )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.lookup_async(**_directions_arguments(arguments))

    def lookup_sync(
        self,
        origin: str,
        destination: str,
        mode: str = "transit",
        depart_at: str | None = None,
        alternatives: bool = True,
    ) -> dict[str, Any]:
        status = self.availability()
        if not status.available:
            return _unavailable_response(status, "routes")

        params = _directions_params(origin, destination, mode, depart_at, alternatives)
        try:
            with httpx.Client(timeout=_google_timeout(), follow_redirects=True) as client:
                response = client.get(GOOGLE_DIRECTIONS_URL, params=params)
                response.raise_for_status()
        except Exception as exc:
            return _provider_error_response(status, "routes", exc)
        return _parse_directions_payload(response.json(), status, mode)

    async def lookup_async(
        self,
        origin: str,
        destination: str,
        mode: str = "transit",
        depart_at: str | None = None,
        alternatives: bool = True,
    ) -> dict[str, Any]:
        status = self.availability()
        if not status.available:
            return _unavailable_response(status, "routes")

        params = _directions_params(origin, destination, mode, depart_at, alternatives)
        try:
            async with httpx.AsyncClient(timeout=_google_timeout(), follow_redirects=True) as client:
                response = await client.get(GOOGLE_DIRECTIONS_URL, params=params)
                response.raise_for_status()
        except Exception as exc:
            return _provider_error_response(status, "routes", exc)
        return _parse_directions_payload(response.json(), status, mode)


class GoogleMapsPlacesTool:
    spec = ToolSpec(
        name="travel.maps.places",
        description="Look up places, attractions, venues, and local services through a Google Maps-compatible provider.",
        permission_level=PermissionLevel.SEARCH,
        capability="travel_places_search",
        provider_name="google_maps",
        required_env=["GOOGLE_MAPS_API_KEY"],
        input_schema={
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "query": {"type": "string"},
                "category": {"type": "string"},
                "max_results": {"type": "integer"},
            },
            "required": ["location", "query"],
        },
    )

    def availability(self) -> ToolAvailabilityStatus:
        missing = [name for name in self.spec.required_env if not os.getenv(name)]
        return ToolAvailabilityStatus(
            name=self.spec.name,
            capability=self.spec.capability or self.spec.name,
            available=not missing,
            status="unavailable" if missing else "available",
            permission_level=self.spec.permission_level,
            required_env=self.spec.required_env,
            missing_env=missing,
            recoverable_error=(
                "GOOGLE_MAPS_API_KEY is not configured."
                if missing
                else None
            ),
            metadata={"provider_name": self.spec.provider_name},
        )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.search_async(**_places_arguments(arguments))

    def search_sync(
        self,
        location: str,
        query: str,
        category: str | None = None,
        max_results: int = 3,
    ) -> dict[str, Any]:
        status = self.availability()
        if not status.available:
            return _unavailable_response(status, "places")

        payload = _places_payload(location, query, category, max_results)
        try:
            with httpx.Client(timeout=_google_timeout(), follow_redirects=True) as client:
                response = client.post(
                    GOOGLE_PLACES_TEXT_SEARCH_URL,
                    json=payload,
                    headers=_places_headers(),
                )
                response.raise_for_status()
        except Exception as exc:
            return _provider_error_response(status, "places", exc)
        return _parse_places_payload(response.json(), status, location, query, category)

    async def search_async(
        self,
        location: str,
        query: str,
        category: str | None = None,
        max_results: int = 3,
    ) -> dict[str, Any]:
        status = self.availability()
        if not status.available:
            return _unavailable_response(status, "places")

        payload = _places_payload(location, query, category, max_results)
        try:
            async with httpx.AsyncClient(timeout=_google_timeout(), follow_redirects=True) as client:
                response = await client.post(
                    GOOGLE_PLACES_TEXT_SEARCH_URL,
                    json=payload,
                    headers=_places_headers(),
                )
                response.raise_for_status()
        except Exception as exc:
            return _provider_error_response(status, "places", exc)
        return _parse_places_payload(response.json(), status, location, query, category)


def _directions_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "origin": arguments["origin"],
        "destination": arguments["destination"],
        "mode": arguments.get("mode") or "transit",
        "depart_at": arguments.get("depart_at"),
        "alternatives": bool(arguments.get("alternatives", True)),
    }


def _places_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "location": arguments["location"],
        "query": arguments["query"],
        "category": arguments.get("category"),
        "max_results": int(arguments.get("max_results") or 3),
    }


def _directions_params(
    origin: str,
    destination: str,
    mode: str,
    depart_at: str | None,
    alternatives: bool,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "origin": origin,
        "destination": destination,
        "mode": mode,
        "alternatives": str(alternatives).lower(),
        "key": os.environ["GOOGLE_MAPS_API_KEY"],
    }
    language = os.getenv("GOOGLE_MAPS_LANGUAGE")
    region = os.getenv("GOOGLE_MAPS_REGION")
    if language:
        params["language"] = language
    if region:
        params["region"] = region
    if mode in {"driving", "transit"}:
        params["departure_time"] = _departure_time(depart_at)
    return params


def _departure_time(depart_at: str | None) -> str:
    if not depart_at:
        return "now"
    if depart_at.isdigit():
        return depart_at
    try:
        return str(int(datetime.fromisoformat(depart_at).timestamp()))
    except ValueError:
        return "now"


def _places_payload(location: str, query: str, category: str | None, max_results: int) -> dict[str, Any]:
    text_query = f"{query} near {location}" if location.lower() not in query.lower() else query
    payload: dict[str, Any] = {
        "textQuery": text_query,
        "maxResultCount": max(1, min(max_results, 10)),
    }
    language = os.getenv("GOOGLE_MAPS_LANGUAGE")
    region = os.getenv("GOOGLE_MAPS_REGION")
    if language:
        payload["languageCode"] = language
    if region:
        payload["regionCode"] = region
    if category:
        payload["includedType"] = category if category.isidentifier() else None
        if payload["includedType"] is None:
            payload.pop("includedType")
    return payload


def _places_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": os.environ["GOOGLE_MAPS_API_KEY"],
        "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
    }


def _google_timeout() -> float:
    return float(os.getenv("GOOGLE_MAPS_TIMEOUT_SECONDS") or "10")


def _parse_directions_payload(payload: dict[str, Any], status: ToolAvailabilityStatus, mode: str) -> dict[str, Any]:
    google_status = payload.get("status")
    if google_status != "OK":
        error = payload.get("error_message") or f"Google Directions returned status {google_status}."
        return _provider_status_response(status, "routes", [], recoverable_error=error)

    routes = []
    for index, route in enumerate(payload.get("routes") or []):
        legs = route.get("legs") or []
        if not legs:
            continue
        duration_seconds = sum(_duration_value(leg) for leg in legs)
        distance_meters = sum((leg.get("distance") or {}).get("value") or 0 for leg in legs)
        steps = []
        for leg in legs:
            for step in (leg.get("steps") or [])[:8]:
                steps.append(
                    {
                        "travel_mode": step.get("travel_mode"),
                        "duration_text": (step.get("duration") or {}).get("text"),
                        "distance_text": (step.get("distance") or {}).get("text"),
                        "html_instructions": step.get("html_instructions"),
                    }
                )
        routes.append(
            {
                "origin": (legs[0].get("start_address") or "").strip(),
                "destination": (legs[-1].get("end_address") or "").strip(),
                "mode": mode,
                "estimated_minutes": round(duration_seconds / 60) if duration_seconds else None,
                "distance_km": round(distance_meters / 1000, 2) if distance_meters else None,
                "summary": route.get("summary"),
                "warnings": route.get("warnings") or [],
                "steps": steps,
                "provider_metadata": {
                    "provider_name": "google_maps",
                    "google_status": google_status,
                    "route_index": index,
                    "copyrights": route.get("copyrights"),
                    "fare": route.get("fare"),
                    "bounds": route.get("bounds"),
                },
            }
        )
    return _provider_status_response(status, "routes", routes)


def _duration_value(leg: dict[str, Any]) -> int:
    duration = leg.get("duration_in_traffic") or leg.get("duration") or {}
    return int(duration.get("value") or 0)


def _parse_places_payload(
    payload: dict[str, Any],
    status: ToolAvailabilityStatus,
    location: str,
    query: str,
    category: str | None,
) -> dict[str, Any]:
    places = []
    for index, place in enumerate(payload.get("places") or []):
        display_name = place.get("displayName") or {}
        places.append(
            {
                "name": display_name.get("text") or "Unknown place",
                "category": category or _first_type(place.get("types")) or query,
                "location": place.get("formattedAddress") or location,
                "rating": place.get("rating"),
                "user_rating_count": place.get("userRatingCount"),
                "google_maps_uri": place.get("googleMapsUri"),
                "place_id": place.get("id"),
                "provider_metadata": {
                    "provider_name": "google_maps",
                    "result_index": index,
                    "types": place.get("types") or [],
                    "business_status": place.get("businessStatus"),
                    "location": place.get("location"),
                },
            }
        )
    return _provider_status_response(status, "places", places)


def _first_type(types: list[str] | None) -> str | None:
    if not types:
        return None
    return types[0].replace("_", " ")


def _unavailable_response(status: ToolAvailabilityStatus, result_key: str) -> dict[str, Any]:
    return _provider_status_response(
        status,
        result_key,
        [],
        recoverable_error=status.recoverable_error,
    )


def _provider_error_response(status: ToolAvailabilityStatus, result_key: str, exc: Exception) -> dict[str, Any]:
    return _provider_status_response(
        status,
        result_key,
        [],
        recoverable_error=f"{type(exc).__name__}: {exc}",
    )


def _provider_status_response(
    status: ToolAvailabilityStatus,
    result_key: str,
    results: list[dict[str, Any]],
    recoverable_error: str | None = None,
) -> dict[str, Any]:
    provider_status = status
    if recoverable_error:
        provider_status = status.model_copy(
            update={
                "available": False,
                "status": "degraded" if not status.missing_env else status.status,
                "recoverable_error": recoverable_error,
            }
        )
    return {
        "provider_status": provider_status.model_dump(mode="json"),
        result_key: results,
        "source": "google_maps",
        "recoverable_error": recoverable_error,
        "assumptions": [
            "Google Maps provider data is advisory and must be rechecked before booking.",
            "No booking, payment, or external submission was performed.",
        ],
    }
