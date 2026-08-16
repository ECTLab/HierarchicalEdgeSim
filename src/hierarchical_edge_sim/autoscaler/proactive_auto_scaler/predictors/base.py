"""Predictor protocols. Option A is a one-shot horizon; Option B is one-step + roll."""

from __future__ import annotations

from typing import Protocol


class OneStepRpsPredictor(Protocol):
    def predict_next(self, x: list[float]) -> float:
        """Return next-step RPS given a history window (real RPS units)."""
        ...


class HorizonRpsPredictor(Protocol):
    def predict_horizon(
        self,
        history_rps: list[float],
        *,
        time_ticks: list[int] | None = None,
        counts: list[float] | None = None,
    ) -> list[float]:
        """Return H future RPS values from a full feature window."""
        ...
