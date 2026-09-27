from datetime import UTC, date, datetime
import sys

import pytest

from app.agents.finance.service import FinanceAgentService
from app.agents.finance.bill_parser import FinanceBillParser
from app.agents.finance.budget_goals import BudgetGoalPlanner
from app.agents.travel.itinerary import TravelItineraryGenerator
from app.agents.travel.persistence import TravelMemoryConfirmationService, TravelPlannerPersistenceService
from app.agents.travel.route_provider import TravelProviderResult
from app.agents.travel.service import TravelAgentService
from app.documents.models import DocumentContentType, ParsedDocument, ParsedDocumentElement
from app.schemas.finance import BudgetGoalInput, BudgetGoalRequest, FinanceBillParseRequest
from app.schemas.planner import SavedPlannerOutput
from app.schemas.tools import WeatherForecast, WeatherLookupRequest
from app.schemas.travel import RouteSuggestion, TravelItineraryRequest, TravelMemoryCandidate, TravelPlaceSuggestion
from app.tools.executor import ToolExecutor
from app.tools.logging import ToolExecutionLogger
from app.tools.mcp_adapters import BrowserMcpSearchExtractTool, GoogleMapsDirectionsTool, GoogleMapsPlacesTool
from app.tools.models import ToolCallRequest, ToolSpec
from app.tools.registry import ToolRegistry, build_default_tool_registry
from app.tools.weather import WeatherLookupTool, _parse_daily_forecasts
from app.core.permissions import PermissionLevel


def test_default_tool_registry_exposes_weather_lookup() -> None:
    registry = build_default_tool_registry()

    specs = registry.list_specs()
    names = {spec.name for spec in specs}

    assert {
        "weather.lookup",
        "research.arxiv.search",
        "research.web.search",
        "reminder.draft",
        "calendar.event.draft",
        "browser.mcp.search_extract",
        "travel.maps.directions",
        "travel.maps.places",
    }.issubset(names)
    weather = registry.get("weather.lookup").spec
    assert weather.permission_level == PermissionLevel.SEARCH
    assert weather.requires_approval is False
    assert registry.get("calendar.event.draft").spec.permission_level == PermissionLevel.WRITE_DRAFT
    assert registry.get("calendar.event.draft").spec.requires_approval is False


def test_default_tool_registry_reports_provider_availability(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("BROWSER_MCP_ENABLED", raising=False)

    registry = build_default_tool_registry()
    statuses = {status.name: status for status in registry.list_availability()}

    assert statuses["travel.maps.directions"].available is False
    assert statuses["travel.maps.directions"].missing_env == ["GOOGLE_MAPS_API_KEY"]
    assert statuses["travel.maps.places"].available is False
    assert statuses["browser.mcp.search_extract"].available is False


def test_browser_mcp_status_available_when_http_endpoint_configured(monkeypatch) -> None:
    monkeypatch.setenv("BROWSER_MCP_ENABLED", "true")
    monkeypatch.setenv("BROWSER_MCP_ENDPOINT", "http://127.0.0.1:8765/mcp")

    status = BrowserMcpSearchExtractTool().availability()

    assert status.available is True
    assert status.status == "available"
    assert status.metadata["transport"] == "http_jsonrpc"


@pytest.mark.asyncio
async def test_browser_mcp_http_runtime_calls_tools_call_and_normalizes_results(monkeypatch) -> None:
    monkeypatch.setenv("BROWSER_MCP_ENABLED", "true")
    monkeypatch.setenv("BROWSER_MCP_ENDPOINT", "http://127.0.0.1:8765/mcp")
    monkeypatch.setenv("BROWSER_MCP_TOOL", "browser.search_extract")
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "jsonrpc": "2.0",
                "id": "browser-search-extract-1",
                "result": {
                    "structuredContent": {
                        "results": [
                            {
                                "title": "University visa guidance",
                                "url": "https://example.edu/visa",
                                "snippet": "Bring passport and proof of address.",
                            }
                        ]
                    }
                },
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("app.tools.browser_mcp.httpx.AsyncClient", FakeAsyncClient)

    output = await BrowserMcpSearchExtractTool().run(
        {
            "task": "Search university visa guidance",
            "url": "https://example.edu/visa",
            "extraction_goal": "Required documents",
        }
    )

    assert output["provider_status"]["available"] is True
    assert output["results"][0]["title"] == "University visa guidance"
    assert output["results"][0]["text"] == "Bring passport and proof of address."
    assert captured["json"]["method"] == "tools/call"
    assert captured["json"]["params"]["name"] == "browser.search_extract"
    assert captured["json"]["params"]["arguments"]["url"] == "https://example.edu/visa"


@pytest.mark.asyncio
async def test_browser_mcp_http_runtime_reports_jsonrpc_error(monkeypatch) -> None:
    monkeypatch.setenv("BROWSER_MCP_ENABLED", "true")
    monkeypatch.setenv("BROWSER_MCP_ENDPOINT", "http://127.0.0.1:8765/mcp")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"jsonrpc": "2.0", "id": "browser-search-extract-1", "error": {"code": -32000, "message": "browser closed"}}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def post(self, url, json, headers):
            return FakeResponse()

    monkeypatch.setattr("app.tools.browser_mcp.httpx.AsyncClient", FakeAsyncClient)

    output = await BrowserMcpSearchExtractTool().run({"task": "Extract visible page text"})

    assert output["provider_status"]["available"] is False
    assert output["provider_status"]["status"] == "degraded"
    assert "browser closed" in output["recoverable_error"]


@pytest.mark.asyncio
async def test_browser_mcp_stdio_runtime_calls_tools_call(monkeypatch, tmp_path) -> None:
    server = tmp_path / "fake_browser_mcp.py"
    server.write_text(
        "\n".join(
            [
                "import json, sys",
                "for line in sys.stdin:",
                "    msg = json.loads(line)",
                "    if msg.get('method') == 'initialize':",
                "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'capabilities': {}}}), flush=True)",
                "    elif msg.get('method') == 'tools/call':",
                "        result = {'content': [{'type': 'text', 'text': 'Visible page text from Browser MCP'}]}",
                "        print(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result}), flush=True)",
                "        break",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BROWSER_MCP_ENABLED", "true")
    monkeypatch.delenv("BROWSER_MCP_ENDPOINT", raising=False)
    monkeypatch.setenv("BROWSER_MCP_COMMAND", f"{sys.executable} {server}")

    output = await BrowserMcpSearchExtractTool().run({"task": "Extract current page"})

    assert output["provider_status"]["available"] is True
    assert output["transport"] == "stdio_jsonrpc"
    assert output["results"][0]["text"] == "Visible page text from Browser MCP"


@pytest.mark.asyncio
async def test_tool_executor_blocks_approval_required_tool() -> None:
    async def fake_handler(arguments):
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="email.send",
            description="Send email",
            permission_level=PermissionLevel.SEND,
        ),
        fake_handler,
    )

    result = await ToolExecutor(registry).run(ToolCallRequest(tool_name="email.send"))

    assert result.success is False
    assert result.requires_approval is True


@pytest.mark.asyncio
async def test_tool_execution_logger_adds_agent_and_tool_runs() -> None:
    class FakeSession:
        def __init__(self):
            self.added = []
            self.flushed = False

        def add(self, item):
            self.added.append(item)

        async def flush(self):
            self.flushed = True

    session = FakeSession()
    result = await ToolExecutor(logger=ToolExecutionLogger(session)).run(
        ToolCallRequest(tool_name="unknown.tool", arguments={"location": "Nowhere"}, user_id="user_1")
    )

    assert result.success is False
    assert session.flushed is True
    assert len(session.added) == 3


def test_weather_daily_forecast_parser_adds_travel_notes() -> None:
    payload = {
        "daily": {
            "time": ["2026-10-03"],
            "weather_code": [63],
            "temperature_2m_min": [8.5],
            "temperature_2m_max": [13.0],
            "precipitation_probability_max": [80],
        }
    }

    forecasts = _parse_daily_forecasts(payload, "Manchester")

    assert forecasts[0].condition == "rain"
    assert forecasts[0].precipitation_probability == 80
    assert any("waterproof" in note for note in forecasts[0].notes)


@pytest.mark.asyncio
async def test_weather_lookup_returns_recoverable_fallback(monkeypatch) -> None:
    class FailingClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise RuntimeError("provider unavailable")

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr("app.tools.weather.httpx.AsyncClient", FailingClient)

    response = await WeatherLookupTool().lookup(WeatherLookupRequest(location="Manchester"))

    assert response.source == "fallback"
    assert response.recoverable_error is not None
    assert response.forecasts == []


def test_google_maps_tools_call_live_endpoints_and_parse_results(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-key")
    calls = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def get(self, url, params):
            calls.append(("get", url, params))
            return FakeResponse(
                {
                    "status": "OK",
                    "routes": [
                        {
                            "summary": "M1",
                            "copyrights": "Map data",
                            "legs": [
                                {
                                    "start_address": "London",
                                    "end_address": "Manchester",
                                    "duration": {"value": 5400, "text": "1 hour 30 mins"},
                                    "distance": {"value": 320000, "text": "320 km"},
                                    "steps": [],
                                }
                            ],
                        }
                    ],
                }
            )

        def post(self, url, json, headers):
            calls.append(("post", url, json, headers))
            return FakeResponse(
                {
                    "places": [
                        {
                            "id": "place-1",
                            "displayName": {"text": "Campus Cafe"},
                            "formattedAddress": "1 Student Street, Manchester",
                            "googleMapsUri": "https://maps.google.com/?cid=1",
                            "rating": 4.4,
                            "userRatingCount": 120,
                            "types": ["restaurant"],
                            "businessStatus": "OPERATIONAL",
                        }
                    ]
                }
            )

    monkeypatch.setattr("app.tools.mcp_adapters.httpx.Client", FakeClient)

    route_payload = GoogleMapsDirectionsTool().lookup_sync("London", "Manchester", mode="driving")
    place_payload = GoogleMapsPlacesTool().search_sync("Manchester", "student friendly restaurant", category="restaurant")

    assert route_payload["routes"][0]["estimated_minutes"] == 90
    assert route_payload["routes"][0]["distance_km"] == 320
    assert place_payload["places"][0]["name"] == "Campus Cafe"
    assert place_payload["places"][0]["rating"] == 4.4
    assert calls[0][0] == "get"
    assert calls[0][2]["key"] == "test-key"
    assert calls[1][0] == "post"
    assert calls[1][3]["X-Goog-Api-Key"] == "test-key"


def test_travel_itinerary_generator_creates_days_budget_and_weather_notes(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    request = TravelItineraryRequest(
        user_id="user_1",
        origin="London",
        destination="Manchester",
        depart_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
        return_at=datetime(2026, 10, 4, 18, 0, tzinfo=UTC),
        purpose="academic_trip",
        budget_amount=200,
        accommodation_needed=True,
        weather_forecasts=[
            WeatherForecast(
                date=date(2026, 10, 3),
                location="Manchester",
                condition="rain",
                precipitation_probability=80,
                notes=["Pack waterproof layers."],
            )
        ],
    )

    output = TravelItineraryGenerator().generate(request)

    assert len(output.days) == 2
    assert output.days[0].weather is not None
    assert any(item.category == "accommodation" for item in output.budget_breakdown)
    assert output.requires_booking_approval is True
    assert output.route_suggestions
    assert output.route_suggestions[0].source == "estimated"
    assert output.route_suggestions[0].provider_name == "local_estimate"
    assert output.tool_statuses
    assert any(item.source_type == "travel" for item in output.planner_items)


def test_travel_itinerary_uses_provider_routes_and_places() -> None:
    class FakeRouteProvider:
        def collect(self, request):
            return TravelProviderResult(
                route_suggestions=[
                    RouteSuggestion(
                        origin="London",
                        destination="Manchester",
                        mode="transit",
                        estimated_minutes=75,
                        distance_km=300,
                        source="provider_verified",
                        confidence=0.85,
                        provider_name="google_maps",
                    )
                ],
                place_suggestions=[
                    TravelPlaceSuggestion(
                        name="Campus Cafe",
                        category="restaurant",
                        location="1 Student Street, Manchester",
                        source="provider_verified",
                        confidence=0.85,
                        provider_name="google_maps",
                    )
                ],
            )

        def statuses(self):
            return []

    request = TravelItineraryRequest(
        user_id="user_1",
        origin="London",
        destination="Manchester",
        depart_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
        return_at=datetime(2026, 10, 4, 18, 0, tzinfo=UTC),
        purpose="academic_trip",
        budget_amount=200,
        accommodation_needed=True,
    )

    output = TravelItineraryGenerator(route_provider=FakeRouteProvider()).generate(request)

    assert output.route_suggestions[0].source == "provider_verified"
    assert output.place_suggestions[0].name == "Campus Cafe"
    assert output.days[0].events[0].end_time == datetime(2026, 10, 3, 10, 15, tzinfo=UTC)
    assert "Campus Cafe" in output.days[0].events[1].description
    assert output.information_sources[1].tool_name == "travel.maps.directions"
    assert any(item.estimate_basis and "Google Maps route context" in item.estimate_basis for item in output.budget_breakdown)


@pytest.mark.asyncio
async def test_travel_planner_persistence_requires_confirmation() -> None:
    class FakePlannerRepository:
        async def save_plan(self, user_id, plan):
            raise AssertionError("save_plan should not be called without confirmation")

    request = TravelItineraryRequest(
        user_id="user_1",
        origin="London",
        destination="Manchester",
        depart_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
        persist_to_planner=True,
        planner_confirmed=False,
    )
    output = TravelItineraryGenerator().generate(request)

    result = await TravelPlannerPersistenceService(FakePlannerRepository()).persist_itinerary(
        request=request,
        output=output,
    )

    assert result.status == "needs_confirmation"
    assert result.saved is None


@pytest.mark.asyncio
async def test_travel_planner_persistence_saves_confirmed_itinerary() -> None:
    saved_plan = {}

    class FakePlannerRepository:
        async def list_schedule_blocks(self, user_id):
            return []

        async def save_plan(self, user_id, plan):
            saved_plan["user_id"] = user_id
            saved_plan["plan"] = plan
            return SavedPlannerOutput(task_ids=["task_1"], event_ids=["event_1"], reminder_ids=["reminder_1"])

    request = TravelItineraryRequest(
        user_id="user_1",
        origin="London",
        destination="Manchester",
        depart_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
        persist_to_planner=True,
        planner_confirmed=True,
        accommodation_needed=True,
    )
    output = TravelItineraryGenerator().generate(request)

    result = await TravelPlannerPersistenceService(FakePlannerRepository()).persist_itinerary(
        request=request,
        output=output,
    )

    assert result.status == "saved"
    assert result.saved.event_ids == ["event_1"]
    assert saved_plan["user_id"] == "user_1"
    assert saved_plan["plan"].events
    assert saved_plan["plan"].tasks


@pytest.mark.asyncio
async def test_travel_memory_confirmation_flow_pends_then_confirms_candidates() -> None:
    class FakeMemoryRepository:
        def __init__(self):
            self.pending = []
            self.confirmed = []

        async def add_memory_candidate(self, **kwargs):
            memory_id = f"pending_{len(self.pending) + 1}"
            self.pending.append((memory_id, kwargs))
            return memory_id

        async def add_memory(self, **kwargs):
            memory_id = f"confirmed_{len(self.confirmed) + 1}"
            self.confirmed.append((memory_id, kwargs))
            return memory_id

        async def confirm_memory_candidates(self, *, user_id, memory_ids):
            return memory_ids

    repository = FakeMemoryRepository()
    service = TravelMemoryConfirmationService(repository)
    candidates = [TravelMemoryCandidate(content="Travel preference: prefers rail over coach.")]

    pending = await service.persist_candidates(
        user_id="user_1",
        candidates=candidates,
        requested=True,
        confirmed=False,
    )
    confirmed = await service.confirm(user_id="user_1", memory_ids=pending.pending_memory_ids)

    assert pending.status == "pending_confirmation"
    assert pending.pending_memory_ids == ["pending_1"]
    assert repository.pending[0][1]["namespace"] == "travel"
    assert confirmed.status == "confirmed"
    assert confirmed.confirmed_memory_ids == ["pending_1"]


@pytest.mark.asyncio
async def test_travel_memory_confirmed_candidates_are_saved_as_preferences() -> None:
    class FakeMemoryRepository:
        def __init__(self):
            self.saved = []

        async def add_memory(self, **kwargs):
            self.saved.append(kwargs)
            return "memory_1"

    repository = FakeMemoryRepository()
    service = TravelMemoryConfirmationService(repository)

    result = await service.persist_candidates(
        user_id="user_1",
        candidates=[TravelMemoryCandidate(content="Travel budget preference: GBP 200.")],
        requested=True,
        confirmed=True,
    )

    assert result.status == "confirmed"
    assert result.confirmed_memory_ids == ["memory_1"]
    assert repository.saved[0]["memory_type"] == "user_preference"
    assert repository.saved[0]["access_policy"]["confirmed"] is True


def test_travel_agent_marks_provider_status_and_estimate_sources(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    request = TravelItineraryRequest(
        user_id="user_1",
        origin="London",
        destination="Manchester",
        depart_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
        purpose="academic_trip",
        budget_amount=120,
        accommodation_needed=True,
    )

    plan = TravelAgentService().plan(request)

    assert plan.route_suggestions
    assert plan.route_suggestions[0].source == "estimated"
    assert plan.route_suggestions[0].confidence < 0.5
    assert plan.place_suggestions == []
    assert any(status.name == "travel.maps.directions" and not status.available for status in plan.tool_statuses)
    assert any(source.source_type == "estimated" for source in plan.information_sources)
    assert all(item.estimate_basis for item in plan.budget_breakdown)


@pytest.mark.asyncio
async def test_travel_agent_async_injects_weather_status() -> None:
    class FakeWeatherTool:
        async def lookup(self, request):
            return type(
                "WeatherResponse",
                (),
                {
                    "forecasts": [
                        WeatherForecast(
                            date=date(2026, 10, 3),
                            location=request.location,
                            condition="rain",
                            notes=["Pack waterproof layers."],
                        )
                    ],
                    "recoverable_error": None,
                    "source": "fake-weather",
                },
            )()

    request = TravelItineraryRequest(
        user_id="user_1",
        origin="London",
        destination="Manchester",
        depart_at=datetime(2026, 10, 3, 9, 0, tzinfo=UTC),
        purpose="academic_trip",
    )

    plan = await TravelAgentService(weather_tool=FakeWeatherTool()).plan_async(request)

    assert plan.weather_forecasts[0].condition == "rain"
    assert any(status.name == "weather.lookup" and status.available for status in plan.tool_statuses)


def test_finance_bill_parser_extracts_obligation_and_due_task() -> None:
    request = FinanceBillParseRequest(
        user_id="user_1",
        raw_text="Tuition invoice\nAmount due: £1,250.00\nPayment due: 2026-10-12",
        source_name="tuition_invoice.txt",
    )

    output = FinanceBillParser().parse(request)

    assert output.obligations[0].bill_type == "tuition"
    assert output.obligations[0].amount == 1250.0
    assert output.obligations[0].due_date == date(2026, 10, 12)
    assert output.action_items[0].deadline is not None


@pytest.mark.asyncio
async def test_finance_bill_service_parses_file_text_and_verifies(tmp_path) -> None:
    source_path = tmp_path / "rent.txt"
    source_path.write_text("Rent invoice\nAmount due: £700\nPayment due: 2026-10-20", encoding="utf-8")
    captured = {}

    class FakeDocumentParser:
        def parse(self, source_path, file_id, source_name=None, mime_type=None):
            return ParsedDocument(
                file_id=file_id,
                source_name=source_name or source_path.name,
                source_path=source_path,
                elements=[
                    ParsedDocumentElement(
                        content_type=DocumentContentType.PARAGRAPH,
                        text=source_path.read_text(encoding="utf-8"),
                    )
                ],
            )

    class FakeVerifier:
        async def verify(self, output, source_text):
            captured["source_text"] = source_text
            return output

    output = await FinanceAgentService(
        document_parser=FakeDocumentParser(),
        bill_verifier=FakeVerifier(),
    ).parse_bill_async(
        FinanceBillParseRequest(
            user_id="user_1",
            source_path=source_path,
            source_name="rent.txt",
        )
    )

    assert output.obligations[0].amount == 700.0
    assert "Rent invoice" in captured["source_text"]


def test_budget_goal_planner_flags_unrealistic_goal() -> None:
    request = BudgetGoalRequest(
        user_id="user_1",
        monthly_income=1000,
        monthly_expense=950,
        goals=[
            BudgetGoalInput(
                name="Emergency fund",
                target_amount=600,
                current_amount=100,
                target_date=date(2026, 10, 1),
                priority="high",
            )
        ],
    )

    output = BudgetGoalPlanner().review(request)

    assert output.available_monthly_surplus == 50
    assert output.goal_reviews[0].status == "at_risk"
    assert any(item.priority == "high" for item in output.action_items)


def test_budget_goal_planner_accounts_for_recurring_contributions() -> None:
    request = BudgetGoalRequest(
        user_id="user_1",
        monthly_income=1500,
        monthly_expense=900,
        goals=[
            BudgetGoalInput(
                name="Visa renewal buffer",
                target_amount=1000,
                current_amount=200,
                target_date=date(2026, 12, 1),
                recurring_contribution=150,
            )
        ],
        memory_preferences=["Prefers conservative monthly savings buffers."],
    )

    output = BudgetGoalPlanner().review(request)

    assert output.available_monthly_surplus == 450
    assert any("recurring" in assumption.lower() for assumption in output.assumptions)
    assert any("memory" in assumption.lower() for assumption in output.assumptions)
