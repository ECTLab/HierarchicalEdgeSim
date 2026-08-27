"""Fallback / test backend: next RPS equals the last observed sample."""


class PersistencePredictor:
    def __init__(self, forecast_horizon: int = 3) -> None:
        if forecast_horizon < 1:
            raise ValueError("forecast_horizon must be >= 1")
        self.forecast_horizon = forecast_horizon

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
        return [last] * self.forecast_horizon
