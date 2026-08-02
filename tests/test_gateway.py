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


async def test_malformed_request_body_still_ledgered(gateway):
    client, config, _ = gateway
    resp = await client.post("/v1/chat/completions", data=b'{"model": broken',
                             headers={"Content-Type": "application/json"})
    assert resp.status >= 400  # backend rejects it; the pipe relays that honestly
    (row,) = ledger_rows(config)
    assert row["request_parse_error"] == "JSONDecodeError"
    assert row["usage"] is None  # unknown, not fabricated
    assert row["status"] >= 400


async def test_unobservable_cache_is_unavailable_not_zero(backend, tmp_path, registries):
    config = make_config(backend, tmp_path)
    config.profile.raw["cache_schema"] = {
        "cached_tokens": {"surfaces": False, "path": None}}  # vllm-metal-style backend
    client = TestClient(TestServer(create_app(config)))
    await client.start_server()
    try:
        await client.post("/v1/chat/completions", json={
            "model": "test-model", "messages": [{"role": "user", "content": "x"}]})
        (row,) = ledger_rows(config)
        assert row["cost"]["cache_status"] == "unavailable"
        assert row["cost"]["observed_flags"]["cached_tokens"] is False
        assert row["cost"]["imputed_flags"]["cached_tokens"] is False
        from euthyna.ledger import aggregate
        s = aggregate([row])[row["session"]]
        assert s["cached_tokens"] is None  # unknown never rendered as 0
        assert s["cached_fraction"] is None
        assert s["cache_unavailable_calls"] == 1
    finally:
        await client.close()


async def test_cost_quality_estimated_when_cache_priced_but_unobserved(backend, tmp_path, registries):
    config = make_config(backend, tmp_path)
    config.profile.raw["cache_schema"] = {"cached_tokens": {"surfaces": False, "path": None}}
    config.profile.raw["prices_per_1m"] = {"input": 1.25, "cached_input": 0.125, "output": 10.0}
    client = TestClient(TestServer(create_app(config)))
    await client.start_server()
    try:
        await client.post("/v1/chat/completions", json={
            "model": "test-model", "messages": [{"role": "user", "content": "x"}]})
        (row,) = ledger_rows(config)
        assert row["cost_quality"] == "estimated_under_no_cache_assumption"
    finally:
        await client.close()


async def test_prefix_mutation_priced_from_observed_tokens(gateway):
    """A tools[] change mid-session is the cache tax event nobody has measured.
    It must be recorded, attributed, and priced from the previous call's OBSERVED
    prompt tokens (1.25x write - 0.10x read = 1.15x), never from an estimate."""
    client, config, _ = gateway
    base = {"model": "test-model", "messages": [{"role": "user", "content": "x"}]}
    await client.post("/v1/chat/completions",
                      json={**base, "tools": [{"function": {"name": "read"}}]},
                      headers={"X-Euthyna-Session": "sess-mut"})
    await client.post("/v1/chat/completions",
                      json={**base, "tools": [{"function": {"name": "read"}},
                                              {"function": {"name": "grep"}}]},
                      headers={"X-Euthyna-Session": "sess-mut"})
    first, second = ledger_rows(config)
    assert first["prefix_mutation"] is None  # first call establishes the baseline
    m = second["prefix_mutation"]
    assert m["segments"] == ["tools"]
    assert m["tools_added"] == ["grep"] and m["tools_removed"] == []
    # mock backend reports prompt_tokens=100 on call one
    assert m["cost_tok_eq"] == 115.0
    assert m["cost_basis"] == "observed_prev_prompt_tokens"


async def test_unchanged_prefix_records_no_mutation(gateway):
    client, config, _ = gateway
    body = {"model": "test-model", "messages": [{"role": "user", "content": "x"}],
            "tools": [{"function": {"name": "read"}}]}
    for _ in range(2):
        await client.post("/v1/chat/completions", json=body,
                          headers={"X-Euthyna-Session": "sess-stable"})
    assert all(r["prefix_mutation"] is None for r in ledger_rows(config))


async def test_model_switch_counts_as_prefix_mutation(gateway):
    client, config, _ = gateway
    for model in ("test-model", "other-model"):
        await client.post("/v1/chat/completions",
                          json={"model": model, "messages": [{"role": "user", "content": "x"}]},
                          headers={"X-Euthyna-Session": "sess-model"})
    assert ledger_rows(config)[1]["prefix_mutation"]["segments"] == ["model"]


async def test_healthz_and_stats(gateway):
    client, config, _ = gateway
    assert (await (await client.get("/healthz")).json())["ok"] is True
    await client.post("/v1/chat/completions", json={
        "model": "test-model", "messages": [{"role": "user", "content": "hello"}]})
    stats = await (await client.get("/euthyna/stats")).json()
    assert stats["calls"] == 1
    assert stats["prompt_tokens"] == 100
    assert stats["sessions"] == 1


# --- extract_actions: the tool calls a response actually made -------------------------

def test_openai_body_actions_in_order():
    from euthyna.gateway.taps import extract_actions
    body = {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "glob", "arguments": '{"pattern":"*.py"}'}},
        {"function": {"name": "read", "arguments": '{"path":"a.py"}'}},
    ]}}]}
    assert extract_actions("openai", body, None) == ["glob", "read"]


def test_openai_stream_accumulates_name_and_arguments_by_index():
    """The name arrives once; arguments arrive as fragments across later deltas."""
    from euthyna.gateway.taps import extract_actions
    sse = "\n".join([
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"bash","arguments":"{\\"comm"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"and\\":\\"grep -rn foo .\\"}"}}]}}]}',
        "data: [DONE]",
    ])
    assert extract_actions("openai", None, sse) == ["bash:grep"]


def test_anthropic_body_and_stream_agree():
    from euthyna.gateway.taps import extract_actions
    body = {"content": [
        {"type": "text", "text": "thinking"},
        {"type": "tool_use", "name": "bash", "input": {"command": "sed -i s/a/b/ f.py"}},
    ]}
    assert extract_actions("anthropic", body, None) == ["bash:sed"]
    sse = "\n".join([
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","name":"bash"}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"partial_json":"{\\"command\\":\\"sed -i s/a/b/ f.py\\"}"}}',
    ])
    assert extract_actions("anthropic", None, sse) == ["bash:sed"]


def test_only_the_command_verb_is_kept_never_its_arguments():
    """The verb distinguishes rituals; the rest is the user's data and is discarded."""
    from euthyna.gateway.taps import _refine_action
    secret = "grep -rn 'AKIAIOSFODNN7EXAMPLE' /home/loki/.aws/credentials"
    assert _refine_action("bash", {"command": secret}) == "bash:grep"
    got = _refine_action("bash", {"command": secret})
    assert "AKIA" not in got and "credentials" not in got and "loki" not in got


def test_absolute_paths_and_plain_verbs_are_the_same_action():
    from euthyna.gateway.taps import _refine_action
    assert _refine_action("bash", {"command": "/usr/bin/grep x ."}) == "bash:grep"
    assert _refine_action("bash", {"command": "grep x ."}) == "bash:grep"


def test_non_command_tools_are_not_refined():
    from euthyna.gateway.taps import _refine_action
    assert _refine_action("read", {"path": "a.py"}) == "read"
    assert _refine_action("edit", '{"file":"a.py"}') == "edit"


def test_unreadable_response_is_none_but_a_toolless_one_is_empty():
    """None and [] must not be conflated: unknown is never rendered as 'called nothing'."""
    from euthyna.gateway.taps import extract_actions
    assert extract_actions("openai", None, None) is None
    assert extract_actions("openai", {"choices": [{"message": {"content": "hi"}}]}, None) == []
    assert extract_actions("openai", None, "data: not json\n") == []


def test_malformed_arguments_degrade_to_the_bare_tool_name():
    from euthyna.gateway.taps import extract_actions, _refine_action
    assert _refine_action("bash", "{not json") == "bash"
    body = {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "bash", "arguments": "{truncated"}}]}}]}
    assert extract_actions("openai", body, None) == ["bash"]


# --- streaming action-parser regressions ---------------------------------------------

def test_deltas_without_an_index_do_not_collapse_into_one_call():
    """A provider that omits `index` would otherwise lose every call but the last."""
    from euthyna.gateway.taps import extract_actions
    sse = "\n".join([
        'data: {"choices":[{"delta":{"tool_calls":[{"function":{"name":"read","arguments":"{}"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"function":{"name":"edit","arguments":"{}"}}]}}]}',
    ])
    assert extract_actions("openai", None, sse) == ["read", "edit"]


def test_actions_are_ordered_by_index_not_arrival():
    """A signature is an ordered suffix match, so arrival order would mis-key it."""
    from euthyna.gateway.taps import extract_actions
    sse = "\n".join([
        'data: {"choices":[{"delta":{"tool_calls":[{"index":1,"function":{"name":"edit"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"read"}}]}}]}',
    ])
    assert extract_actions("openai", None, sse) == ["read", "edit"]


def test_arguments_still_accumulate_across_fragments_after_the_reorder():
    from euthyna.gateway.taps import extract_actions
    sse = "\n".join([
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"bash","arguments":"{\\"comm"}}]}}]}',
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"and\\":\\"grep -rn x .\\"}"}}]}}]}',
    ])
    assert extract_actions("openai", None, sse) == ["bash:grep"]


def test_anthropic_reused_block_index_keeps_both_calls_distinct():
    from euthyna.gateway.taps import extract_actions
    sse = "\n".join([
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","name":"bash"}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"partial_json":"{\\"command\\":\\"grep x\\"}"}}',
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","name":"bash"}}',
        'data: {"type":"content_block_delta","index":0,"delta":{"partial_json":"{\\"command\\":\\"sed y\\"}"}}',
    ])
    assert extract_actions("anthropic", None, sse) == ["bash:grep", "bash:sed"]


# --- privacy: only a bare command name may ever reach the ledger ----------------------

def test_env_assignment_prefix_does_not_leak_its_value():
    """Where secrets actually live. mini-swe-agent's own prompt template tells the agent
    to write `MY_ENV_VAR=MY_VALUE cd /path && ...`, so this is routine input."""
    from euthyna.gateway.taps import _refine_action
    got = _refine_action("bash", {"command": "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI grep foo ."})
    assert got == "bash:grep"
    assert "wJalrX" not in got
    got = _refine_action("bash", {"command": "A=1 B=2 C=3 sed -i s/x/y/ f.py"})
    assert got == "bash:sed"


def test_a_token_that_is_not_a_command_name_yields_no_detail():
    """Allowlist, not denylist: an unrecognised shape is data and gets discarded."""
    from euthyna.gateway.taps import _refine_action
    for cmd in ["curl?token=ghp_AbCdEf123456789",
                "aGVsbG8gd29ybGQgc2VjcmV0IHRva2VuIGRvbnQgbGVhaw==",
                "x" * 40,
                "--flag-only"]:
        assert _refine_action("bash", {"command": cmd}) == "bash", cmd


def test_ordinary_command_names_still_survive():
    from euthyna.gateway.taps import _refine_action
    for cmd, want in [("grep -rn foo .", "bash:grep"),
                      ("python3 -m pytest -q", "bash:python3"),
                      ("apt-get install -y curl", "bash:apt-get"),
                      ("/usr/bin/grep pattern .", "bash:grep"),
                      ('"grep" -rn x .', "bash:grep"),
                      ("g++ -o a a.cc", "bash:g++")]:
        assert _refine_action("bash", {"command": cmd}) == want, cmd


def test_no_command_at_all_degrades_to_the_tool_name():
    from euthyna.gateway.taps import _refine_action
    assert _refine_action("bash", {"command": "   "}) == "bash"
    assert _refine_action("bash", {"command": "FOO=1"}) == "bash"   # assignment only
    assert _refine_action("bash", {}) == "bash"


def test_a_credential_never_survives_any_position_in_the_line():
    """Property check across positions rather than one hand-picked case."""
    from euthyna.gateway.taps import _refine_action
    secret = "AKIAIOSFODNN7EXAMPLE"
    lines = [
        f"grep -rn {secret} /home/u/.aws/credentials",
        f"TOKEN={secret} python3 deploy.py",
        f"curl -H 'Authorization: {secret}' https://api.example.com",
        f"echo {secret} >> .env",
        f"{secret}",
        f"env AWS_KEY={secret} aws s3 ls",
    ]
    for line in lines:
        got = _refine_action("bash", {"command": line})
        assert secret not in got, (line, got)
        assert got.count(":") <= 1 and len(got) <= 40, (line, got)


# --- text-format harnesses (pre-tool-call action markup) ------------------------------

def test_xml_action_markup_is_recorded_when_there_is_no_tool_call():
    """mini-swe-agent's XML config is the only format some SFT'd models reliably emit."""
    from euthyna.gateway.taps import extract_actions
    body = {"choices": [{"message": {"content":
        "Let me look.\n\n<mswea_bash_command>ls -la requests/</mswea_bash_command>"}}]}
    assert extract_actions("openai", body, None) == ["bash:ls"]


def test_fenced_action_markup_is_recorded():
    from euthyna.gateway.taps import extract_actions
    for content, want in [
        ("THOUGHT: check\n\n```mswea_bash_command\ngrep -rn foo .\n```", ["bash:grep"]),
        ("```bash\nsed -i s/a/b/ f.py\n```", ["bash:sed"]),
        ("```sh\npython3 -m pytest\n```", ["bash:python3"]),
    ]:
        assert extract_actions("openai", {"choices": [{"message": {"content": content}}]},
                               None) == want, content


def test_a_tool_call_always_wins_over_text_markup():
    """Otherwise a harness using tool calls could be misread from stray prose."""
    from euthyna.gateway.taps import extract_actions
    body = {"choices": [{"message": {
        "tool_calls": [{"function": {"name": "bash", "arguments": '{"command":"ls"}'}}],
        "content": "<mswea_bash_command>rm -rf /</mswea_bash_command>"}}]}
    assert extract_actions("openai", body, None) == ["bash:ls"]


def test_text_markup_gets_the_same_privacy_minimisation():
    from euthyna.gateway.taps import extract_actions
    body = {"choices": [{"message": {"content":
        "<mswea_bash_command>AWS_KEY=wJalrXUtnFEMI grep x .</mswea_bash_command>"}}]}
    got = extract_actions("openai", body, None)
    assert got == ["bash:grep"] and "wJalrX" not in got[0]


def test_prose_with_no_action_is_empty_not_none():
    from euthyna.gateway.taps import extract_actions
    body = {"choices": [{"message": {"content": "just prose, no action here"}}]}
    assert extract_actions("openai", body, None) == []


def test_streamed_text_format_is_reassembled_before_parsing():
    """The command can be split across deltas; parsing per-chunk would miss it."""
    from euthyna.gateway.taps import extract_actions
    sse = "\n".join([
        'data: {"choices":[{"delta":{"content":"Let me check.\\n\\n<mswea_bash_"}}]}',
        'data: {"choices":[{"delta":{"content":"command>grep -rn x .</mswea_bash_command>"}}]}',
    ])
    assert extract_actions("openai", None, sse) == ["bash:grep"]


def test_editor_subcommand_is_kept_so_reading_differs_from_editing():
    """OpenHands routes view/create/str_replace through ONE tool name, so collapsing them
    erases the read-vs-edit distinction. Verified against a real OpenHands run rather than
    the mini-swe-agent corpus, which cannot exhibit this: it ran in text-action mode and
    contains no str_replace_editor call at all."""
    from euthyna.gateway.taps import _refine_action
    assert _refine_action("str_replace_editor",
                          {"command": "view", "path": "/a/b.py"}) == "str_replace_editor:view"
    assert _refine_action("str_replace_editor",
                          {"command": "str_replace"}) == "str_replace_editor:str_replace"
    # arguments arrive as a JSON string on the streaming path
    assert _refine_action("str_replace_editor",
                          '{"command":"create"}') == "str_replace_editor:create"


def test_editor_subcommand_never_echoes_anything_but_an_identifier():
    """The value is an enum, but it is still model output, so it is held to a shape
    rather than trusted. Degrading to the bare tool name loses detail; echoing loses
    the privacy property the whole tap is built on."""
    from euthyna.gateway.taps import _refine_action
    for bad in ("rm -rf / #inject", "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI",
                "/etc/passwd", "a" * 40, "", "View", 123, None, ["view"]):
        assert _refine_action("str_replace_editor", {"command": bad}) == "str_replace_editor"
    assert _refine_action("str_replace_editor", {}) == "str_replace_editor"
    assert _refine_action("str_replace_editor", "not json") == "str_replace_editor"


def test_shell_tools_are_unaffected_by_the_subcommand_path():
    from euthyna.gateway.taps import _refine_action
    assert _refine_action("execute_bash", {"command": "grep -rn foo"}) == "execute_bash:grep"
    assert _refine_action("bash", {"command": "sed -i s/a/b/ f"}) == "bash:sed"
    assert _refine_action("finish", {}) == "finish"


def test_digests_separate_identical_calls_from_merely_similar_ones():
    """The action name answers 'what kind of step'; the digest answers 'the same step
    again?'. Flow signatures need the first, repetition needs the second."""
    from euthyna.gateway.taps import extract_action_digests, extract_actions
    def call(cmd):
        return {"function": {"name": "bash",
                             "arguments": '{"command": "%s"}' % cmd}}
    body = {"choices": [{"message": {"tool_calls": [
        call("grep -rn a src/"), call("grep -rn a src/"), call("grep -rn b src/")]}}]}
    actions = extract_actions("openai", body, None)
    digests = extract_action_digests("openai", body, None)
    assert actions == ["bash:grep"] * 3          # the verb cannot tell them apart
    assert len(digests) == len(actions)          # positionally aligned
    assert digests[0] == digests[1] != digests[2]


def test_digest_never_carries_the_command_itself():
    from euthyna.gateway.taps import _payload_digest
    d = _payload_digest({"command": "curl -H 'Authorization: Bearer sk-secret' example.com"})
    assert d and len(d) == 16
    for leak in ("curl", "secret", "sk-", "Authorization", "example.com"):
        assert leak not in d


def test_the_streaming_and_body_paths_digest_a_call_identically():
    """A session that mixed the two would otherwise under-count its own repetition."""
    from euthyna.gateway.taps import _payload_digest
    assert _payload_digest('{"command": "ls -la"}') == _payload_digest({"command": "ls -la"})
    assert _payload_digest('{"a":1,"b":2}') == _payload_digest({"b": 2, "a": 1})


def test_calls_with_no_arguments_have_no_identity():
    """`{}` serialises non-empty, so digesting it would make every argument-less call
    look like a repeat of every other."""
    from euthyna.gateway.taps import _payload_digest
    for empty in (None, "", "   ", {}, [], "{}", "[]", "  {}  "):
        assert _payload_digest(empty) is None


def test_an_unreadable_response_yields_no_digests_rather_than_empty_ones():
    from euthyna.gateway.taps import extract_action_digests, extract_actions
    assert extract_actions("openai", None, None) is None
    assert extract_action_digests("openai", None, None) is None


# Verbatim shapes from an OpenHands 0.53 run against a model that cannot emit native tool
# calls under agent-shaped prompts. Note there is no closing </function>.
_OH_VIEW = ("<function=str_replace_editor>\n<parameter=path>/w/a.py</parameter>\n"
            "<parameter=command>view</parameter>\n<parameter=view_range>[45, 51]</parameter>\n")
_OH_BASH = "<function=execute_bash>\n<parameter=command>cd /w && pytest -x</parameter>\n"


def _content(text):
    return {"choices": [{"message": {"content": text}}]}


def test_openhands_prompt_based_tool_calls_are_recorded():
    """Without this the tap reads OpenHands runs as 'the model called no tools' — which is
    indistinguishable, downstream, from a model that genuinely did nothing."""
    from euthyna.gateway.taps import extract_actions
    assert extract_actions("openai", _content(_OH_VIEW), None) == ["str_replace_editor:view"]
    assert extract_actions("openai", _content(_OH_BASH), None) == ["execute_bash:pytest"]
    # order preserved across several blocks in one response
    assert extract_actions("openai", _content(_OH_VIEW + _OH_BASH), None) == [
        "str_replace_editor:view", "execute_bash:pytest"]


def test_a_missing_closing_tag_does_not_silently_swallow_the_action():
    """The model does not emit </function>, and the final </parameter> is often absent too.
    A pattern requiring either records nothing while looking like it worked."""
    from euthyna.gateway.taps import extract_actions
    unclosed = "<function=execute_bash>\n<parameter=command>ls -la"
    assert extract_actions("openai", _content(unclosed), None) == ["execute_bash:ls"]


def test_openhands_parameter_values_are_never_echoed():
    from euthyna.gateway.taps import extract_actions
    leaky = ("<function=str_replace_editor>\n<parameter=command>str_replace</parameter>\n"
             "<parameter=old_str>AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI</parameter>\n")
    actions = extract_actions("openai", _content(leaky), None)
    assert actions == ["str_replace_editor:str_replace"]
    assert "wJalrX" not in "".join(actions)


def test_the_other_harnesses_text_formats_still_parse():
    from euthyna.gateway.taps import extract_actions
    assert extract_actions(
        "openai", _content("<mswea_bash_command>grep -rn x</mswea_bash_command>"), None
    ) == ["bash:grep"]
    assert extract_actions("openai", _content("prose with no tool call"), None) == []


def test_a_directory_change_does_not_stand_in_for_the_real_command():
    """A shell agent working in a repo prefixes almost everything with `cd`. Naming the
    line by its first token records the navigation instead of the work: on the 28-instance
    SWE-bench corpus 339 of 1004 commands (33.8%) recorded as bash:cd, and every one was
    a compound. `cd` fell to 0 once this was fixed; python went 38 -> 112."""
    from euthyna.gateway.taps import _command_verb
    assert _command_verb("cd /repo && grep -rn foo") == "grep"
    assert _command_verb("cd /a && sed -i s/x/y/ f.py") == "sed"
    assert _command_verb("cd /a; ls -la") == "ls"
    assert _command_verb("cd /a || echo fail") == "echo"
    assert _command_verb("pushd /a && pytest -x") == "pytest"
    assert _command_verb("MY_VAR=1 cd /a && pytest") == "pytest"
    assert _command_verb("cd /a && /usr/bin/python3 -m pytest") == "python3"


def test_a_bare_navigation_command_is_still_reported_as_one():
    """The point is to skip navigation that PREFIXES work, not to lose it when it is the
    work — otherwise `cd` becomes unnameable rather than merely uninteresting."""
    from euthyna.gateway.taps import _command_verb
    assert _command_verb("cd /repo") == "cd"
    assert _command_verb("cd") == "cd"
    assert _command_verb("cd /a && cd /b") == "cd"


def test_skipping_a_segment_still_cannot_put_data_in_the_ledger():
    """Each segment goes through the same allowlist, so advancing past `cd` can cost
    detail but can never promote a fragment of user data into an action name."""
    from euthyna.gateway.taps import _command_verb
    assert _command_verb("cd /a && AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI") == "cd"
    assert _command_verb("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI") is None
    assert _command_verb("cd /a && ./THIS_IS_A_VERY_LONG_NAME_INDEED") == "cd"
