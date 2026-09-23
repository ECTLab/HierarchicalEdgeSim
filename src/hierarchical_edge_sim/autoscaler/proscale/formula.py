"""ProScale-style replica count from a short moving average (no env)."""

from __future__ import annotations

import math


def moving_average(samples: list[float], window: int) -> float:
    """Mean of the last ``window`` samples. Fewer samples use whatever exists."""
    if window < 1:
        raise ValueError("window must be >= 1")
    if not samples:
        return 0.0
    used = samples[-window:]
    return sum(used) / len(used)


def desired_instances(
    forecast: float,
    mu_per_replica: float,
    *,
    min_replicas: int,
    max_replicas: int,
) -> int:
    """How many fixed-size replicas cover ``forecast`` at one replica's throughput."""
    if min_replicas < 1:
        raise ValueError("min_replicas must be >= 1")
    if forecast <= 0.0 or mu_per_replica <= 0.0:
        return min_replicas
    raw = max(1, math.ceil(forecast / mu_per_replica - 1e-12))
    return max(min_replicas, min(max_replicas, raw))
