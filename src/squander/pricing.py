"""Load per-model prices from prices.yaml and compute dollar costs.

Prices live in config, never in code: providers change them, and a
config edit shouldn't require a redeploy. All prices are USD per
1,000,000 tokens.

Cache writes are priced by TTL (the 1-hour cache costs more than the
5-minute one). Claude Code's session logs break cache writes down by
TTL, so costs computed from that breakdown are exact.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import yaml

TOKENS_PER_UNIT = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens for one model, split by token kind."""

    input: float
    output: float
    cache_read: float
    cache_write_5m: float
    cache_write_1h: float


class PriceBook:
    """Model prices plus defaults, loaded from a prices.yaml file."""

    def __init__(self, models: dict, chars_per_token: float):
        self._models = models
        self.chars_per_token = chars_per_token

    def get(self, model: str) -> Optional[ModelPrice]:
        """Price for a model, or None if the model isn't in the config."""
        return self._models.get(model)

    def cost(
        self,
        model: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_5m_tokens: int = 0,
        cache_write_1h_tokens: int = 0,
    ) -> Optional[float]:
        """Dollar cost of a token bundle, or None for an unpriced model.

        Returning None (rather than 0.0) keeps "we don't know" distinct
        from "free" so callers can surface unpriced models instead of
        silently under-reporting cost.
        """
        price = self.get(model)
        if price is None:
            return None
        return (
            input_tokens * price.input
            + output_tokens * price.output
            + cache_read_tokens * price.cache_read
            + cache_write_5m_tokens * price.cache_write_5m
            + cache_write_1h_tokens * price.cache_write_1h
        ) / TOKENS_PER_UNIT


def _find_default_prices_file() -> Path:
    """Locate prices.yaml: current directory first, then the repo root.

    The cwd comes first so a user can override prices per-project
    without touching the squander checkout.
    """
    cwd_candidate = Path.cwd() / "prices.yaml"
    if cwd_candidate.exists():
        return cwd_candidate
    # src/squander/pricing.py -> repo root is two levels above src/.
    repo_candidate = Path(__file__).resolve().parents[2] / "prices.yaml"
    if repo_candidate.exists():
        return repo_candidate
    raise FileNotFoundError(
        "No prices.yaml found in the current directory or the squander "
        "repo root; pass an explicit path."
    )


def load_prices(path: Optional[Union[Path, str]] = None) -> PriceBook:
    path = Path(path) if path is not None else _find_default_prices_file()
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    models = {}
    for name, fields in (raw.get("models") or {}).items():
        models[name] = ModelPrice(
            input=float(fields["input"]),
            output=float(fields["output"]),
            cache_read=float(fields["cache_read"]),
            cache_write_5m=float(fields["cache_write_5m"]),
            cache_write_1h=float(fields["cache_write_1h"]),
        )

    defaults = raw.get("defaults") or {}
    return PriceBook(
        models=models,
        chars_per_token=float(defaults.get("chars_per_token", 4.0)),
    )
