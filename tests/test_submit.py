"""Submission packaging tests: sanitization, content-leak guard, bundle round-trip."""
import json
import tarfile


from euthyna.cli.main import build_parser
from euthyna.cli.submit import collect, summarize, write_bundle


def make_home(tmp_path, rows, events=None):
    home = tmp_path / "home"
    (home / "ledger").mkdir(parents=True)
    (home / "traces").mkdir()
    (home / "ledger" / "2026-07-24.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows))
    if events:
        (home / "traces" / "ses_secret_name_xyz.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events))
    return home


ROW = {"ts": "2026-07-24T10:00:00+08:00", "session": "ses_secret_name_xyz",
       "dialect": "openai", "path": "/v1/chat/completions", "status": 200,
       "model": "m", "latency_ms": 5.0,
       "usage": {"prompt_tokens": 100, "completion_tokens": 10},
       "gateway_injected": False, "prefix_stable_ratio": 0.9,
       "cost": None, "cost_error": None, "tap_truncated": False}


def test_sessions_anonymized_and_counts(tmp_path):
    home = make_home(tmp_path, [ROW, {**ROW, "session": "other"}],
                     events=[{"ts": "2026-07-24T10:00:00+08:00", "n_messages": 2,
                              "roles": ["system", "user"], "message_sha256": ["ab", "cd"],
                              "message_bytes": [10, 20], "prefix_stable_ratio": None}])
    bundle = collect(home, "2026-07-24", "2026-07-24")
    rows = bundle["ledgers"]["2026-07-24.jsonl"]
    assert {r["session"] for r in rows} == {"s001", "s002"}
    assert "s001.jsonl" in bundle["traces"]  # trace filename re-mapped too
    manifest = summarize(bundle)
    assert manifest["calls"] == 2
    assert manifest["sessions"] == 2
    assert manifest["prompt_tokens"] == 200
    assert manifest["tier"] == "hash-only"
    assert manifest["schema"] == 2


def test_allowlist_drops_unknown_fields_and_pseudonymizes(tmp_path):
    bad = {**ROW, "surprise": "x" * 500, "model": "mlx-community/secret-model"}
    home = make_home(tmp_path, [bad])
    bundle = collect(home, "2026-07-24", "2026-07-24")
    (row,) = bundle["ledgers"]["2026-07-24.jsonl"]
    assert "surprise" not in row  # allowlist projection, not filtering
    assert row["model"].startswith("model-") and "secret" not in row["model"]
    named = collect(home, "2026-07-24", "2026-07-24", include_model_names=True)
    assert named["ledgers"]["2026-07-24.jsonl"][0]["model"] == "mlx-community/secret-model"


def test_cost_error_becomes_enum(tmp_path):
    row = {**ROW, "cost_error": "model local/foo not in price sheet 2026-07-21 " + "x" * 200}
    home = make_home(tmp_path, [row])
    bundle = collect(home, "2026-07-24", "2026-07-24")
    assert bundle["ledgers"]["2026-07-24.jsonl"][0]["cost_error"] == "unknown_model"


def test_message_hashes_rekeyed_per_submission(tmp_path):
    events = [{"ts": "2026-07-24T10:00:00+08:00", "n_messages": 2,
               "roles": ["system", "user"], "message_sha256": ["aabb", "aabb"],
               "message_bytes": [10, 20], "prefix_stable_ratio": None}]
    home = make_home(tmp_path, [ROW], events=events)
    one = collect(home, "2026-07-24", "2026-07-24")["traces"]["s001.jsonl"][0]
    two = collect(home, "2026-07-24", "2026-07-24")["traces"]["s001.jsonl"][0]
    assert one["message_hmac"][0] == one["message_hmac"][1]  # structure preserved within
    assert one["message_hmac"][0] != "aabb"  # never the raw hash
    assert one["message_hmac"][0] != two["message_hmac"][0]  # fresh salt per submission
    assert "message_sha256" not in one


def test_date_filter(tmp_path):
    home = make_home(tmp_path, [ROW])
    assert collect(home, "2026-07-01", "2026-07-02")["ledgers"] == {}


def test_bundle_round_trip(tmp_path):
    home = make_home(tmp_path, [ROW])
    bundle = collect(home, "2026-07-24", "2026-07-24")
    out = write_bundle(bundle, summarize(bundle), tmp_path / "out")
    with tarfile.open(out) as tar:
        names = tar.getnames()
        assert "MANIFEST.json" in names
        assert "ledger/2026-07-24.jsonl" in names
        manifest = json.loads(tar.extractfile("MANIFEST.json").read())
        assert manifest["submission_id"] in out.name
        row = json.loads(tar.extractfile("ledger/2026-07-24.jsonl").read())
        assert row["session"] == "s001"
        assert "secret" not in json.dumps(row)


def test_parser_flags():
    args = build_parser().parse_args(["submit", "--from", "2026-07-01", "--yes"])
    assert (args.from_date, args.to_date, args.yes) == ("2026-07-01", None, True)
