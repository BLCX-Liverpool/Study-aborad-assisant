from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import StreamableHTTPTransport, create_mcp_http_client

from app.tools.mcp.models import (
    EXPECTED_REMOTE_SCHEMAS,
    DiscoveredTool,
    TavilyCallResult,
    TavilyMcpSettings,
)


SessionFactory = Callable[[float], Any]


class TavilyMcpError(RuntimeError):
    retryable = False


class TavilyMcpUnavailableError(TavilyMcpError):
    pass


class TavilyMcpSchemaError(TavilyMcpError):
    pass


class TavilyMcpRemoteError(TavilyMcpError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


class TavilyMcpClient:
    """A narrowly scoped Streamable HTTP MCP client for approved Tavily tools."""

    def __init__(
        self,
        settings: TavilyMcpSettings | None = None,
        *,
        session_factory: SessionFactory | None = None,
    ) -> None:
        self.settings = settings or TavilyMcpSettings.from_env()
        self._session_factory = session_factory or self._sdk_session
        self._tools: dict[str, DiscoveredTool] = {}
        self._tools_expires_at: datetime | None = None
        self._discovery_completed = False
        self._discovery_lock = asyncio.Lock()
        self._last_error: str | None = None
        self._server_metadata: dict[str, Any] = {}

    def configuration_error(self) -> str | None:
        if not self.settings.enabled:
            return "Tavily MCP is not enabled."
        if not self.settings.api_key:
            return "TAVILY_API_KEY is not configured."
        if not self.settings.endpoint.startswith("https://"):
            return "TAVILY_MCP_ENDPOINT must be an absolute HTTPS URL."
        return None

    def discovered_tool(self, remote_tool: str) -> DiscoveredTool | None:
        return self._tools.get(remote_tool)

    @property
    def discovery_status(self) -> str:
        if self._last_error:
            return "failed"
        if self._discovery_completed:
            return "complete"
        return "pending"

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def server_metadata(self) -> dict[str, Any]:
        return dict(self._server_metadata)

    async def discover_tools(self, *, force: bool = False, timeout_seconds: float = 30.0) -> dict[str, DiscoveredTool]:
        self._ensure_configured()
        if not force and self._cache_valid():
            return dict(self._tools)
        async with self._discovery_lock:
            if not force and self._cache_valid():
                return dict(self._tools)
            try:
                async with self._session_factory(timeout_seconds) as session:
                    tools = await _list_all_tools(session)
                discovered = {tool.name: _discovered_tool(tool) for tool in tools}
                self._tools = discovered
                self._discovery_completed = True
                self._tools_expires_at = datetime.now(UTC) + timedelta(
                    seconds=self.settings.tool_cache_ttl_seconds
                )
                self._last_error = None
                return dict(discovered)
            except Exception as exc:
                self._last_error = _redacted_error(exc, self.settings.api_key)
                raise

    async def call_tool(
        self,
        remote_tool: str,
        arguments: dict[str, Any],
        *,
        timeout_seconds: float,
    ) -> TavilyCallResult:
        self._ensure_configured()
        try:
            async with self._session_factory(timeout_seconds) as session:
                if not self._cache_valid():
                    tools = await _list_all_tools(session)
                    self._tools = {tool.name: _discovered_tool(tool) for tool in tools}
                    self._discovery_completed = True
                    self._tools_expires_at = datetime.now(UTC) + timedelta(
                        seconds=self.settings.tool_cache_ttl_seconds
                    )
                discovered = self._tools.get(remote_tool)
                _require_compatible_tool(remote_tool, discovered)
                result = await session.call_tool(
                    remote_tool,
                    arguments=arguments,
                    read_timeout_seconds=timedelta(seconds=timeout_seconds),
                )
            raw_result = result.model_dump(mode="json", by_alias=True, exclude_none=True)
            error = _tool_result_error(raw_result)
            if error:
                raise TavilyMcpRemoteError(error, retryable=_retryable_text(error))
            self._last_error = None
            return TavilyCallResult(
                remote_tool=remote_tool,
                raw_result=raw_result,
                schema_hash=discovered.schema_hash if discovered else None,
            )
        except TavilyMcpError:
            raise
        except Exception as exc:
            message = _redacted_error(exc, self.settings.api_key)
            self._last_error = message
            raise TavilyMcpRemoteError(
                message,
                retryable=_retryable_exception(exc),
                retry_after_seconds=_retry_after_seconds(exc),
            ) from exc

    @asynccontextmanager
    async def _sdk_session(self, timeout_seconds: float) -> AsyncIterator[ClientSession]:
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "User-Agent": "study-abroad-assistant/0.1.0",
        }
        async with _bounded_streamable_http_client(
            self.settings.endpoint,
            headers=headers,
            timeout_seconds=timeout_seconds,
            max_event_size=self.settings.max_sse_event_size,
        ) as (read_stream, write_stream):
            async with ClientSession(
                read_stream,
                write_stream,
                read_timeout_seconds=timedelta(seconds=timeout_seconds),
            ) as session:
                initialized = await session.initialize()
                self._server_metadata = {
                    "protocol_version": initialized.protocol_version,
                    "server_info": initialized.server_info.model_dump(mode="json"),
                }
                yield session

    def _ensure_configured(self) -> None:
        error = self.configuration_error()
        if error:
            raise TavilyMcpUnavailableError(error)

    def _cache_valid(self) -> bool:
        return bool(
            self._tools
            and self._tools_expires_at is not None
            and self._tools_expires_at > datetime.now(UTC)
        )


async def _list_all_tools(session: ClientSession) -> list[Any]:
    tools: list[Any] = []
    cursor: str | None = None
    while True:
        page = await session.list_tools(cursor=cursor)
        tools.extend(page.tools)
        cursor = page.next_cursor
        if not cursor:
            return tools


def _discovered_tool(tool: Any) -> DiscoveredTool:
    schema = dict(tool.input_schema or {})
    serialized = json.dumps(schema, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    compatible, incompatibility = _schema_compatibility(tool.name, schema)
    return DiscoveredTool(
        name=tool.name,
        description=tool.description,
        input_schema=schema,
        schema_hash=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        compatible=compatible,
        incompatibility=incompatibility,
    )


def _schema_compatibility(remote_tool: str, schema: dict[str, Any]) -> tuple[bool, str | None]:
    expected = EXPECTED_REMOTE_SCHEMAS.get(remote_tool)
    if expected is None:
        return False, "Remote tool is not approved by the Tavily MCP contract."
    properties = set((schema.get("properties") or {}).keys())
    required = set(schema.get("required") or [])
    missing_properties = expected["properties"] - properties
    missing_required = expected["required"] - required
    if missing_properties:
        return False, f"Missing expected properties: {sorted(missing_properties)}"
    if missing_required:
        return False, f"Missing expected required fields: {sorted(missing_required)}"
    return True, None


def _require_compatible_tool(remote_tool: str, discovered: DiscoveredTool | None) -> None:
    if discovered is None:
        raise TavilyMcpUnavailableError(f"Tavily MCP tool {remote_tool} was not returned by tools/list.")
    if not discovered.compatible:
        raise TavilyMcpSchemaError(
            f"Tavily MCP tool {remote_tool} has an incompatible schema: {discovered.incompatibility}"
        )


def _tool_result_error(raw_result: dict[str, Any]) -> str | None:
    if raw_result.get("isError"):
        return _content_error(raw_result) or "Tavily MCP returned isError=true."
    structured = raw_result.get("structuredContent")
    if isinstance(structured, dict) and structured.get("error"):
        detail = structured.get("detail") or structured.get("message")
        return f"{structured['error']}: {detail}" if detail else str(structured["error"])
    content_error = _content_error(raw_result)
    if content_error and any(
        marker in content_error.lower()
        for marker in ("tavily api error:", "invalid api key", "usage limit exceeded")
    ):
        return content_error
    return None


def _content_error(raw_result: dict[str, Any]) -> str | None:
    texts = []
    for item in raw_result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text" and item.get("text"):
            texts.append(str(item["text"]))
    return " ".join(texts) or None


def _retryable_exception(exc: Exception) -> bool:
    if isinstance(exc, BaseExceptionGroup):
        return any(_retryable_exception(item) for item in exc.exceptions if isinstance(item, Exception))
    if isinstance(exc, (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 429} or exc.response.status_code >= 500
    return _retryable_text(str(exc))


def _retryable_text(message: str) -> bool:
    lowered = message.lower()
    if any(token in lowered for token in ("401", "403", "unauthorized", "forbidden", "schema", "invalid api")):
        return False
    return any(
        token in lowered
        for token in (
            "408",
            "429",
            "timed out",
            "timeout",
            "connection",
            "temporarily",
            "server error",
            "usage limit exceeded",
            "rate limit",
            "500",
            "502",
            "503",
            "504",
        )
    )


def _retry_after_seconds(exc: Exception) -> float | None:
    if isinstance(exc, BaseExceptionGroup):
        for item in exc.exceptions:
            if isinstance(item, Exception):
                value = _retry_after_seconds(item)
                if value is not None:
                    return value
        return None
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        value = exc.response.headers.get("Retry-After")
        if value:
            try:
                return max(float(value), 0.0)
            except ValueError:
                return None
    return None


def _redacted_error(exc: BaseException, api_key: str) -> str:
    message = f"{type(exc).__name__}: {exc}"
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message[:4000]


class _BoundedStreamableHTTPTransport(StreamableHTTPTransport):
    def __init__(self, *args, max_event_size: int, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.max_event_size = max_event_size

    async def _handle_sse_event(self, sse, read_stream_writer, *args, **kwargs):
        if len(str(sse.data).encode("utf-8")) > self.max_event_size:
            await read_stream_writer.send(
                ValueError(f"MCP SSE event exceeds {self.max_event_size} bytes.")
            )
            return True
        return await super()._handle_sse_event(sse, read_stream_writer, *args, **kwargs)

    async def _handle_json_response(self, response, read_stream_writer, *args, **kwargs):
        content = await response.aread()
        if len(content) > self.max_event_size:
            await read_stream_writer.send(
                ValueError(f"MCP JSON response exceeds {self.max_event_size} bytes.")
            )
            return None
        return await super()._handle_json_response(response, read_stream_writer, *args, **kwargs)


@asynccontextmanager
async def _bounded_streamable_http_client(
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    max_event_size: int,
):
    transport = _BoundedStreamableHTTPTransport(
        url,
        headers=headers,
        timeout=timeout_seconds,
        sse_read_timeout=timeout_seconds,
        max_event_size=max_event_size,
    )
    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async with anyio.create_task_group() as task_group:
        try:
            async with create_mcp_http_client(
                headers=transport.request_headers,
                timeout=httpx.Timeout(transport.timeout, read=transport.sse_read_timeout),
                auth=transport.auth,
            ) as http_client:
                def start_get_stream() -> None:
                    task_group.start_soon(transport.handle_get_stream, http_client, read_stream_writer)

                task_group.start_soon(
                    transport.post_writer,
                    http_client,
                    write_stream_reader,
                    read_stream_writer,
                    write_stream,
                    start_get_stream,
                    task_group,
                )
                try:
                    yield read_stream, write_stream
                finally:
                    if transport.session_id:
                        await transport.terminate_session(http_client)
                    task_group.cancel_scope.cancel()
        finally:
            await read_stream_writer.aclose()
            await write_stream.aclose()
