"""The Euthyna gateway: a bump-in-the-wire proxy for OpenAI/Anthropic dialects.

One asyncio process, one port (default 4517). Byte-faithful passthrough — SSE is
relayed as received, auth headers (including anthropic-beta) pass untouched. All
observation is fail-open. The single sanctioned request mutation is injecting
``stream_options.include_usage`` on streaming OpenAI calls, always flagged in the
ledger with before/after hashes. EUTHYNA_TRANSPARENT=1 turns the gateway into a
pure pipe (no taps, no mutation).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
import zlib
from typing import Optional

from aiohttp import ClientSession, ClientTimeout, web

from euthyna import ledger
from euthyna.version import __version__

from .config import GatewayConfig
from .taps import SESSION_HEADER, Taps

# Paths whose request/response we parse for observation. Everything else under
# /v1/* is proxied verbatim without inspection.
TAPPED = {
    "/v1/chat/completions": "openai",
    "/v1/completions": "openai",
    "/v1/messages": "anthropic",
}
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}
TAP_BUFFER_CAP = 8 * 1024 * 1024  # stop buffering (not proxying) past this size

CONFIG_KEY = web.AppKey("euthyna_config", GatewayConfig)
TAPS_KEY = web.AppKey("euthyna_taps", Taps)
CLIENT_KEY = web.AppKey("euthyna_client", ClientSession)


def _filter_headers(headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_BY_HOP}


def _decompress(raw: bytes, encoding: Optional[str]) -> bytes:
    """Best-effort decode for tap parsing only; the client always gets raw bytes."""
    if encoding == "gzip":
        return gzip.decompress(raw)
    if encoding == "deflate":
        return zlib.decompress(raw)
    return raw


def _maybe_inject_usage(body: bytes) -> tuple[bytes, bool, Optional[tuple[str, str]]]:
    """Add stream_options.include_usage to a streaming OpenAI request if absent."""
    try:
        data = json.loads(body)
        if not (isinstance(data, dict) and data.get("stream")):
            return body, False, None
        opts = data.get("stream_options") or {}
        if opts.get("include_usage"):
            return body, False, None
        data["stream_options"] = {**opts, "include_usage": True}
        new = json.dumps(data, ensure_ascii=False).encode()
        digest = (hashlib.sha256(body).hexdigest(), hashlib.sha256(new).hexdigest())
        return new, True, digest
    except Exception:
        return body, False, None


async def proxy(request: web.Request) -> web.StreamResponse:
    config = request.app[CONFIG_KEY]
    taps = request.app[TAPS_KEY]
    session = request.app[CLIENT_KEY]

    dialect = TAPPED.get(request.path)
    profile = config.profile_for(dialect or "openai")
    if profile is None:
        return web.json_response({"error": "euthyna: no backend profile configured"}, status=502)

    body = await request.read()
    outbound, injected, request_sha = body, False, None
    if dialect == "openai" and not config.transparent:
        outbound, injected, request_sha = _maybe_inject_usage(body)

    started = time.monotonic()
    try:
        upstream = await session.request(
            request.method,
            profile.base_url + request.path_qs,
            data=outbound if request.method != "GET" else None,
            headers=_filter_headers(request.headers),
        )
    except Exception as exc:
        return web.json_response(
            {"error": {"type": "euthyna_upstream_unreachable", "message": str(exc),
                       "backend": profile.base_url}},
            status=502,
        )

    response = web.StreamResponse(status=upstream.status, headers=_filter_headers(upstream.headers))
    await response.prepare(request)
    chunks: list[bytes] = []
    buffered = 0
    overflow = False
    relay_error: Optional[BaseException] = None
    try:
        async for chunk in upstream.content.iter_any():
            await response.write(chunk)
            if dialect and not config.transparent and not overflow:
                chunks.append(chunk)
                buffered += len(chunk)
                if buffered > TAP_BUFFER_CAP:
                    overflow = True
                    chunks.clear()
        await response.write_eof()
        upstream.release()
    except BaseException as exc:  # client disconnect / backend death mid-stream
        relay_error = exc
        upstream.close()  # partially-read body: close, don't pool

    if dialect and not config.transparent:
        # Fail-open observation — runs even for truncated/disconnected calls so
        # every call is ledgered; usage may be unknown on those rows.
        truncated = overflow or relay_error is not None
        response_json = response_sse = None
        try:
            raw = _decompress(b"".join(chunks), upstream.headers.get("Content-Encoding"))
            if raw:
                if "text/event-stream" in upstream.headers.get("Content-Type", ""):
                    response_sse = raw.decode("utf-8", errors="replace")
                else:
                    response_json = json.loads(raw)
        except Exception:
            response_json = response_sse = None
        try:
            taps.observe(
                dialect=dialect,
                path=request.path,
                status=upstream.status,
                latency_ms=(time.monotonic() - started) * 1000,
                request_json=json.loads(body) if body else None,
                response_json=response_json,
                response_sse=response_sse,
                session_header=request.headers.get(SESSION_HEADER),
                injected=injected,
                request_sha=request_sha,
                truncated=truncated,
            )
        except Exception:
            pass

    if relay_error is not None:
        raise relay_error
    return response


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "version": __version__,
                              "transparent": request.app[CONFIG_KEY].transparent})


async def stats(request: web.Request) -> web.Response:
    """Quick aggregates over today's ledger. Heavier analysis belongs in `euthyna report`."""
    import datetime as dt

    config = request.app[CONFIG_KEY]
    sessions = ledger.aggregate(
        ledger.load_rows(dt.date.today().isoformat(), home_dir=config.home))
    totals = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
              "cached_tokens": 0, "cost_usd": 0.0}
    ratios = [s["mean_prefix_stable_ratio"] for s in sessions.values()
              if s["mean_prefix_stable_ratio"] is not None]
    for s in sessions.values():
        for key in totals:
            totals[key] += s[key]
    totals["sessions"] = len(sessions)
    totals["mean_prefix_stable_ratio"] = round(sum(ratios) / len(ratios), 4) if ratios else None
    totals["cost_usd"] = round(totals["cost_usd"], 6)
    return web.json_response(totals)


def create_app(config: GatewayConfig) -> web.Application:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app[CONFIG_KEY] = config
    app[TAPS_KEY] = Taps(config)
    config.register_profiles()

    async def _client(app_: web.Application):
        # auto_decompress=False: relay the backend's bytes exactly as sent (the tap
        # decompresses its own copy for parsing).
        app_[CLIENT_KEY] = ClientSession(
            timeout=ClientTimeout(total=None, sock_connect=10), auto_decompress=False)
        yield
        await app_[CLIENT_KEY].close()

    app.cleanup_ctx.append(_client)
    app.router.add_get("/healthz", healthz)
    app.router.add_get("/euthyna/stats", stats)
    app.router.add_route("*", "/v1/{tail:.*}", proxy)
    return app


def run(config: GatewayConfig) -> None:
    web.run_app(create_app(config), host="127.0.0.1", port=config.port,
                print=lambda *_: None)
