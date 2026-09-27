from datetime import date, timedelta
from typing import Any

import httpx

from app.core.permissions import PermissionLevel
from app.schemas.tools import WeatherForecast, WeatherLookupRequest, WeatherLookupResponse
from app.tools.models import ToolSpec

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WEATHER_CODES = {
    0: "clear",
    1: "mainly_clear",
    2: "partly_cloudy",
    3: "overcast",
    45: "fog",
    48: "rime_fog",
    51: "light_drizzle",
    53: "drizzle",
    55: "heavy_drizzle",
    61: "light_rain",
    63: "rain",
    65: "heavy_rain",
    71: "light_snow",
    73: "snow",
    75: "heavy_snow",
    80: "rain_showers",
    81: "rain_showers",
    82: "violent_rain_showers",
    95: "thunderstorm",
}


class WeatherLookupTool:
    spec = ToolSpec(
        name="weather.lookup",
        description="Look up a short weather forecast for student travel planning.",
        permission_level=PermissionLevel.SEARCH,
        input_schema=WeatherLookupRequest.model_json_schema(),
        output_schema=WeatherLookupResponse.model_json_schema(),
    )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        request = WeatherLookupRequest.model_validate(arguments)
        response = await self.lookup(request)
        return response.model_dump(mode="json")

    async def lookup(self, request: WeatherLookupRequest) -> WeatherLookupResponse:
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                geo = await client.get(GEOCODING_URL, params={"name": request.location, "count": 1, "language": "en"})
                geo.raise_for_status()
                location = _first_location(geo.json(), request.location)
                forecast_params: dict[str, Any] = {
                    "latitude": location["latitude"],
                    "longitude": location["longitude"],
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                    "forecast_days": request.days,
                    "timezone": "auto",
                }
                if request.start_date is not None:
                    forecast_params["start_date"] = request.start_date.isoformat()
                    forecast_params["end_date"] = (request.start_date + timedelta(days=request.days - 1)).isoformat()
                    forecast_params.pop("forecast_days", None)

                forecast = await client.get(FORECAST_URL, params=forecast_params)
                forecast.raise_for_status()
        except Exception as exc:
            return WeatherLookupResponse(
                location=request.location,
                forecasts=[],
                assumptions=[
                    "Weather provider lookup failed; user should recheck weather manually before departure.",
                    "No booking, cancellation, or payment decision should be made from this fallback response.",
                ],
                source="fallback",
                recoverable_error=f"{type(exc).__name__}: {exc}",
            )

        resolved_location = _location_name(location)
        return WeatherLookupResponse(
            location=resolved_location,
            forecasts=_parse_daily_forecasts(forecast.json(), resolved_location),
            assumptions=[
                "Weather is advisory and should be rechecked before departure.",
                "Forecast provider is Open-Meteo; no booking or payment action is performed.",
            ],
        )


def _first_location(payload: dict[str, Any], fallback_location: str) -> dict[str, Any]:
    results = payload.get("results") or []
    if not results:
        raise RuntimeError(f"No weather location found for {fallback_location!r}.")
    return results[0]


def _location_name(location: dict[str, Any]) -> str:
    parts = [location.get("name"), location.get("admin1"), location.get("country")]
    return ", ".join(str(part) for part in parts if part)


def _parse_daily_forecasts(payload: dict[str, Any], location: str) -> list[WeatherForecast]:
    daily = payload.get("daily") or {}
    dates = daily.get("time") or []
    codes = daily.get("weather_code") or []
    max_temps = daily.get("temperature_2m_max") or []
    min_temps = daily.get("temperature_2m_min") or []
    rain_probs = daily.get("precipitation_probability_max") or []

    forecasts: list[WeatherForecast] = []
    for index, raw_date in enumerate(dates):
        condition = WEATHER_CODES.get(_value_at(codes, index), "unknown")
        forecasts.append(
            WeatherForecast(
                date=date.fromisoformat(raw_date),
                location=location,
                condition=condition,
                temperature_min_c=_value_at(min_temps, index),
                temperature_max_c=_value_at(max_temps, index),
                precipitation_probability=_value_at(rain_probs, index),
                notes=_weather_notes(condition, _value_at(rain_probs, index)),
            )
        )
    return forecasts


def _value_at(values: list[Any], index: int) -> Any:
    if index >= len(values):
        return None
    return values[index]


def _weather_notes(condition: str, rain_probability: int | None) -> list[str]:
    notes = []
    if "rain" in condition or "drizzle" in condition or (rain_probability is not None and rain_probability >= 50):
        notes.append("Pack waterproof layers and allow extra local transport time.")
    if "snow" in condition:
        notes.append("Check rail or road disruptions before leaving.")
    if condition in {"clear", "mainly_clear"}:
        notes.append("Weather looks low-risk, but recheck before departure.")
    return notes
