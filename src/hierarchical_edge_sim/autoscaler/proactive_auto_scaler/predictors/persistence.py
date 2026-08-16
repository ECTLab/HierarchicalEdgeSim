"""Fallback / test backend: next RPS equals the last observed sample."""


class PersistencePredictor:
    def __init__(self, horizon_h: int = 3) -> None:
        if horizon_h < 1:
            raise ValueError("horizon_h must be >= 1")
        self.horizon_h = horizon_h

    def predict_next(self, x: list[float]) -> float:
        if not x:
            raise ValueError("persistence predictor needs a non-empty window")
        return float(x[-1])

    def predict_horizon(
        self,
        history_rps: list[float],
        *,
        time_ticks: list[int] | None = None,
        counts: list[float] | None = None,
    ) -> list[float]:
        _ = time_ticks, counts
        last = self.predict_next(history_rps)
        return [last] * self.horizon_h
