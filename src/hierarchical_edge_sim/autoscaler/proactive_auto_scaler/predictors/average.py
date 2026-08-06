"""Simple averaging one-step RPS predictor."""

from __future__ import annotations


class AveragePredictor:
    """predict_next(x) = arithmetic mean of the feature window ``x``.

    ``x`` is the sliding lookback of length ``feature_window`` (past RPS samples).
    """

    def predict_next(self, x: list[float]) -> float:
        if not x:
            raise ValueError("feature window must be non-empty")
        return sum(x) / len(x)
