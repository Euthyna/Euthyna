"""Gateway configuration and backend profiles.

A profile is one YAML file describing one backend: where it lives, which dialect
it speaks, what its usage payloads surface (measured by `euthyna probe`, never
assumed), and a dated price sheet. Loading a profile registers its model in the
accountant so cost rows can be computed; the core library stays untouched.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from euthyna.core import accountant

DEFAULT_PORT = 4517
USAGE_CATEGORIES = ("cached_tokens", "cache_creation_tokens", "reasoning_tokens")


@dataclass
class Profile:
    """One backend, as measured. See profiles/ for the YAML schema by example."""

    name: str
    dialect: str  # "openai" | "anthropic"
    base_url: str
    accountant_model: Optional[str] = None
    price_date: Optional[str] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Profile":
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls(
            name=data.get("name", Path(path).stem),
            dialect=data.get("dialect", "openai"),
            base_url=data["base_url"].rstrip("/"),
            accountant_model=data.get("accountant_model"),
            price_date=data.get("price_date"),
            raw=data,
        )

    def register(self) -> None:
        """Publish this profile's cache schema + prices into the accountant registries.

        Only what the profile explicitly provides is registered, and never over an
        existing entry: a profile may *reference* a built-in model by name (providing
        nothing), or *define* a new one, but silently overwriting is an error. Price
        keys are required when given — an incomplete sheet fails loudly at startup
        rather than producing fabricated $0 cost rows.
        """
        if not (self.accountant_model and self.price_date):
            return
        if "cache_schema" in self.raw:
            if self.accountant_model in accountant.PROVIDER_CACHE_SCHEMAS:
                raise ValueError(
                    f"profile {self.name!r}: cache schema for {self.accountant_model!r} "
                    "already registered — pick a different accountant_model name")
            schema = {}
            for cat in USAGE_CATEGORIES:
                spec = self.raw["cache_schema"].get(cat) or {}
                path = spec.get("path")
                schema[cat] = {
                    "surfaces": bool(spec.get("surfaces")),
                    "path": tuple(path) if path else None,
                }
            accountant.PROVIDER_CACHE_SCHEMAS[self.accountant_model] = schema
        if "prices_per_1m" in self.raw:
            sheet = accountant.PRICE_SHEET.setdefault(self.price_date, {})
            if self.accountant_model in sheet:
                raise ValueError(
                    f"profile {self.name!r}: {self.accountant_model!r} already priced "
                    f"on sheet {self.price_date} — pick a different name or date")
            prices = self.raw["prices_per_1m"]
            sheet[self.accountant_model] = {
                "input_per_1m": prices["input"],
                "cached_input_per_1m": prices["cached_input"],
                "output_per_1m": prices["output"],
                "cache_creation_per_1m": prices.get("cache_creation"),
                "notes": f"registered from profile {self.name!r}",
            }


@dataclass
class GatewayConfig:
    """Everything the gateway process needs. Env knobs: EUTHYNA_TRANSPARENT, EUTHYNA_HOME."""

    profile: Optional[Profile] = None  # OpenAI-dialect backend (/v1/chat/completions, ...)
    anthropic_profile: Optional[Profile] = None  # optional /v1/messages backend
    port: int = DEFAULT_PORT
    home: Path = field(default_factory=lambda: Path(os.environ.get("EUTHYNA_HOME", "~/.euthyna")).expanduser())
    transparent: bool = field(default_factory=lambda: os.environ.get("EUTHYNA_TRANSPARENT") == "1")

    @property
    def ledger_dir(self) -> Path:
        return self.home / "ledger"

    @property
    def traces_dir(self) -> Path:
        return self.home / "traces"

    def profile_for(self, dialect: str) -> Optional[Profile]:
        if dialect == "anthropic":
            return self.anthropic_profile  # unconfigured → explicit 502, not silent fallback
        return self.profile

    def register_profiles(self) -> None:
        for p in (self.profile, self.anthropic_profile):
            if p is not None:
                p.register()
