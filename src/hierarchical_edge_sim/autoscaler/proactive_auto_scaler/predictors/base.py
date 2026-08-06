"""Predictor protocol for one-step RPS forecasting."""

from __future__ import annotations

from typing import Protocol


class OneStepRpsPredictor(Protocol):
    def predict_next(self, x: list[float]) -> float:
        """Return next-step RPS given a history window (real RPS units)."""
        ...
