"""Parameters for proactive_auto_scaler (RPS forecast; average or LSTM)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ProactiveAutoScalerParams:
    ttw_ticks: int = 1
    feature_window: int = 30
    horizon_H: int = 3
    predictor: str = "average"  # average | lstm
    model_path: str | None = None
    scaler_path: str | None = None
    meta_path: str | None = None


def validate_params(raw: dict[str, Any]) -> ProactiveAutoScalerParams:
    data = dict(raw)
    # Accept legacy alias from early drafts.
    if "feature_window" not in data and "window_W" in data:
        data["feature_window"] = data.pop("window_W")
    else:
        data.pop("window_W", None)

    predictor = str(data.pop("predictor", "average")).strip().lower()
    model_path = data.pop("model_path", None)
    scaler_path = data.pop("scaler_path", None)
    meta_path = data.pop("meta_path", None)

    params = ProactiveAutoScalerParams(
        ttw_ticks=int(data.pop("ttw_ticks", 1)),
        feature_window=int(data.pop("feature_window", 30)),
        horizon_H=int(data.pop("horizon_H", 3)),
        predictor=predictor,
        model_path=None if model_path in (None, "") else str(model_path),
        scaler_path=None if scaler_path in (None, "") else str(scaler_path),
        meta_path=None if meta_path in (None, "") else str(meta_path),
    )
    if data:
        raise ValueError(f"unknown proactive_auto_scaler params: {sorted(data)}")
    if params.ttw_ticks < 1:
        raise ValueError("ttw_ticks must be >= 1")
    if params.feature_window < 1:
        raise ValueError("feature_window must be >= 1")
    if params.horizon_H < 1:
        raise ValueError("horizon_H must be >= 1")
    if params.predictor not in {"average", "lstm"}:
        raise ValueError("predictor must be 'average' or 'lstm'")
    if params.predictor != "lstm" and (
        params.model_path or params.scaler_path or params.meta_path
    ):
        raise ValueError("model_path/scaler_path/meta_path are only valid with predictor=lstm")
    return params
