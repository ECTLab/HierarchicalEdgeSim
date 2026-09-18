"""Parameters for reactive_vertical."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ReactiveVerticalParams:
    x_up_streak: int = 3
    y_down_streak: int = 8
    cooldown_ticks: int = 5
    eps_drop: float = 1.0e-9
    theta_free: float = 0.35
    theta_high: float = 0.90
    use_near_saturation_up: bool = False
    min_mu_step: float = 25.0
    prefer_consolidate_down: bool = True
    grow_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)
    shrink_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)


def _parse_grow_weights(val: Any) -> tuple[float, float, float]:
    if val is None:
        return (0.5, 0.3, 0.2)
    if isinstance(val, dict):
        return (float(val["drop"]), float(val["util"]), float(val["room"]))
    if isinstance(val, (list, tuple)) and len(val) == 3:
        return (float(val[0]), float(val[1]), float(val[2]))
    raise ValueError("grow_weights must be {drop,util,room} or a 3-tuple")


def _parse_shrink_weights(val: Any) -> tuple[float, float, float]:
    if val is None:
        return (0.5, 0.3, 0.2)
    if isinstance(val, dict):
        return (float(val["slack"]), float(val["no_drop"]), float(val["room"]))
    if isinstance(val, (list, tuple)) and len(val) == 3:
        return (float(val[0]), float(val[1]), float(val[2]))
    raise ValueError("shrink_weights must be {slack,no_drop,room} or a 3-tuple")


def validate_params(raw: dict[str, Any]) -> ReactiveVerticalParams:
    data = dict(raw)
    if "alpha_up" in data or "alpha_down" in data:
        raise ValueError(
            "alpha_up/alpha_down were removed; AllocateResources applies the full residual"
        )
    if "delta_cpu_min_cores" in data or "delta_ram_min_mb" in data:
        raise ValueError(
            "delta_cpu_min_cores/delta_ram_min_mb were removed; use min_mu_step "
            "(req/tick). RAM follows μ×ρ. Floor extras terminate because they add no μ"
        )
    grow = _parse_grow_weights(data.pop("grow_weights", None))
    shrink = _parse_shrink_weights(data.pop("shrink_weights", None))

    params = ReactiveVerticalParams(
        x_up_streak=int(data.pop("x_up_streak", 3)),
        y_down_streak=int(data.pop("y_down_streak", 8)),
        cooldown_ticks=int(data.pop("cooldown_ticks", 5)),
        eps_drop=float(data.pop("eps_drop", 1.0e-9)),
        theta_free=float(data.pop("theta_free", 0.35)),
        theta_high=float(data.pop("theta_high", 0.90)),
        use_near_saturation_up=bool(data.pop("use_near_saturation_up", False)),
        min_mu_step=float(data.pop("min_mu_step", 25.0)),
        prefer_consolidate_down=bool(data.pop("prefer_consolidate_down", True)),
        grow_weights=grow,
        shrink_weights=shrink,
    )
    if data:
        raise ValueError(f"unknown reactive_vertical params: {sorted(data)}")
    if params.x_up_streak < 1 or params.y_down_streak < 1:
        raise ValueError("streaks must be >= 1")
    if params.cooldown_ticks < 0:
        raise ValueError("cooldown_ticks must be >= 0")
    if not (0.0 < params.theta_free <= 1.0):
        raise ValueError("theta_free must be in (0, 1]")
    if not (0.0 < params.theta_high <= 1.0):
        raise ValueError("theta_high must be in (0, 1]")
    if params.min_mu_step < 0.0:
        raise ValueError("min_mu_step must be >= 0")
    return params
