"""Window sensing + forecast for proactive_auto_scaler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.env.api import Env

from .confidence import CountConfidence
from .history import RpsHistory
from .params import ProactiveAutoScalerParams
from .predictors.window import time_window
from .window_rps import counts_to_rps, is_window_close, window_index


@dataclass(frozen=True, slots=True)
class SenseCloseResult:
    ms_id: str
    window_index: int
    observed_rps: float
    forecast_rps: tuple[float, ...] | None
    history_full: bool
    history_len: int
    kappa: float = 0.0
    mape: float = 0.0


@dataclass(slots=True)
class ProactiveSensing:
    params: ProactiveAutoScalerParams
    predictor: Any
    _histories: dict[str, RpsHistory] = field(default_factory=dict)
    _confidence: dict[str, CountConfidence] = field(default_factory=dict)
    _window_request_totals: dict[str, float] = field(default_factory=dict)

    def on_tick(self, env: Env, tau: int) -> list[SenseCloseResult]:
        tick_sec = float(env.world_spec.sim.tick_sec)
        window_len = self.params.ticks_per_window

        for ms_id in env.list_microservices():
            self._window_request_totals[ms_id] = self._window_request_totals.get(ms_id, 0.0) + _sum_lambda_in(
                env, ms_id, tau
            )

        if not is_window_close(tau, window_len):
            return []

        closed_index = window_index(tau, window_len)
        close_time_tick = (tau - 1) + self.params.time_tick_offset
        closed: list[SenseCloseResult] = []
        for ms_id in env.list_microservices():
            n_requests = self._window_request_totals.get(ms_id, 0.0)
            self._window_request_totals[ms_id] = 0.0
            observed_rps = counts_to_rps(
                n_requests, ticks_per_window=window_len, tick_sec=tick_sec
            )
            history = self._histories.setdefault(ms_id, RpsHistory(self.params.feature_window))
            history.append(n_requests)
            predicted: tuple[float, ...] | None = None
            if history.is_full():
                predicted = tuple(
                    _predict(
                        self.predictor,
                        ms_id=ms_id,
                        history=history,
                        steps=self.params.forecast_horizon,
                        feature_window=self.params.feature_window,
                        ticks_per_window=window_len,
                        tick_sec=tick_sec,
                        close_time_tick=close_time_tick,
                    )
                )
            w_kappa = self.params.window_kappa or self.params.feature_window
            tracker = self._confidence.setdefault(ms_id, CountConfidence(w_kappa))
            next_count = None
            if predicted:
                next_count = predicted[0] * window_len * tick_sec
            kappa = tracker.observe(n_requests, next_count)
            closed.append(
                SenseCloseResult(
                    ms_id=ms_id,
                    window_index=closed_index,
                    observed_rps=observed_rps,
                    forecast_rps=predicted,
                    history_full=history.is_full(),
                    history_len=len(history),
                    kappa=kappa,
                    mape=tracker.mape(),
                )
            )
        return closed


def _predict(
    predictor: Any,
    *,
    ms_id: str,
    history: RpsHistory,
    steps: int,
    feature_window: int,
    ticks_per_window: int,
    tick_sec: float,
    close_time_tick: int,
) -> list[float]:
    counts = history.as_list()
    rps = history.as_rps(ticks_per_window=ticks_per_window, tick_sec=tick_sec)
    if hasattr(predictor, "predictor_for"):
        predictor = predictor.predictor_for(ms_id)
    if hasattr(predictor, "predict_horizon"):
        ticks = time_window(close_time_tick, feature_window)
        return [
            float(v)
            for v in predictor.predict_horizon(rps, time_ticks=ticks, counts=counts)
        ]
    from .forecast import forecast_horizon as roll_horizon

    return roll_horizon(
        rps,
        steps,
        predictor,
        feature_window=feature_window,
    )


def _sum_lambda_in(env: Env, ms_id: str, tau: int) -> float:
    ms = env.get_microservice(ms_id)
    total = 0.0
    for cid in ms.container_ids:
        total += float(env.get_container(cid).history_at(tau).lambda_in)
    return total
