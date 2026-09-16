"""Confidence κ = 1/(1+MAPE) on request counts (paper Eq. confidence)."""

from __future__ import annotations

from collections import deque


def mape_on_counts(predicted: float, actual: float, *, eps: float = 1.0) -> float:
    """Absolute percentage error on a request count. Floor the denom so a zero window cannot explode."""
    denom = max(abs(float(actual)), eps)
    return abs(float(predicted) - float(actual)) / denom


def kappa_from_mape(mape: float) -> float:
    return 1.0 / (1.0 + max(0.0, float(mape)))


class CountConfidence:
    """Trailing MAPE of one-step request-count forecasts vs realized counts."""

    def __init__(self, window: int) -> None:
        if window < 1:
            raise ValueError("window must be >= 1")
        self.window = window
        self._pending: float | None = None
        self._errors: deque[float] = deque(maxlen=window)
        self._windows = 0

    def observe(self, actual_count: float, next_step_forecast_count: float | None) -> float:
        """Consume the last forecast, record APE, publish the next-step forecast. Return κ."""
        self._windows += 1
        if self._pending is not None:
            self._errors.append(mape_on_counts(self._pending, actual_count))
        self._pending = None if next_step_forecast_count is None else float(next_step_forecast_count)
        return self.kappa()

    def kappa(self) -> float:
        if self._windows < self.window:
            return 0.0
        if not self._errors:
            return 1.0
        mape = sum(self._errors) / len(self._errors)
        return kappa_from_mape(mape)

    def mape(self) -> float:
        if not self._errors:
            return 0.0
        return sum(self._errors) / len(self._errors)
