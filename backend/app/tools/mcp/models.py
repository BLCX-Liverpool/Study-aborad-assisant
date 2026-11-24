from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


TAVILY_ENDPOINT_DEFAULT = "https://mcp.tavily.com/mcp/"
TAVILY_REMOTE_TOOLS = {
    "browser.mcp.search": "tavily_search",
    "browser.mcp.extract": "tavily_extract",
    "browser.mcp.map": "tavily_map",
    "browser.mcp.crawl": "tavily_crawl",
}

EXPECTED_REMOTE_SCHEMAS: dict[str, dict[str, set[str]]] = {
    "tavily_search": {
        "required": {"query"},
        "properties": {
            "query",
            "search_depth",
            "topic",
            "max_results",
            "include_domains",
            "exclude_domains",
            "country",
        },
    },
    "tavily_extract": {
        "required": {"urls"},
        "properties": {"urls", "extract_depth", "include_images", "format", "query"},
    },
    "tavily_map": {
        "required": {"url"},
        "properties": {
            "url",
            "max_depth",
            "max_breadth",
            "limit",
            "instructions",
            "select_paths",
            "select_domains",
            "allow_external",
        },
    },
    "tavily_crawl": {
        "required": {"url"},
        "properties": {
            "url",
            "max_depth",
            "max_breadth",
            "limit",
            "instructions",
            "select_paths",
            "select_domains",
            "allow_external",
            "extract_depth",
            "format",
        },
    },
}


@dataclass(frozen=True, slots=True)
class TavilyMcpSettings:
    enabled: bool
    endpoint: str
    api_key: str
    tool_cache_ttl_seconds: int
    max_sse_event_size: int

    @classmethod
    def from_env(cls) -> "TavilyMcpSettings":
        return cls(
            enabled=os.getenv("TAVILY_MCP_ENABLED", "").lower() in {"1", "true", "yes"},
            endpoint=os.getenv("TAVILY_MCP_ENDPOINT") or TAVILY_ENDPOINT_DEFAULT,
            api_key=os.getenv("TAVILY_API_KEY") or "",
            tool_cache_ttl_seconds=max(int(os.getenv("TAVILY_MCP_TOOL_CACHE_TTL_SECONDS") or "300"), 1),
            max_sse_event_size=max(int(os.getenv("TAVILY_MCP_MAX_SSE_EVENT_SIZE") or str(1024 * 1024)), 1024),
        )


@dataclass(slots=True)
class DiscoveredTool:
    name: str
    description: str | None
    input_schema: dict[str, Any]
    schema_hash: str
    compatible: bool
    incompatibility: str | None = None


@dataclass(slots=True)
class TavilyCallResult:
    remote_tool: str
    raw_result: dict[str, Any]
    schema_hash: str | None
