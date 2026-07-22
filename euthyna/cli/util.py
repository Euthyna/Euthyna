"""Small shared helpers for the CLI."""
from __future__ import annotations

import os
from typing import Optional


def bearer(env_name: Optional[str]) -> dict:
    """Authorization header from a NAMED env var — the key itself never lives in
    config or profiles. Empty dict when no env name given or the var is unset."""
    if not env_name:
        return {}
    value = os.environ.get(env_name)
    if not value:
        return {}
    return {"Authorization": f"Bearer {value}"}
