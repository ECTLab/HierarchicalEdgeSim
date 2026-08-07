"""Parameters for proactive_auto_scaler (forecast + decide + distribute)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.autoscaler.common.distribute import (
    DistributeParams,
    validate_distribute_params,
)


@dataclass(frozen=True, slots=True)
class ProactiveAutoScalerParams:
    ttw_ticks: int = 60
    feature_window: int = 10
    horizon_H: int = 3
    model_path: str | None = None
    scaler_path: str | None = None
    meta_path: str | None = None
    theta_up: float = 0.80
    theta_down: float = 0.30
    theta_target: float = 0.60
    sustained_tau: int = 2
    cooldown_C: int = 3
    distribute: DistributeParams = field(default_factory=DistributeParams)


def validate_params(raw: dict[str, Any]) -> ProactiveAutoScalerParams:
    data = dict(raw)
    if "feature_window" not in data and "window_W" in data:
        data["feature_window"] = data.pop("window_W")
    else:
        data.pop("window_W", None)

    model_path = data.pop("model_path", None)
    scaler_path = data.pop("scaler_path", None)
    meta_path = data.pop("meta_path", None)
    distribute_raw = data.pop("distribute", None)
    if distribute_raw is None:
        distribute = DistributeParams()
    elif isinstance(distribute_raw, dict):
        distribute = validate_distribute_params(distribute_raw)
    else:
        raise ValueError("distribute must be a mapping if provided")

    params = ProactiveAutoScalerParams(
        ttw_ticks=int(data.pop("ttw_ticks", 60)),
        feature_window=int(data.pop("feature_window", 10)),
        horizon_H=int(data.pop("horizon_H", 3)),
        model_path=None if model_path in (None, "") else str(model_path),
        scaler_path=None if scaler_path in (None, "") else str(scaler_path),
        meta_path=None if meta_path in (None, "") else str(meta_path),
        theta_up=float(data.pop("theta_up", 0.80)),
        theta_down=float(data.pop("theta_down", 0.30)),
        theta_target=float(data.pop("theta_target", 0.60)),
        sustained_tau=int(data.pop("sustained_tau", 2)),
        cooldown_C=int(data.pop("cooldown_C", 3)),
        distribute=distribute,
    )
    if data:
        raise ValueError(f"unknown proactive_auto_scaler params: {sorted(data)}")
    if params.ttw_ticks < 1:
        raise ValueError("ttw_ticks must be >= 1")
    if params.feature_window < 1:
        raise ValueError("feature_window must be >= 1")
    if params.horizon_H < 1:
        raise ValueError("horizon_H must be >= 1")
    if params.sustained_tau < 1:
        raise ValueError("sustained_tau must be >= 1")
    if params.cooldown_C < 0:
        raise ValueError("cooldown_C must be >= 0")
    if not (0.0 < params.theta_down < params.theta_target < params.theta_up <= 1.0):
        raise ValueError("require 0 < theta_down < theta_target < theta_up <= 1")
    return params
