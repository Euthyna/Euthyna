"""euthyna — the command line. Four verbs: up, probe, report, doctor (+ analyze).

`up` runs the gateway; everything else is offline/read-only against ledgers,
traces, and profiles. See docs/SETUP.md for the end-to-end walkthrough.
"""
from __future__ import annotations

import argparse

from euthyna.version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="euthyna",
        description="Agent-runtime audit gateway: meter task-total LLM cost, "
                    "watch cache/prefix health, intervene only with evidence.",
    )
    parser.add_argument("--version", action="version", version=f"euthyna {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="run the gateway (sidecar data plane)")
    up.add_argument("--profile", default="profiles/vllm-metal.yaml",
                    help="backend profile YAML, relative to the current directory — "
                         "written by `euthyna probe` (default: %(default)s)")
    up.add_argument("--anthropic-profile", default=None,
                    help="optional profile for the /v1/messages dialect")
    up.add_argument("--port", type=int, default=4517)

    probe = sub.add_parser("probe", help="measure a backend and write its profile")
    probe.add_argument("--base-url", default="http://127.0.0.1:8000")
    probe.add_argument("--name", default="vllm-metal")
    probe.add_argument("--out", default="profiles")
    probe.add_argument("--api-key-env", default=None, metavar="ENV_NAME",
                       help="env var holding the API key for cloud backends "
                            "(the name goes in the profile; the key never does)")
    probe.add_argument("--model", default=None,
                       help="model id to probe (default: first from /v1/models)")

    report = sub.add_parser("report", help="aggregate a day's ledger")
    report.add_argument("--date", default=None, help="YYYY-MM-DD (default: today)")
    report.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="preflight the backend → gateway → host pipeline")
    doctor.add_argument("--profile", default="profiles/vllm-metal.yaml")
    doctor.add_argument("--port", type=int, default=4517)
    doctor.add_argument("--host", choices=["opencode", "none"], default="opencode")

    analyze = sub.add_parser("analyze", help="Serving-B advisory read of today's ledger+traces "
                                             "(EXPERIMENTAL narrative advisor — judgment quality "
                                             "not validated; never acts)")
    analyze.add_argument("--advisor-url", default="http://127.0.0.1:8001",
                         help="any OpenAI-dialect endpoint — local Serving B or a "
                              "frontier API (default: %(default)s)")
    analyze.add_argument("--advisor-api-key-env", default=None, metavar="ENV_NAME")
    analyze.add_argument("--advisor-model", default=None,
                         help="model id (default: first from the endpoint's /v1/models)")
    analyze.add_argument("--date", default=None)

    submit = sub.add_parser("submit", help="package local telemetry (hash-only tier) into an "
                                           "offline submission tarball — nothing is uploaded")
    submit.add_argument("--from", dest="from_date", default=None, metavar="YYYY-MM-DD",
                        help="start day (default: --to day only)")
    submit.add_argument("--to", dest="to_date", default=None, metavar="YYYY-MM-DD",
                        help="end day (default: today)")
    submit.add_argument("--out", default=".", help="output directory (default: current)")
    submit.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    submit.add_argument("--include-model-names", action="store_true",
                        help="keep raw model names (default: pseudonymized hashes)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "up":
        from euthyna.gateway import GatewayConfig, Profile, run as run_gateway
        try:
            profile = Profile.load(args.profile)
            anthropic = Profile.load(args.anthropic_profile) if args.anthropic_profile else None
        except FileNotFoundError:
            print(f"up: profile {args.profile} not found — run `euthyna probe "
                  f"--base-url http://127.0.0.1:8000 --name <name>` first")
            return 1
        except Exception as exc:
            print(f"up: could not load profile: {exc}")
            return 1
        if profile.dialect != "openai":
            print(f"up: --profile must be an openai-dialect backend (got {profile.dialect!r}); "
                  "use --anthropic-profile for the /v1/messages side")
            return 1
        config = GatewayConfig(profile=profile, anthropic_profile=anthropic, port=args.port)
        print(f"euthyna up — port {config.port}, backend {config.profile.base_url}, "
              f"home {config.home}{' [TRANSPARENT]' if config.transparent else ''}")
        run_gateway(config)
        return 0
    if args.command == "probe":
        from . import probe
        return probe.run(args)
    if args.command == "report":
        from . import report
        return report.run(args)
    if args.command == "doctor":
        from . import doctor
        return doctor.run(args)
    if args.command == "analyze":
        from . import analyze
        return analyze.run(args)
    if args.command == "submit":
        from . import submit
        return submit.run(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
