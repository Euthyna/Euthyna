# Provenance

Euthyna's core library (`euthyna/core/`) is a rename-only port of the **arcp SDK
v0.1.0** ("agent-runtime control-plane SDK"), produced by the same research
program that Euthyna productizes.

- Upstream: research repository `agent-runtime-trace-taxonomy` (currently
  private; an evidence pack is planned for publication), path
  `projects/agent-runtime-trace-taxonomy/sdk/arcp/`, tag `arcp-v0.1.0`,
  commit `d7b0a2a54a83d255fe084737bab984168e27f2b4` (2026-07-20).
  Release kit hash: `af58c558`.
- License: the upstream arcp SDK is Apache-2.0, the same license as this
  repository; the port retains those terms. Copyright remains with the research
  program's authors, who publish this port.
- Port parity: `accountant.py`, `trajectory.py`, `verifier.py`, `transforms.py`,
  `adapters/{base,sweagent,openhands}.py` and all three test fixtures are
  identical to the tag modulo the `s/arcp/euthyna/` rename and re-nesting under
  `euthyna.core` (verified 2026-07-21: `diff` after `sed` produces zero output).
- Deliberately deferred from the port (exist upstream at the tag, re-port rather
  than rewrite): `engine.py` (policy engine), `dispatch.py`, `calibration.py`,
  `cli.py`, `examples/*.yaml`, and 12 of arcp's 34 tests (`test_engine`,
  `test_calibration`, `test_version`).

This repository starts with fresh history per the research repo's extraction
rules. The design lineage (evidence base, architecture v0.3) is documented in
`docs/`.
