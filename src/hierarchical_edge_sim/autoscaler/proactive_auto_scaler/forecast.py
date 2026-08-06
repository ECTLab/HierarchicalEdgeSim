"""Recursive multi-horizon forecast on a scratch copy of history."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .predictors.base import OneStepRpsPredictor


def forecast_horizon(
    x: list[float],
    horizon_h: int,
    predictor: OneStepRpsPredictor,
    *,
    feature_window: int | None = None,
) -> list[float]:
    """Return H predictions; never mutates ``x``.

    If ``feature_window`` is set, requires ``len(x) == feature_window``.
    """
    if horizon_h < 1:
        raise ValueError("horizon_h must be >= 1")
    if not x:
        raise ValueError("feature window must be non-empty")
    if feature_window is not None and len(x) != feature_window:
        raise ValueError(
            f"expected feature_window={feature_window} samples, got len(x)={len(x)}"
        )
    z = list(x)
    preds: list[float] = []
    for _ in range(horizon_h):
        y = float(predictor.predict_next(z))
        preds.append(y)
        z = z[1:] + [y]
    return preds
