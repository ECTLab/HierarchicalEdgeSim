"""Parameters for reactive_local (BEV + in-cluster BEH)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ReactiveLocalParams:
    x_up_streak: int = 3
    y_down_streak: int = 8
    cooldown_ticks: int = 5
    eps_drop: float = 1.0e-9
    theta_free: float = 0.35
    theta_high: float = 0.90
    use_near_saturation_up: bool = False
    alpha_up: float = 0.20
    alpha_down: float = 0.10
    delta_cpu_min_cores: float = 0.25
    delta_ram_min_mb: float = 128.0
    up_mode: str = "deficit"
    prefer_consolidate_down: bool = True
    grow_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)
    shrink_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)
    # Prolonged surge: skip BEV and go straight to BEH (paper Alg. BEV).
    # Default above x_up_streak so the first UP still tries vertical packing.
    sustained_up_streak: int = 6


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


def validate_params(raw: dict[str, Any]) -> ReactiveLocalParams:
    data = dict(raw)
    grow = _parse_grow_weights(data.pop("grow_weights", None))
    shrink = _parse_shrink_weights(data.pop("shrink_weights", None))

    params = ReactiveLocalParams(
        x_up_streak=int(data.pop("x_up_streak", 3)),
        y_down_streak=int(data.pop("y_down_streak", 8)),
        cooldown_ticks=int(data.pop("cooldown_ticks", 5)),
        eps_drop=float(data.pop("eps_drop", 1.0e-9)),
        theta_free=float(data.pop("theta_free", 0.35)),
        theta_high=float(data.pop("theta_high", 0.90)),
        use_near_saturation_up=bool(data.pop("use_near_saturation_up", False)),
        alpha_up=float(data.pop("alpha_up", 0.20)),
        alpha_down=float(data.pop("alpha_down", 0.10)),
        delta_cpu_min_cores=float(data.pop("delta_cpu_min_cores", 0.25)),
        delta_ram_min_mb=float(data.pop("delta_ram_min_mb", 128.0)),
        up_mode=str(data.pop("up_mode", "deficit")),
        prefer_consolidate_down=bool(data.pop("prefer_consolidate_down", True)),
        grow_weights=grow,
        shrink_weights=shrink,
        sustained_up_streak=int(data.pop("sustained_up_streak", 6)),
    )
    if data:
        raise ValueError(f"unknown reactive_local params: {sorted(data)}")
    if params.x_up_streak < 1 or params.y_down_streak < 1:
        raise ValueError("streaks must be >= 1")
    if params.sustained_up_streak < 1:
        raise ValueError("sustained_up_streak must be >= 1")
    if params.cooldown_ticks < 0:
        raise ValueError("cooldown_ticks must be >= 0")
    if not (0.0 < params.theta_free <= 1.0):
        raise ValueError("theta_free must be in (0, 1]")
    if not (0.0 < params.theta_high <= 1.0):
        raise ValueError("theta_high must be in (0, 1]")
    if params.alpha_up <= 0 or params.alpha_down <= 0:
        raise ValueError("alpha_up/alpha_down must be > 0")
    if params.up_mode not in {"deficit", "multiplicative"}:
        raise ValueError("up_mode must be 'deficit' or 'multiplicative'")
    return params
