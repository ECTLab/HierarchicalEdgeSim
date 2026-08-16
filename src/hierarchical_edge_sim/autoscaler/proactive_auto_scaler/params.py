"""Parameters for proactive_auto_scaler (forecast + decide + shared ladder)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.autoscaler.reactive_local.params import (
    ReactiveLocalParams,
    validate_params as validate_ladder_params,
)

_PREDICTORS = ("persistence", "tcn_delta")


@dataclass(frozen=True, slots=True)
class ProactiveAutoScalerParams:
    ttw_ticks: int = 1
    feature_window: int = 10
    horizon_H: int = 3
    theta_up: float = 0.80
    theta_down: float = 0.30
    theta_target: float = 0.60
    sustained_tau: int = 2
    cooldown_C: int = 3
    predictor: str = "persistence"
    model_dir: str = "models/tcn_delta_v1"
    time_tick_offset: int = 0
    ladder: ReactiveLocalParams = field(default_factory=ReactiveLocalParams)


def validate_params(raw: dict[str, Any]) -> ProactiveAutoScalerParams:
    data = dict(raw)
    if "feature_window" not in data and "window_W" in data:
        data["feature_window"] = data.pop("window_W")
    else:
        data.pop("window_W", None)

    predictor = str(data.pop("predictor", "persistence"))
    params = ProactiveAutoScalerParams(
        ttw_ticks=int(data.pop("ttw_ticks", 1)),
        feature_window=int(data.pop("feature_window", 60 if predictor == "tcn_delta" else 10)),
        horizon_H=int(data.pop("horizon_H", 5 if predictor == "tcn_delta" else 3)),
        theta_up=float(data.pop("theta_up", 0.80)),
        theta_down=float(data.pop("theta_down", 0.30)),
        theta_target=float(data.pop("theta_target", 0.60)),
        sustained_tau=int(data.pop("sustained_tau", 2)),
        cooldown_C=int(data.pop("cooldown_C", 5 if predictor == "tcn_delta" else 3)),
        predictor=predictor,
        model_dir=str(data.pop("model_dir", "models/tcn_delta_v1")),
        time_tick_offset=int(data.pop("time_tick_offset", 0)),
        ladder=validate_ladder_params(data),
    )
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
    if params.predictor not in _PREDICTORS:
        raise ValueError(f"predictor must be one of {_PREDICTORS}")
    if params.predictor == "tcn_delta":
        if params.ttw_ticks != 1:
            raise ValueError("tcn_delta requires ttw_ticks=1 (one Alibaba minute per sample)")
        if params.feature_window != 60:
            raise ValueError("tcn_delta requires feature_window=60")
        if params.horizon_H != 5:
            raise ValueError("tcn_delta requires horizon_H=5")
    return params
