"""Gateway tests against in-process mock backends (both dialects, stream + non-stream)."""
import gzip
import json

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from euthyna.gateway import GatewayConfig, Profile, create_app

NONSTREAM_BODY = json.dumps({
    "id": "cmpl-1", "model": "test-model",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 10,
              "prompt_tokens_details": {"cached_tokens": 80}},
}).encode()


def sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"


async def openai_chat(request):
    body = await request.json()
    request.app["seen"].append({"headers": dict(request.headers), "body": body})
    if request.headers.get("X-Test-Gzip"):
        return web.Response(body=gzip.compress(NONSTREAM_BODY),
                            content_type="application/json",
                            headers={"Content-Encoding": "gzip"})
    if body.get("stream"):
        events = [{"model": "test-model", "choices": [{"delta": {"content": "hi"}}]}]
        if (body.get("stream_options") or {}).get("include_usage"):
            events.append({"model": "test-model", "choices": [],
                           "usage": {"prompt_tokens": 100, "completion_tokens": 10,
                                     "prompt_tokens_details": {"cached_tokens": 80}}})
        return web.Response(text=sse(*events), content_type="text/event-stream")
    return web.Response(body=NONSTREAM_BODY, content_type="application/json")


async def anthropic_messages(request):
    body = await request.json()
    request.app["seen"].append({"headers": dict(request.headers), "body": body})
    events = [
        {"type": "message_start", "message": {"model": "claude-test",
         "usage": {"input_tokens": 50, "cache_read_input_tokens": 40,
                   "cache_creation_input_tokens": 10}}},
        {"type": "message_delta", "usage": {"output_tokens": 7}},
    ]
    return web.Response(text=sse(*events), content_type="text/event-stream")


async def openai_completions(request):
    body = await request.json()
    request.app["seen"].append({"headers": dict(request.headers), "body": body})
    return web.json_response({"model": "test-model", "choices": [{"text": "ok"}],
                              "usage": {"prompt_tokens": 5, "completion_tokens": 1}})


async def models_list(request):
    return web.json_response({"data": [{"id": "test-model"}]})


@pytest.fixture
async def backend():
    app = web.Application()
    app["seen"] = []
    app.router.add_post("/v1/chat/completions", openai_chat)
    app.router.add_post("/v1/completions", openai_completions)
    app.router.add_post("/v1/messages", anthropic_messages)
    app.router.add_get("/v1/models", models_list)
    server = TestServer(app)
    await server.start_server()
    yield server
    await server.close()


def make_config(backend, tmp_path, **kwargs):
    base = f"http://127.0.0.1:{backend.port}"
    profile = Profile(
        name="test", dialect="openai", base_url=base,
        accountant_model="local/test", price_date="2026-07-21",
        raw={"cache_schema": {"cached_tokens": {
                 "surfaces": True, "path": ["prompt_tokens_details", "cached_tokens"]}},
             "prices_per_1m": {"input": 0.0, "cached_input": 0.0, "output": 0.0}},
    )
    anthropic = Profile(
        name="test-anthropic", dialect="anthropic", base_url=base,
        accountant_model="anthropic/claude-cache", price_date="2026-07-15",
    )
    return GatewayConfig(profile=profile, anthropic_profile=anthropic,
                         home=tmp_path / "euthyna-home", **kwargs)


@pytest.fixture
async def gateway(backend, tmp_path, registries):
    config = make_config(backend, tmp_path)
    client = TestClient(TestServer(create_app(config)))
    await client.start_server()
    yield client, config, backend.app["seen"]
    await client.close()


def ledger_rows(config):
    rows = []
    if config.ledger_dir.exists():
        for f in sorted(config.ledger_dir.glob("*.jsonl")):
            rows += [json.loads(line) for line in f.read_text().splitlines()]
    return rows


async def test_nonstream_passthrough_byte_faithful_and_ledger(gateway):
    client, config, _ = gateway
    resp = await client.post("/v1/chat/completions", json={
        "model": "test-model", "messages": [{"role": "user", "content": "hello"}]})
    assert resp.status == 200
    assert await resp.read() == NONSTREAM_BODY  # body bytes untouched

    (row,) = ledger_rows(config)
    assert row["usage"]["prompt_tokens"] == 100
    assert row["gateway_injected"] is False
    assert row["cost"]["native_tokens"]["cached_tokens"] == 80
    assert row["cost"]["observed_flags"]["cached_tokens"] is True
    assert row["cost"]["list_cost_usd"] == 0.0  # local backend prices are $0
    assert row["cost_error"] is None


async def test_stream_injects_usage_and_flags(gateway):
    client, config, seen = gateway
    resp = await client.post("/v1/chat/completions", json={
        "model": "test-model", "stream": True,
        "messages": [{"role": "user", "content": "hello"}]})
    text = (await resp.read()).decode()
    assert text.rstrip().endswith("data: [DONE]")
    assert seen[-1]["body"]["stream_options"] == {"include_usage": True}

    (row,) = ledger_rows(config)
    assert row["gateway_injected"] is True
    assert row["request_sha_before"] != row["request_sha_after"]
    assert row["usage"]["completion_tokens"] == 10


async def test_stream_no_injection_when_client_asked(gateway):
    client, config, seen = gateway
    await client.post("/v1/chat/completions", json={
        "model": "test-model", "stream": True, "stream_options": {"include_usage": True},
        "messages": [{"role": "user", "content": "hello"}]})
    assert ledger_rows(config)[0]["gateway_injected"] is False


async def test_anthropic_stream_usage_normalized(gateway):
    client, config, _ = gateway
    await client.post("/v1/messages", json={
        "model": "claude-test", "stream": True,
        "messages": [{"role": "user", "content": "hello"}]})
    (row,) = ledger_rows(config)
    assert row["usage"] == {"input_tokens": 50, "cache_read_input_tokens": 40,
                            "cache_creation_input_tokens": 10, "output_tokens": 7}
    native = row["cost"]["native_tokens"]
    assert native["prompt_tokens"] == 100  # 50 + 40 + 10 (OpenAI convention includes cache)
    assert native["cached_tokens"] == 40
    assert native["cache_creation_tokens"] == 10
    assert row["cost"]["observed_flags"]["cached_tokens"] is True
    # end-to-end dollar check at claude-cache list prices: creation billed exactly once
    # (50 uncached * 3.00 + 40 cached * 0.30 + 10 creation * 3.75 + 7 out * 15.00) / 1M
    assert abs(row["cost"]["list_cost_usd"] - 0.0003045) < 1e-9


async def test_transparent_mode_pure_pipe(backend, tmp_path, registries):
    config = make_config(backend, tmp_path, transparent=True)
    client = TestClient(TestServer(create_app(config)))
    await client.start_server()
    try:
        await client.post("/v1/chat/completions", json={
            "model": "test-model", "stream": True,
            "messages": [{"role": "user", "content": "hello"}]})
        assert "stream_options" not in backend.app["seen"][-1]["body"]  # no mutation
        assert not config.ledger_dir.exists()  # no observation
    finally:
        await client.close()


async def test_tap_crash_is_fail_open(gateway, monkeypatch):
    client, config, _ = gateway
    from euthyna.gateway.taps import Taps
    monkeypatch.setattr(Taps, "observe", lambda self, **kw: 1 / 0)
    resp = await client.post("/v1/chat/completions", json={
        "model": "test-model", "messages": [{"role": "user", "content": "hello"}]})
    assert resp.status == 200
    assert await resp.read() == NONSTREAM_BODY


async def test_prefix_monitor_chains_sessions(gateway):
    client, config, _ = gateway
    first = [{"role": "system", "content": "sys"}, {"role": "user", "content": "q1"}]
    grown = first + [{"role": "assistant", "content": "a1"}, {"role": "user", "content": "q2"}]
    await client.post("/v1/chat/completions", json={"model": "m", "messages": first})
    await client.post("/v1/chat/completions", json={"model": "m", "messages": grown})
    row1, row2 = ledger_rows(config)
    assert row1["session"] == row2["session"]  # chained without any header
    assert row1["prefix_stable_ratio"] is None
    assert row2["prefix_stable_ratio"] == 1.0


async def test_session_header_wins(gateway):
    client, config, _ = gateway
    await client.post("/v1/chat/completions",
                      json={"model": "m", "messages": [{"role": "user", "content": "x"}]},
                      headers={"X-Euthyna-Session": "sess-A"})
    assert ledger_rows(config)[0]["session"] == "sess-A"


async def test_unknown_model_records_usage_without_cost(backend, tmp_path, registries):
    config = make_config(backend, tmp_path)
    config.profile.accountant_model = None  # no registration → no cost basis
    client = TestClient(TestServer(create_app(config)))
    await client.start_server()
    try:
        await client.post("/v1/chat/completions", json={
            "model": "test-model", "messages": [{"role": "user", "content": "x"}]})
        (row,) = ledger_rows(config)
        assert row["usage"]["prompt_tokens"] == 100  # usage recorded regardless
        assert row["cost"] is None
        assert row["cost_error"]  # reason on record, nothing fabricated
    finally:
        await client.close()


async def test_auth_headers_pass_through(gateway):
    client, _, seen = gateway
    await client.post("/v1/chat/completions",
                      json={"model": "m", "messages": []},
                      headers={"Authorization": "Bearer sk-test",
                               "anthropic-beta": "oauth-2025"})
    headers = seen[-1]["headers"]
    assert headers["Authorization"] == "Bearer sk-test"
    assert headers["anthropic-beta"] == "oauth-2025"


async def test_untapped_get_passthrough(gateway):
    client, config, _ = gateway
    resp = await client.get("/v1/models")
    assert resp.status == 200
    assert (await resp.json())["data"][0]["id"] == "test-model"
    assert ledger_rows(config) == []  # not a tapped path


async def test_gzip_relayed_verbatim_and_tap_decompresses(backend, tmp_path, registries):
    config = make_config(backend, tmp_path)
    client = TestClient(TestServer(create_app(config)), auto_decompress=False)
    await client.start_server()
    try:
        resp = await client.post("/v1/chat/completions",
                                 json={"model": "test-model",
                                       "messages": [{"role": "user", "content": "x"}]},
                                 headers={"X-Test-Gzip": "1"})
        raw = await resp.read()
        assert resp.headers.get("Content-Encoding") == "gzip"
        assert raw == gzip.compress(NONSTREAM_BODY)  # bytes exactly as backend sent
        (row,) = ledger_rows(config)
        assert row["usage"]["prompt_tokens"] == 100  # tap parsed its own decompressed copy
    finally:
        await client.close()


async def test_completions_calls_do_not_poison_sessions(gateway):
    client, config, _ = gateway
    await client.post("/v1/completions", json={"model": "m", "prompt": "hello"})
    await client.post("/v1/chat/completions", json={
        "model": "m", "messages": [{"role": "user", "content": "unrelated"}]})
    row1, row2 = ledger_rows(config)
    assert row1["usage"]["prompt_tokens"] == 5  # completions call still ledgered
    assert row1["session"] != row2["session"]  # no chaining onto an empty canonical
    assert row2["prefix_stable_ratio"] is None  # first call of its own session


async def test_completions_distinct_prompts_get_distinct_sessions(gateway):
    client, config, _ = gateway
    await client.post("/v1/completions", json={"model": "m", "prompt": "alpha"})
    await client.post("/v1/completions", json={"model": "m", "prompt": "beta"})
    row1, row2 = ledger_rows(config)
    assert row1["session"] != row2["session"]  # no collapse onto hash of '[]'


async def test_session_header_sanitized_for_filenames(gateway):
    client, config, _ = gateway
    await client.post("/v1/chat/completions",
                      json={"model": "m", "messages": [{"role": "user", "content": "x"}]},
                      headers={"X-Euthyna-Session": "../../../evil"})
    (row,) = ledger_rows(config)
    assert row["session"].startswith("hdr-")
    traces = list(config.traces_dir.glob("*.jsonl"))
    assert [t.name for t in traces] == [row["session"] + ".jsonl"]  # inside traces dir


async def test_oversized_response_still_ledgered(gateway, monkeypatch):
    import euthyna.gateway.app as app_module
    monkeypatch.setattr(app_module, "TAP_BUFFER_CAP", 10)
    client, config, _ = gateway
    resp = await client.post("/v1/chat/completions", json={
        "model": "test-model", "messages": [{"role": "user", "content": "hello"}]})
    assert await resp.read() == NONSTREAM_BODY  # pipe unaffected
    (row,) = ledger_rows(config)
    assert row["tap_truncated"] is True
    assert row["usage"] is None  # unknown, not fabricated
    assert row["status"] == 200


async def test_healthz_and_stats(gateway):
    client, config, _ = gateway
    assert (await (await client.get("/healthz")).json())["ok"] is True
    await client.post("/v1/chat/completions", json={
        "model": "test-model", "messages": [{"role": "user", "content": "hello"}]})
    stats = await (await client.get("/euthyna/stats")).json()
    assert stats["calls"] == 1
    assert stats["prompt_tokens"] == 100
    assert stats["sessions"] == 1
