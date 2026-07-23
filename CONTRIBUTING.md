# Contributing

## Setup and tests

```bash
git clone https://github.com/cdc542559455/Euthyna.git && cd Euthyna
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest
```

(`uv venv && uv pip install -e ".[test]"` works too.) The suite is mock-backed:
no GPU, no model, no network. `pytest` is the only supported runner. Lint with
`pip install -e ".[lint]" && ruff check .`.

## Ground rules

- **Do not refactor `euthyna/core/`.** It is a rename-only port of the upstream
  arcp research SDK (see PROVENANCE.md) and stays byte-parallel to it so upstream
  fixes can be re-ported mechanically. Changes there need a matching upstream
  change or a very good reason.
- **Fail-open is a contract.** Nothing in the observation path may block or alter
  the proxied traffic. If your change can raise, it must be inside the existing
  try/except seams — and add a test proving the pipe survives.
- **Never fabricate accounting.** A value the provider did not return is `None`
  or explicitly flagged imputed — never a silent 0. There are tests pinning this.
- **Claims need evidence.** Docs state only what was measured; numbers cite the
  committed artifact that produced them (a profile, a benchmark summary).
- Keep it small. New dependencies, layers, or config surface need a stronger
  justification than new code.

## PR checklist

- [ ] `pytest` green, `ruff check .` clean
- [ ] New behavior has a test (mock-backed; no live services in CI)
- [ ] Docs updated if commands, flags, or file formats changed
- [ ] No personal data, machine paths, credentials, or key material — env-var
      names only
