"""CLI tests: probe's measurement logic, report aggregation, profile round-trip."""
import copy
import json

import pytest
import yaml

from euthyna.cli.main import build_parser
from euthyna.cli.probe import measure_cache_schema
from euthyna.cli.report import aggregate
from euthyna.core import accountant
from euthyna.core.accountant import cost_row_from_usage
from euthyna.gateway import Profile


def test_measure_cache_schema_vllm_style():
    first = {"prompt_tokens": 1200, "completion_tokens": 5}
    second = {"prompt_tokens": 1200, "completion_tokens": 5,
              "prompt_tokens_details": {"cached_tokens": 1184}}
    schema = measure_cache_schema(first, second)
    assert schema["cached_tokens"] == {
        "surfaces": True, "path": ["prompt_tokens_details", "cached_tokens"]}
    assert schema["cache_creation_tokens"]["surfaces"] is False


def test_measure_cache_schema_nothing_surfaces():
    usage = {"prompt_tokens": 1200, "completion_tokens": 5}
    schema = measure_cache_schema(usage, usage)
    assert all(not spec["surfaces"] for spec in schema.values())


def test_measure_cache_schema_reasoning():
    second = {"prompt_tokens": 10, "completion_tokens": 50,
              "completion_tokens_details": {"reasoning_tokens": 40}}
    schema = measure_cache_schema({}, second)
    assert schema["reasoning_tokens"]["surfaces"] is True


def test_report_aggregate():
    rows = [
        {"session": "s1", "usage": {"prompt_tokens": 100, "completion_tokens": 10},
         "cost": {"native_tokens": {"cached_tokens": 80}, "list_cost_usd": 0.01},
         "prefix_stable_ratio": None, "model": "m", "gateway_injected": True},
        {"session": "s1", "usage": {"prompt_tokens": 200, "completion_tokens": 20},
         "cost": {"native_tokens": {"cached_tokens": 150}, "list_cost_usd": 0.02},
         "prefix_stable_ratio": 1.0, "model": "m", "gateway_injected": False},
    ]
    out = aggregate(rows)
    s1 = out["s1"]
    assert s1["calls"] == 2
    assert s1["prompt_tokens"] == 300
    assert s1["cached_tokens"] == 230
    assert s1["cost_usd"] == 0.03
    assert s1["mean_prefix_stable_ratio"] == 1.0
    assert s1["cached_fraction"] == round(230 / 300, 4)
    assert s1["injected"] == 1


def test_parser_subcommands():
    parser = build_parser()
    assert parser.parse_args(["up", "--port", "5000"]).port == 5000
    assert parser.parse_args(["probe"]).base_url == "http://127.0.0.1:8000"
    assert parser.parse_args(["report", "--json"]).json is True
    assert parser.parse_args(["doctor"]).host == "opencode"
    assert parser.parse_args(["analyze"]).advisor_url == "http://127.0.0.1:8001"


@pytest.fixture
def registries():
    schemas, sheet = copy.deepcopy(accountant.PROVIDER_CACHE_SCHEMAS), copy.deepcopy(accountant.PRICE_SHEET)
    yield
    accountant.PROVIDER_CACHE_SCHEMAS.clear()
    accountant.PROVIDER_CACHE_SCHEMAS.update(schemas)
    accountant.PRICE_SHEET.clear()
    accountant.PRICE_SHEET.update(sheet)


def test_probe_profile_round_trip(tmp_path, registries):
    """A probe-shaped profile loads, registers, and yields observed cost rows."""
    profile_yaml = {
        "name": "vllm-test", "dialect": "openai", "base_url": "http://127.0.0.1:8000",
        "model": "some/model-4bit", "accountant_model": "local/vllm-test",
        "price_date": "2026-07-21",
        "prices_per_1m": {"input": 0.0, "cached_input": 0.0, "output": 0.0, "cache_creation": None},
        "cache_schema": {
            "cached_tokens": {"surfaces": True, "path": ["prompt_tokens_details", "cached_tokens"]},
            "cache_creation_tokens": {"surfaces": False, "path": None},
            "reasoning_tokens": {"surfaces": False, "path": None},
        },
    }
    path = tmp_path / "vllm-test.yaml"
    path.write_text(yaml.safe_dump(profile_yaml))

    profile = Profile.load(path)
    profile.register()
    row = cost_row_from_usage(
        {"prompt_tokens": 1200, "completion_tokens": 5,
         "prompt_tokens_details": {"cached_tokens": 1184}},
        model="local/vllm-test", price_date="2026-07-21",
    )
    assert row["observed_flags"]["cached_tokens"] is True
    assert row["native_tokens"]["cached_tokens"] == 1184
    assert row["native_tokens"]["cache_creation_tokens"] is None  # never fabricated
    assert row["list_cost_usd"] == 0.0
