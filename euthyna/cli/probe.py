"""`euthyna probe` — measure what a backend's usage payloads actually surface.

The probe sends two identical long-prefix completions and reads the usage fields the
backend returns. Whatever it writes into the profile is *measured evidence*, never an
assumption: a field the backend does not return is recorded surfaces=false, and the
raw usage payloads are kept in the profile as the evidence for the verdict.
"""
from __future__ import annotations

import datetime as _dt
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

import yaml

# ~1200 tokens of deterministic filler: long enough to span many KV-cache blocks.
_FILLER = " ".join(f"calibration line {i}: the quick brown fox jumps over the lazy dog." for i in range(160))


def _post_json(url: str, payload: dict, timeout: float = 120.0, headers: dict = {}) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **headers},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _get_json(url: str, timeout: float = 10.0, headers: dict = {}) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def measure_cache_schema(first_usage: dict, second_usage: dict) -> dict:
    """Decide the cache schema from two identical-prompt calls (pure function).

    A category 'surfaces' only if the provider actually returned it. cached_tokens is
    judged on the SECOND call, where an identical prefix makes a cache hit possible.
    """
    details = (second_usage or {}).get("prompt_tokens_details") or {}
    completion_details = (second_usage or {}).get("completion_tokens_details") or {}
    schema = {
        "cached_tokens": {"surfaces": False, "path": None},
        "cache_creation_tokens": {"surfaces": False, "path": None},
        "reasoning_tokens": {"surfaces": False, "path": None},
    }
    if details.get("cached_tokens") is not None:
        schema["cached_tokens"] = {
            "surfaces": True, "path": ["prompt_tokens_details", "cached_tokens"]}
    if details.get("cache_creation_tokens") is not None:
        schema["cache_creation_tokens"] = {
            "surfaces": True, "path": ["prompt_tokens_details", "cache_creation_tokens"]}
    if completion_details.get("reasoning_tokens") is not None:
        schema["reasoning_tokens"] = {
            "surfaces": True, "path": ["completion_tokens_details", "reasoning_tokens"]}
    return schema


def probe(base_url: str, name: str, out_dir: str = "profiles",
          api_key_env: Optional[str] = None, model: Optional[str] = None) -> Path:
    from .util import bearer

    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):  # accept both forms; paths below append /v1/...
        base_url = base_url[:-3].rstrip("/")
    auth = bearer(api_key_env)
    if model is None:
        models = _get_json(f"{base_url}/v1/models", headers=auth)
        model = models["data"][0]["id"]

    messages = [
        {"role": "system", "content": "You are a terse assistant. " + _FILLER},
        {"role": "user", "content": "Reply with the single word: ready."},
    ]
    payload = {"model": model, "messages": messages, "max_tokens": 8, "temperature": 0}
    import time
    t0 = time.monotonic()
    first = _post_json(f"{base_url}/v1/chat/completions", payload, headers=auth)
    t1 = time.monotonic()
    second = _post_json(f"{base_url}/v1/chat/completions", payload, headers=auth)
    t2 = time.monotonic()
    first_usage, second_usage = first.get("usage") or {}, second.get("usage") or {}
    latency = {"first_ms": round((t1 - t0) * 1000, 1), "second_ms": round((t2 - t1) * 1000, 1)}

    schema = measure_cache_schema(first_usage, second_usage)
    today = _dt.date.today().isoformat()
    profile = {
        "name": name,
        "dialect": "openai",
        "base_url": base_url,
        "api_key_env": api_key_env,  # env var NAME only; the key never touches disk
        "model": model,
        "accountant_model": f"local/{name}",
        "price_date": today,
        "prices_per_1m": {"input": 0.0, "cached_input": 0.0, "output": 0.0,
                          "cache_creation": None},
        "cache_schema": schema,
        "probe": {
            "date": today,
            "method": "two identical long-prefix chat completions, temperature 0",
            "first_usage": first_usage,
            "second_usage": second_usage,
            # Client-side latency is side evidence for prefix caching when the
            # backend does not surface cached_tokens (a big drop implies a cache hit).
            "latency": latency,
        },
    }
    out = Path(out_dir) / f"{name}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True))
    return out


def run(args) -> int:
    try:
        out = probe(args.base_url, args.name, args.out,
                    api_key_env=args.api_key_env, model=args.model)
    except (urllib.error.URLError, OSError) as exc:
        print(f"probe: backend unreachable at {args.base_url} ({exc}) — is it running?")
        return 1
    profile = yaml.safe_load(out.read_text())
    cached = profile["cache_schema"]["cached_tokens"]
    print(f"probe: wrote {out}")
    print(f"probe: model = {profile['model']}")
    print(f"probe: cached_tokens surfaces = {cached['surfaces']} (measured, second call: "
          f"{json.dumps(profile['probe']['second_usage'])})")
    if args.api_key_env:
        print("probe: NOTE — prices_per_1m in the profile are 0.0 placeholders; edit them to "
              "the provider's real list prices or every $ in `euthyna report` will read 0")
    return 0
