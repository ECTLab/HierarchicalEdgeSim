"""Kubernetes HPA replica math (no env dependency)."""

from __future__ import annotations

import math


def desired_replicas(
    current: int,
    util: float,
    *,
    target: float,
    tolerance: float,
    min_replicas: int,
    max_replicas: int,
) -> int:
    """``ceil(current * util / target)``, with HPA tolerance and min/max clamps."""
    if current < 1:
        return min_replicas
    if target <= 0.0:
        return current
    ratio = util / target
    if abs(ratio - 1.0) <= tolerance:
        return current
    raw = max(0, math.ceil(current * ratio - 1e-12))
    return max(min_replicas, min(max_replicas, raw))


def apply_scale_up_limit(
    current: int,
    desired: int,
    *,
    scale_up_pods: int,
    scale_up_percent: float,
) -> int:
    """Cap how many replicas may be added in one period (HPA v2 Max of pods/percent)."""
    if desired <= current:
        return desired
    percent_add = math.ceil(current * scale_up_percent / 100.0 - 1e-12) if current > 0 else scale_up_pods
    max_add = max(scale_up_pods, percent_add)
    return min(desired, current + max_add)
