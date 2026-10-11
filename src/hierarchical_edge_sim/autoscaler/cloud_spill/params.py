"""Parameters for edge-first horizontal scaling with an optional cloud cluster."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CloudSpillParams:
    """Same replica formula as the Kubernetes HPA baseline.

    ``cloud_cluster_id`` is empty when every new replica must fit on the home
    cluster. When it names a cluster, a replica that does not fit on the home
    cluster is placed there.
    """

    target_util: float = 0.80
    tolerance: float = 0.10
    min_replicas: int = 1
    max_replicas: int = 100
    scale_down_window: int = 5
    scale_up_pods: int = 4
    scale_up_percent: float = 100.0
    cloud_cluster_id: str = ""


def validate_params(raw: dict[str, Any]) -> CloudSpillParams:
    data = dict(raw)
    params = CloudSpillParams(
        target_util=float(data.pop("target_util", 0.80)),
        tolerance=float(data.pop("tolerance", 0.10)),
        min_replicas=int(data.pop("min_replicas", 1)),
        max_replicas=int(data.pop("max_replicas", 100)),
        scale_down_window=int(data.pop("scale_down_window", 5)),
        scale_up_pods=int(data.pop("scale_up_pods", 4)),
        scale_up_percent=float(data.pop("scale_up_percent", 100.0)),
        cloud_cluster_id=str(data.pop("cloud_cluster_id", "") or "").strip(),
    )
    if data:
        raise ValueError(f"unknown cloud_spill params: {sorted(data)}")
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
