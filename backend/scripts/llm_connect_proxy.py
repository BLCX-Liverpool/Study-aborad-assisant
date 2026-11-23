"""Allowlisted host CONNECT proxy for Docker Desktop development.

Run this process on the host when macOS can reach DashScope but Docker's VM
cannot complete the TLS handshake. Point ``LLM_PROXY_URL`` at
``http://host.docker.internal:18080``.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress


LISTEN_HOST = os.getenv("LLM_CONNECT_PROXY_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("LLM_CONNECT_PROXY_PORT", "18080"))
ALLOWED_HOSTS = {
    host.strip().lower()
    for host in os.getenv("LLM_CONNECT_PROXY_ALLOWED_HOSTS", "dashscope.aliyuncs.com").split(",")
    if host.strip()
}
MAX_HEADER_BYTES = 16_384


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65_536):
            writer.write(chunk)
            await writer.drain()
    except (ConnectionError, asyncio.CancelledError):
        pass
    finally:
        with suppress(Exception):
            writer.close()
            await writer.wait_closed()


async def _read_headers(reader: asyncio.StreamReader) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = await reader.read(1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_HEADER_BYTES:
            raise ValueError("Proxy request headers are too large")
    return bytes(data)


async def _handle(client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
    peer = client_writer.get_extra_info("peername")
    try:
        headers = await _read_headers(client_reader)
        first_line = headers.split(b"\r\n", 1)[0].decode("ascii", errors="replace")
        parts = first_line.split()
        if len(parts) != 3 or parts[0].upper() != "CONNECT":
            client_writer.write(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            return

        host, separator, port_text = parts[1].rpartition(":")
        if not separator or not port_text.isdigit():
            raise ValueError("CONNECT authority must be host:port")
        normalized_host = host.strip("[]").lower()
        port = int(port_text)
        if normalized_host not in ALLOWED_HOSTS or port != 443:
            client_writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            return

        upstream_reader, upstream_writer = await asyncio.open_connection(normalized_host, port)
        client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await client_writer.drain()
        await asyncio.gather(
            _pipe(client_reader, upstream_writer),
            _pipe(upstream_reader, client_writer),
        )
    except Exception as exc:
        print(f"CONNECT proxy error from {peer}: {type(exc).__name__}: {exc}", flush=True)
        with suppress(Exception):
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
    finally:
        with suppress(Exception):
            client_writer.close()
            await client_writer.wait_closed()


async def main() -> None:
    server = await asyncio.start_server(_handle, LISTEN_HOST, LISTEN_PORT)
    addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"DashScope CONNECT proxy listening on {addresses}; allowlist={sorted(ALLOWED_HOSTS)}", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
