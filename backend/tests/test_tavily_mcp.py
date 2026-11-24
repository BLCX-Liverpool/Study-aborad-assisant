from __future__ import annotations

from contextlib import asynccontextmanager
import os
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.agents.orchestrator.workers import AssignmentWorker, TravelWorker, build_default_workers
from app.agents.travel.service import TravelAgentService
from app.schemas.travel import TravelPlanRequest
from app.tools.executor import ToolExecutor
from app.tools.inputs import BrowserMcpExtractInput, BrowserMcpMapInput, BrowserMcpSearchInput
from app.tools.logging import _logged_output
from app.tools.mcp.client import TavilyMcpClient
from app.tools.mcp.models import EXPECTED_REMOTE_SCHEMAS, TavilyMcpSettings
from app.tools.mcp.tavily import build_tavily_mcp_tools
from app.tools.models import ToolCallRequest, ToolCallResult
from app.tools.registry import ToolRegistry, build_default_tool_registry


class FakeCallResult:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def model_dump(self, **kwargs):
        return self.payload


class FakeTavilySession:
    def __init__(self, responses: dict[str, list[dict]] | None = None, *, schemas=None) -> None:
        self.responses = responses or {}
        self.schemas = _compatible_schemas() if schemas is None else schemas
        self.calls: list[tuple[str, dict]] = []
        self.list_calls = 0

    async def list_tools(self, cursor=None):
        self.list_calls += 1
        tools = [
            SimpleNamespace(name=name, description=f"{name} description", input_schema=schema)
            for name, schema in self.schemas.items()
        ]
        # Unapproved remote tools must be ignored rather than registered.
        tools.append(
            SimpleNamespace(
                name="tavily_research",
                description="Not approved",
                input_schema={"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]},
            )
        )
        return SimpleNamespace(tools=tools, next_cursor=None)

    async def call_tool(self, name, arguments=None, **kwargs):
        self.calls.append((name, dict(arguments or {})))
        queue = self.responses.get(name) or [_success_payload(name)]
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        return FakeCallResult(payload)


def _settings() -> TavilyMcpSettings:
    return TavilyMcpSettings(
        enabled=True,
        endpoint="https://mcp.tavily.test/mcp/",
        api_key="tvly-secret",
        tool_cache_ttl_seconds=300,
        max_sse_event_size=1_048_576,
    )


def _client(session: FakeTavilySession) -> TavilyMcpClient:
    @asynccontextmanager
    async def session_factory(timeout_seconds):
        yield session

    return TavilyMcpClient(_settings(), session_factory=session_factory)


def _compatible_schemas() -> dict[str, dict]:
    schemas = {}
    for name, contract in EXPECTED_REMOTE_SCHEMAS.items():
        schemas[name] = {
            "type": "object",
            "properties": {key: {"type": "string"} for key in contract["properties"]},
            "required": sorted(contract["required"]),
        }
    return schemas


def _success_payload(name: str) -> dict:
    payloads = {
        "tavily_search": {
            "query": "student attractions",
            "results": [
                {
                    "title": "Student guide",
                    "url": "https://example.com/guide",
                    "content": "A concise city guide.",
                    "score": 0.9,
                }
            ],
        },
        "tavily_extract": {
            "results": [
                {
                    "url": "https://example.com/guide",
                    "raw_content": "Full guide content",
                }
            ],
            "failed_results": [],
        },
        "tavily_map": {
            "base_url": "https://example.com",
            "results": ["https://example.com/guide", "https://example.com/policy"],
        },
        "tavily_crawl": {
            "base_url": "https://example.com",
            "results": [
                {"url": "https://example.com/guide", "raw_content": "Crawled guide"}
            ],
        },
    }
    return {
        "content": [{"type": "text", "text": "ignored"}],
        "structuredContent": payloads[name],
        "isError": False,
    }


def test_registry_exposes_four_tavily_tools_and_compatibility_alias(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_MCP_ENABLED", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    registry = build_default_tool_registry()
    names = {spec.name for spec in registry.list_specs()}

    assert {
        "browser.mcp.search",
        "browser.mcp.extract",
        "browser.mcp.map",
        "browser.mcp.crawl",
        "browser.mcp.search_extract",
    }.issubset(names)
    assert registry.get("browser.mcp.search").spec.cache_ttl_seconds == 60
    assert registry.get("browser.mcp.extract").spec.cache_ttl_seconds == 300
    assert registry.get("browser.mcp.crawl").spec.timeout_seconds == 180


def test_tavily_tools_are_restricted_to_assignment_and_travel() -> None:
    workers = build_default_workers()
    browser_tools = {
        "browser.mcp.search",
        "browser.mcp.extract",
        "browser.mcp.map",
        "browser.mcp.crawl",
    }

    assert browser_tools.issubset(set(AssignmentWorker.spec.allowed_tools))
    assert browser_tools.issubset(set(TravelWorker.spec.allowed_tools))
    assert "browser.mcp.search_extract" not in AssignmentWorker.spec.allowed_tools
    assert "browser.mcp.search_extract" not in TravelWorker.spec.allowed_tools
    for worker in workers:
        if worker.spec.intent not in {"assignment", "travel"}:
            assert browser_tools.isdisjoint(worker.spec.allowed_tools)


def test_configured_tavily_tool_is_pending_until_tools_list_discovery() -> None:
    search_tool = build_tavily_mcp_tools(_client(FakeTavilySession()))[0]

    status = search_tool.availability()

    assert status.available is True
    assert status.status == "pending"
    assert status.metadata["discovery_status"] == "pending"


def test_tavily_endpoint_rejects_plain_http_to_protect_bearer_key() -> None:
    settings = TavilyMcpSettings(
        enabled=True,
        endpoint="http://mcp.tavily.test/mcp/",
        api_key="tvly-secret",
        tool_cache_ttl_seconds=300,
        max_sse_event_size=1_048_576,
    )
    search_tool = build_tavily_mcp_tools(TavilyMcpClient(settings))[0]

    status = search_tool.availability()

    assert status.available is False
    assert status.status == "unavailable"
    assert status.missing_env == ["TAVILY_MCP_ENDPOINT"]


@pytest.mark.asyncio
async def test_tavily_tools_discover_map_arguments_and_normalize_all_four_results() -> None:
    session = FakeTavilySession()
    tools = {tool.spec.name: tool for tool in build_tavily_mcp_tools(_client(session))}

    search = await tools["browser.mcp.search"].run(
        {"query": "student attractions", "max_results": 5}
    )
    extract = await tools["browser.mcp.extract"].run(
        {"urls": ["https://example.com/guide"], "extraction_goal": "student discounts"}
    )
    mapped = await tools["browser.mcp.map"].run({"url": "https://example.com"})
    crawled = await tools["browser.mcp.crawl"].run({"url": "https://example.com"})

    assert session.list_calls == 1
    assert search["results"][0]["title"] == "Student guide"
    assert extract["results"][0]["text"] == "Full guide content"
    assert mapped["urls"] == ["https://example.com/guide", "https://example.com/policy"]
    assert crawled["pages"][0]["text"] == "Crawled guide"
    calls = dict(session.calls)
    assert calls["tavily_search"]["query"] == "student attractions"
    assert calls["tavily_extract"]["urls"] == ["https://example.com/guide"]
    assert calls["tavily_extract"]["query"] == "student discounts"
    assert calls["tavily_map"]["allow_external"] is False
    assert calls["tavily_crawl"]["limit"] == 20


@pytest.mark.asyncio
async def test_tavily_tools_normalize_official_text_content_format() -> None:
    responses = {
        "tavily_search": [
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Request ID: req-1\nAnswer: Student discounts are available.\n"
                            "Detailed Results:\n\nTitle: Student guide\nID: result-1\n"
                            "URL: https://example.com/guide\nContent: A concise city guide."
                        ),
                    }
                ],
                "isError": False,
            }
        ],
        "tavily_extract": [
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Detailed Results:\n\nTitle: Policy\nURL: https://example.com/policy\n"
                            "Raw Content: First line.\nSecond line."
                        ),
                    }
                ],
                "isError": False,
            }
        ],
        "tavily_map": [
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Base URL: https://example.com\nMapped URLs:\n"
                            "https://example.com/guide\nhttps://example.com/policy"
                        ),
                    }
                ],
                "isError": False,
            }
        ],
        "tavily_crawl": [
            {
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Base URL: https://example.com\nCrawl Results:\n\n"
                            "URL: https://example.com/guide\nRaw Content: Crawled guide"
                        ),
                    }
                ],
                "isError": False,
            }
        ],
    }
    session = FakeTavilySession(responses=responses)
    tools = {tool.spec.name: tool for tool in build_tavily_mcp_tools(_client(session))}

    search = await tools["browser.mcp.search"].run({"query": "student guide"})
    extract = await tools["browser.mcp.extract"].run({"urls": ["https://example.com/policy"]})
    mapped = await tools["browser.mcp.map"].run({"url": "https://example.com"})
    crawled = await tools["browser.mcp.crawl"].run({"url": "https://example.com"})

    assert search["answer"] == "Student discounts are available."
    assert search["results"][0]["url"] == "https://example.com/guide"
    assert extract["results"][0]["text"] == "First line.\nSecond line."
    assert "https://example.com/policy" in mapped["urls"]
    assert mapped["base_url"] == "https://example.com"
    assert crawled["pages"][0]["text"] == "Crawled guide"


@pytest.mark.asyncio
async def test_tavily_text_error_is_not_mistaken_for_an_empty_success() -> None:
    session = FakeTavilySession(
        responses={
            "tavily_search": [
                {
                    "content": [{"type": "text", "text": "Tavily API error: Invalid API key"}],
                    "isError": False,
                }
            ]
        }
    )
    search_tool = build_tavily_mcp_tools(_client(session))[0]

    output = await search_tool.run({"query": "student guide"})

    assert output["provider_status"]["status"] == "degraded"
    assert output["retryable"] is False
    assert "Invalid API key" in output["recoverable_error"]


@pytest.mark.asyncio
async def test_tools_list_schema_mismatch_degrades_without_calling_remote_tool() -> None:
    schemas = _compatible_schemas()
    schemas["tavily_search"] = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }
    session = FakeTavilySession(schemas=schemas)
    tools = {tool.spec.name: tool for tool in build_tavily_mcp_tools(_client(session))}

    output = await tools["browser.mcp.search"].run({"query": "test"})

    assert output["provider_status"]["status"] == "schema_incompatible"
    assert output["retryable"] is False
    assert session.calls == []


@pytest.mark.asyncio
async def test_successful_empty_tools_list_reports_tool_missing_not_pending() -> None:
    session = FakeTavilySession(schemas={})
    search_tool = build_tavily_mcp_tools(_client(session))[0]

    output = await search_tool.run({"query": "test"})

    assert output["provider_status"]["status"] == "tool_missing"
    assert output["provider_status"]["metadata"]["discovery_status"] == "complete"
    assert output["retryable"] is False


@pytest.mark.asyncio
async def test_tool_executor_retries_transient_tavily_error_then_succeeds() -> None:
    error = {
        "structuredContent": {"error": "Search failed", "detail": "429 rate limited"},
        "content": [],
        "isError": False,
    }
    success = _success_payload("tavily_search")
    session = FakeTavilySession(responses={"tavily_search": [error, success]})
    search_tool = build_tavily_mcp_tools(_client(session))[0]
    registry = ToolRegistry()
    registry.register(
        search_tool.spec,
        search_tool.run,
        search_tool.availability,
        input_model=BrowserMcpSearchInput,
    )

    async def no_sleep(seconds):
        return None

    result = await ToolExecutor(registry, sleep=no_sleep, jitter=lambda: 0).run(
        ToolCallRequest(tool_name="browser.mcp.search", arguments={"query": "student guide"})
    )

    assert result.success is True
    assert result.degraded is False
    assert result.attempts == 2
    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_legacy_search_extract_alias_routes_to_new_tools() -> None:
    session = FakeTavilySession()
    tools = {tool.spec.name: tool for tool in build_tavily_mcp_tools(_client(session))}

    search = await tools["browser.mcp.search_extract"].run({"task": "student attractions"})
    extract = await tools["browser.mcp.search_extract"].run(
        {"task": "read policy", "url": "https://example.com/policy"}
    )

    assert search["deprecated"] is True
    assert extract["deprecated"] is True
    assert [name for name, _ in session.calls] == ["tavily_search", "tavily_extract"]


def test_tavily_url_inputs_reject_private_and_credentialed_targets() -> None:
    with pytest.raises(ValidationError):
        BrowserMcpExtractInput(urls=["http://127.0.0.1/private"])
    with pytest.raises(ValidationError):
        BrowserMcpMapInput(url="http://user:password@example.com")
    with pytest.raises(ValidationError):
        BrowserMcpMapInput(url="http://169.254.169.254/latest/meta-data")
    with pytest.raises(ValidationError):
        BrowserMcpSearchInput(query="test", max_results=4)


@pytest.mark.asyncio
async def test_tavily_error_redacts_api_key() -> None:
    @asynccontextmanager
    async def failing_factory(timeout_seconds):
        raise RuntimeError("authorization failed for tvly-secret")
        yield

    client = TavilyMcpClient(_settings(), session_factory=failing_factory)
    search_tool = build_tavily_mcp_tools(client)[0]

    output = await search_tool.run({"query": "test"})

    assert "tvly-secret" not in output["recoverable_error"]
    assert "[REDACTED]" in output["recoverable_error"]


def test_mcp_logging_omits_page_content_but_keeps_metrics() -> None:
    logged = _logged_output(
        "browser.mcp.extract",
        {
            "provider": "tavily",
            "remote_tool": "tavily_extract",
            "results": [{"url": "https://example.com", "text": "sensitive page body"}],
        },
    )

    assert logged["result_count"] == 1
    assert logged["content_omitted_from_log"] is True
    assert "sensitive page body" not in str(logged)


@pytest.mark.asyncio
async def test_travel_plan_consumes_tavily_web_evidence_without_replacing_route_tools() -> None:
    provider_status = {
        "name": "browser.mcp.search",
        "capability": "browser_web_search",
        "available": True,
        "status": "available",
        "permission_level": "SEARCH",
    }
    result = ToolCallResult(
        tool_name="browser.mcp.search",
        success=True,
        output={
            "provider_status": provider_status,
            "results": [
                {
                    "title": "Manchester student guide",
                    "url": "https://example.com/manchester-guide",
                    "text": "Student-friendly museum and walking recommendations.",
                }
            ],
        },
    )

    plan = await TravelAgentService().plan_async(
        TravelPlanRequest(user_id="u1", origin="London", destination="Manchester"),
        tool_results=[result],
    )

    assert any(source.tool_name == "browser.mcp.search" for source in plan.information_sources)
    assert any(status.name == "browser.mcp.search" for status in plan.tool_statuses)
    assert all(route.provider_name != "tavily" for route in plan.route_suggestions)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_TAVILY_MCP_INTEGRATION") != "1" or not os.getenv("TAVILY_API_KEY"),
    reason="Set RUN_TAVILY_MCP_INTEGRATION=1 and TAVILY_API_KEY for live Tavily MCP tests.",
)
async def test_live_tavily_mcp_all_four_tools(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_MCP_ENABLED", "true")
    tools = {tool.spec.name: tool for tool in build_tavily_mcp_tools()}

    search = await tools["browser.mcp.search"].run(
        {"query": "Tavily MCP documentation", "max_results": 5}
    )
    extract = await tools["browser.mcp.extract"].run(
        {"urls": ["https://docs.tavily.com"], "extraction_goal": "Tavily documentation"}
    )
    mapped = await tools["browser.mcp.map"].run(
        {"url": "https://docs.tavily.com", "limit": 2, "max_breadth": 2}
    )
    crawled = await tools["browser.mcp.crawl"].run(
        {
            "url": "https://docs.tavily.com",
            "limit": 2,
            "max_breadth": 2,
            "instructions": "Return MCP documentation pages only",
        }
    )

    for output in (search, extract, mapped, crawled):
        assert output["provider_status"]["available"] is True
        assert output["recoverable_error"] is None
    assert search["results"]
    assert extract["results"]
    assert mapped["urls"]
    assert crawled["pages"]
