import asyncio
import json
import os
import shlex
from typing import Any

import httpx

from app.core.permissions import PermissionLevel
from app.tools.models import ToolAvailabilityStatus, ToolSpec


BROWSER_MCP_TOOL_NAME = "browser.mcp.search_extract"


class BrowserMcpRuntime:
    spec = ToolSpec(
        name=BROWSER_MCP_TOOL_NAME,
        description="Use a connected Browser MCP runtime to browse, inspect, and extract web content through MCP tools.",
        permission_level=PermissionLevel.SEARCH,
        capability="browser_search_extract",
        provider_name="browser_mcp",
        required_env=["BROWSER_MCP_ENABLED"],
        input_schema={
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "url": {"type": "string"},
                "extraction_goal": {"type": "string"},
                "max_results": {"type": "integer"},
                "include_screenshot": {"type": "boolean"},
            },
            "required": ["task"],
        },
    )

    def availability(self) -> ToolAvailabilityStatus:
        enabled = _browser_mcp_enabled()
        endpoint = os.getenv("BROWSER_MCP_ENDPOINT")
        command = os.getenv("BROWSER_MCP_COMMAND")
        missing = [] if enabled else ["BROWSER_MCP_ENABLED"]
        if enabled and not endpoint and not command:
            missing = ["BROWSER_MCP_ENDPOINT or BROWSER_MCP_COMMAND"]

        return ToolAvailabilityStatus(
            name=self.spec.name,
            capability=self.spec.capability or self.spec.name,
            available=not missing,
            status="available" if not missing else "unavailable",
            permission_level=self.spec.permission_level,
            required_env=self.spec.required_env,
            missing_env=missing,
            recoverable_error=_browser_recoverable_error(enabled, endpoint, command),
            metadata={
                "provider_name": self.spec.provider_name,
                "transport": _browser_transport(endpoint, command),
                "endpoint_configured": bool(endpoint),
                "command_configured": bool(command),
                "tool_name": _browser_tool_name({}),
            },
        )

    async def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        status = self.availability()
        if not status.available:
            return _browser_result(
                status=status,
                results=[],
                raw_result=None,
                recoverable_error=status.recoverable_error,
            )

        tool_name = _browser_tool_name(arguments)
        tool_arguments = _browser_tool_arguments(arguments)
        try:
            if os.getenv("BROWSER_MCP_ENDPOINT"):
                raw_result = await _call_http_mcp(tool_name, tool_arguments)
            else:
                raw_result = await _call_stdio_mcp(tool_name, tool_arguments)
        except Exception as exc:
            degraded = status.model_copy(
                update={
                    "available": False,
                    "status": "degraded",
                    "recoverable_error": f"{type(exc).__name__}: {exc}",
                }
            )
            return _browser_result(
                status=degraded,
                results=[],
                raw_result=None,
                recoverable_error=degraded.recoverable_error,
                tool_name=tool_name,
            )

        return _browser_result(
            status=status,
            results=_browser_results(raw_result),
            raw_result=raw_result,
            tool_name=tool_name,
        )


def _browser_mcp_enabled() -> bool:
    return os.getenv("BROWSER_MCP_ENABLED", "").lower() in {"1", "true", "yes"}


def _browser_transport(endpoint: str | None, command: str | None) -> str | None:
    if endpoint:
        return "http_jsonrpc"
    if command:
        return "stdio_jsonrpc"
    return None


def _browser_recoverable_error(enabled: bool, endpoint: str | None, command: str | None) -> str | None:
    if not enabled:
        return "Browser MCP runtime is not enabled."
    if not endpoint and not command:
        return "Browser MCP is enabled, but neither BROWSER_MCP_ENDPOINT nor BROWSER_MCP_COMMAND is configured."
    return None


def _browser_tool_name(arguments: dict[str, Any]) -> str:
    if arguments.get("url") and os.getenv("BROWSER_MCP_EXTRACT_TOOL"):
        return os.environ["BROWSER_MCP_EXTRACT_TOOL"]
    if not arguments.get("url") and os.getenv("BROWSER_MCP_SEARCH_TOOL"):
        return os.environ["BROWSER_MCP_SEARCH_TOOL"]
    return os.getenv("BROWSER_MCP_TOOL") or "browser.search_extract"


def _browser_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "task": str(arguments.get("task") or ""),
        "url": arguments.get("url"),
        "extraction_goal": arguments.get("extraction_goal"),
        "max_results": int(arguments.get("max_results") or 5),
        "include_screenshot": bool(arguments.get("include_screenshot", False)),
    }
    return {key: value for key, value in payload.items() if value is not None}


async def _call_http_mcp(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    endpoint = os.environ["BROWSER_MCP_ENDPOINT"]
    request = {
        "jsonrpc": "2.0",
        "id": "browser-search-extract-1",
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    async with httpx.AsyncClient(timeout=_browser_timeout(), follow_redirects=True) as client:
        response = await client.post(endpoint, json=request, headers=_browser_http_headers())
        response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(_jsonrpc_error(payload["error"]))
    return payload.get("result") or {}


async def _call_stdio_mcp(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    command = shlex.split(os.environ["BROWSER_MCP_COMMAND"])
    if not command:
        raise RuntimeError("BROWSER_MCP_COMMAND is empty.")

    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    try:
        await _stdio_send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "study-abroad-assistant", "version": "0.1.0"},
                },
            },
        )
        await _stdio_read_response(process, 1)
        await _stdio_send(process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        await _stdio_send(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        )
        response = await _stdio_read_response(process, 2)
        if response.get("error"):
            raise RuntimeError(_jsonrpc_error(response["error"]))
        return response.get("result") or {}
    finally:
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            process.kill()
            await process.wait()


async def _stdio_send(process: asyncio.subprocess.Process, message: dict[str, Any]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
    await process.stdin.drain()


async def _stdio_read_response(process: asyncio.subprocess.Process, response_id: int) -> dict[str, Any]:
    assert process.stdout is not None
    deadline = _browser_timeout()
    while True:
        line = await asyncio.wait_for(process.stdout.readline(), timeout=deadline)
        if not line:
            stderr = await _stdio_stderr(process)
            raise RuntimeError(f"Browser MCP process ended before response {response_id}. {stderr}".strip())
        payload = json.loads(line.decode("utf-8"))
        if payload.get("id") == response_id:
            return payload


async def _stdio_stderr(process: asyncio.subprocess.Process) -> str:
    if process.stderr is None:
        return ""
    try:
        raw = await asyncio.wait_for(process.stderr.read(), timeout=0.2)
    except TimeoutError:
        return ""
    return raw.decode("utf-8", errors="replace").strip()


def _browser_http_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = os.getenv("BROWSER_MCP_AUTH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _browser_timeout() -> float:
    return float(os.getenv("BROWSER_MCP_TIMEOUT_SECONDS") or "30")


def _jsonrpc_error(error: dict[str, Any]) -> str:
    message = error.get("message") or "Browser MCP JSON-RPC error."
    code = error.get("code")
    data = error.get("data")
    suffix = f" code={code}" if code is not None else ""
    if data is not None:
        suffix += f" data={data}"
    return message + suffix


def _browser_results(raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    structured = raw_result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("results", "items", "documents", "pages"):
            value = structured.get(key)
            if isinstance(value, list):
                return [_normalize_browser_item(item) for item in value]
        return [_normalize_browser_item(structured)]

    content = raw_result.get("content")
    if isinstance(content, list):
        results = []
        for index, item in enumerate(content):
            normalized = _normalize_browser_content(index, item)
            if normalized:
                results.append(normalized)
        return results
    if isinstance(raw_result.get("text"), str):
        return [{"title": "Browser MCP result", "text": raw_result["text"], "source": "browser_mcp"}]
    return []


def _normalize_browser_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"title": "Browser MCP result", "text": str(item), "source": "browser_mcp"}
    return {
        "title": item.get("title") or item.get("name") or item.get("url") or "Browser MCP result",
        "url": item.get("url") or item.get("href"),
        "text": item.get("text") or item.get("content") or item.get("snippet") or item.get("summary"),
        "metadata": {key: value for key, value in item.items() if key not in {"title", "name", "url", "href", "text", "content", "snippet", "summary"}},
        "source": "browser_mcp",
    }


def _normalize_browser_content(index: int, item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return {"title": f"Browser MCP content {index + 1}", "text": str(item), "source": "browser_mcp"}
    content_type = item.get("type")
    if content_type == "text":
        return {"title": f"Browser MCP text {index + 1}", "text": item.get("text", ""), "source": "browser_mcp"}
    if content_type == "resource":
        resource = item.get("resource") or {}
        return {
            "title": resource.get("name") or resource.get("uri") or f"Browser MCP resource {index + 1}",
            "url": resource.get("uri"),
            "text": resource.get("text"),
            "metadata": resource,
            "source": "browser_mcp",
        }
    return _normalize_browser_item(item)


def _browser_result(
    status: ToolAvailabilityStatus,
    results: list[dict[str, Any]],
    raw_result: dict[str, Any] | None,
    recoverable_error: str | None = None,
    tool_name: str | None = None,
) -> dict[str, Any]:
    return {
        "provider_status": status.model_dump(mode="json"),
        "results": results,
        "raw_result": raw_result,
        "tool_name": tool_name or _browser_tool_name({}),
        "transport": status.metadata.get("transport"),
        "source": "browser_mcp",
        "recoverable_error": recoverable_error,
        "assumptions": [
            "Browser MCP may navigate external pages and extracted content should be treated as provider data.",
            "No form submission, purchase, login, or destructive browser action is requested by this tool.",
        ],
    }
