"""Parameters for the reduced ProScale clone."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProscaleParams:
    # ProScale §5: simple moving average with N=2, applied every decision.
    sma_window: int = 2
    min_replicas: int = 1
    max_replicas: int = 100


def validate_params(raw: dict[str, Any]) -> ProscaleParams:
    data = dict(raw)
    params = ProscaleParams(
        sma_window=int(data.pop("sma_window", 2)),
        min_replicas=int(data.pop("min_replicas", 1)),
        max_replicas=int(data.pop("max_replicas", 100)),
    )
    if data:
        raise ValueError(f"unknown proscale params: {sorted(data)}")
    if params.sma_window < 1:
        raise ValueError("sma_window must be >= 1")
    if params.min_replicas < 1:
        raise ValueError("min_replicas must be >= 1")
    if params.max_replicas < params.min_replicas:
        raise ValueError("max_replicas must be >= min_replicas")
    return params
