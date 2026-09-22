"""Parameters for the Kubernetes HPA replica-count baseline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class KubernetesHpaParams:
    # CPU usage/request target. me-kube reported 50% and 80%; campaign 12 uses 0.80
    # to match the ladder's prefer-local bar.
    target_util: float = 0.80
    # Kubernetes HPA default: |current/target - 1| <= 0.1 → hold.
    tolerance: float = 0.10
    min_replicas: int = 1
    max_replicas: int = 100
    # Scale-down stabilization (HPA default 300s). Campaign ticks are 60s → 5.
    scale_down_window: int = 5
    # HPA v2 scale-up selectPolicy Max: +4 pods or +100% per period.
    scale_up_pods: int = 4
    scale_up_percent: float = 100.0


def validate_params(raw: dict[str, Any]) -> KubernetesHpaParams:
    data = dict(raw)
    params = KubernetesHpaParams(
        target_util=float(data.pop("target_util", 0.80)),
        tolerance=float(data.pop("tolerance", 0.10)),
        min_replicas=int(data.pop("min_replicas", 1)),
        max_replicas=int(data.pop("max_replicas", 100)),
        scale_down_window=int(data.pop("scale_down_window", 5)),
        scale_up_pods=int(data.pop("scale_up_pods", 4)),
        scale_up_percent=float(data.pop("scale_up_percent", 100.0)),
    )
    if data:
        raise ValueError(f"unknown kubernetes_hpa params: {sorted(data)}")
    if not (0.0 < params.target_util <= 1.0):
        raise ValueError("target_util must be in (0, 1]")
    if not (0.0 <= params.tolerance < 1.0):
        raise ValueError("tolerance must be in [0, 1)")
    if params.min_replicas < 1:
        raise ValueError("min_replicas must be >= 1")
    if params.max_replicas < params.min_replicas:
        raise ValueError("max_replicas must be >= min_replicas")
    if params.scale_down_window < 1:
        raise ValueError("scale_down_window must be >= 1")
    if params.scale_up_pods < 1:
        raise ValueError("scale_up_pods must be >= 1")
    if params.scale_up_percent < 0.0:
        raise ValueError("scale_up_percent must be >= 0")
    return params
