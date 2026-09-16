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
    ticks_per_window: int = 1
    feature_window: int = 10
    forecast_horizon: int = 3
    theta_up: float = 0.80
    theta_down: float = 0.30
    theta_target: float = 0.60
    sustained_steps: int = 2
    # Scale-down only. Kubernetes HPA default: scaleUp stabilization 0s,
    # scaleDown 300s. On Alibaba (1 window = 1 min) cooldown_C=5 is that 5 min.
    cooldown_C: int = 3
    predictor: str = "persistence"
    model_dir: str = "models/tcn_delta_v1"
    time_tick_offset: int = 0
    kappa_min: float = 0.5
    window_kappa: int | None = None
    ladder: ReactiveLocalParams = field(default_factory=ReactiveLocalParams)


def _pop_alias(data: dict[str, Any], new_key: str, old_key: str, default: Any) -> Any:
    """Prefer ``new_key``; still accept ``old_key`` from older YAML."""
    if new_key in data:
        data.pop(old_key, None)
        return data.pop(new_key)
    if old_key in data:
        return data.pop(old_key)
    return default


def validate_params(raw: dict[str, Any]) -> ProactiveAutoScalerParams:
    data = dict(raw)
    if "feature_window" not in data and "window_W" in data:
        data["feature_window"] = data.pop("window_W")
    else:
        data.pop("window_W", None)

    predictor = str(data.pop("predictor", "persistence"))
    if "hold_down_ticks" in data:
        raise ValueError(
            "hold_down_ticks was removed; cooldown_C delays scale-down only "
            "(Kubernetes HPA: scaleUp stabilization 0s, scaleDown 300s)"
        )
    ticks_per_window = int(_pop_alias(data, "ticks_per_window", "ttw_ticks", 1))
    forecast_horizon = int(
        _pop_alias(
            data,
            "forecast_horizon",
            "horizon_H",
            5 if predictor == "tcn_delta" else 3,
        )
    )
    sustained_steps = int(_pop_alias(data, "sustained_steps", "sustained_tau", 2))
    kappa_min = float(data.pop("kappa_min", 0.5))
    window_kappa_raw = data.pop("window_kappa", None)
    window_kappa = None if window_kappa_raw is None else int(window_kappa_raw)
    params = ProactiveAutoScalerParams(
        ticks_per_window=ticks_per_window,
        feature_window=int(data.pop("feature_window", 60 if predictor == "tcn_delta" else 10)),
        forecast_horizon=forecast_horizon,
        theta_up=float(data.pop("theta_up", 0.80)),
        theta_down=float(data.pop("theta_down", 0.30)),
        theta_target=float(data.pop("theta_target", 0.60)),
        sustained_steps=sustained_steps,
        cooldown_C=int(data.pop("cooldown_C", 5 if predictor == "tcn_delta" else 3)),
        predictor=predictor,
        model_dir=str(data.pop("model_dir", "models/tcn_delta_v1")),
        time_tick_offset=int(data.pop("time_tick_offset", 0)),
        kappa_min=kappa_min,
        window_kappa=window_kappa,
        ladder=validate_ladder_params(data),
    )
    if params.ticks_per_window < 1:
        raise ValueError("ticks_per_window must be >= 1")
    if params.feature_window < 1:
        raise ValueError("feature_window must be >= 1")
    if params.forecast_horizon < 1:
        raise ValueError("forecast_horizon must be >= 1")
    if params.sustained_steps < 1:
        raise ValueError("sustained_steps must be >= 1")
    if params.cooldown_C < 0:
        raise ValueError("cooldown_C must be >= 0")
    if not (0.0 < params.kappa_min <= 1.0):
        raise ValueError("kappa_min must be in (0, 1]")
    if params.window_kappa is not None and params.window_kappa < 1:
        raise ValueError("window_kappa must be >= 1")
    if not (0.0 < params.theta_down < params.theta_target < params.theta_up <= 1.0):
        raise ValueError("require 0 < theta_down < theta_target < theta_up <= 1")
    if params.predictor not in _PREDICTORS:
        raise ValueError(f"predictor must be one of {_PREDICTORS}")
    if params.predictor == "tcn_delta":
        if params.ticks_per_window != 1:
            raise ValueError("tcn_delta requires ticks_per_window=1 (one Alibaba minute per sample)")
        if params.feature_window != 60:
            raise ValueError("tcn_delta requires feature_window=60")
        if params.forecast_horizon != 5:
            raise ValueError("tcn_delta requires forecast_horizon=5")
    return params
