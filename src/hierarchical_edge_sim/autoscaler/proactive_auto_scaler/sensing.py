"""TTW sensing + forecast for proactive_auto_scaler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.env.api import Env

from .forecast import forecast_horizon
from .history import RpsHistory
from .params import ProactiveAutoScalerParams
from .predictors.window import time_window
from .ttw_rps import counts_to_rps, is_ttw_close, ttw_index


@dataclass(frozen=True, slots=True)
class SenseCloseResult:
    ms_id: str
    ttw_t: int
    r_t: float
    r_hat: tuple[float, ...] | None
    history_full: bool
    history_len: int


@dataclass(slots=True)
class ProactiveSensing:
    params: ProactiveAutoScalerParams
    predictor: Any
    _histories: dict[str, RpsHistory] = field(default_factory=dict)
    _ttw_request_totals: dict[str, float] = field(default_factory=dict)

    def on_tick(self, env: Env, tau: int) -> list[SenseCloseResult]:
        tick_sec = float(env.world_spec.sim.tick_sec)
        ttw_len = self.params.ttw_ticks

        for ms_id in env.list_microservices():
            self._ttw_request_totals[ms_id] = self._ttw_request_totals.get(ms_id, 0.0) + _sum_lambda_in(
                env, ms_id, tau
            )

        if not is_ttw_close(tau, ttw_len):
            return []

        ttw_t = ttw_index(tau, ttw_len)
        close_time_tick = (tau - 1) + self.params.time_tick_offset
        closed: list[SenseCloseResult] = []
        for ms_id in env.list_microservices():
            n_requests = self._ttw_request_totals.get(ms_id, 0.0)
            self._ttw_request_totals[ms_id] = 0.0
            r_t = counts_to_rps(n_requests, ttw_ticks=ttw_len, tick_sec=tick_sec)
            history = self._histories.setdefault(ms_id, RpsHistory(self.params.feature_window))
            history.append(n_requests)
            forecast_rps: tuple[float, ...] | None = None
            if history.is_full():
                forecast_rps = tuple(
                    _predict(
                        self.predictor,
                        history=history,
                        horizon_h=self.params.horizon_H,
                        feature_window=self.params.feature_window,
                        ttw_ticks=ttw_len,
                        tick_sec=tick_sec,
                        close_time_tick=close_time_tick,
                    )
                )
            closed.append(
                SenseCloseResult(
                    ms_id=ms_id,
                    ttw_t=ttw_t,
                    r_t=r_t,
                    r_hat=forecast_rps,
                    history_full=history.is_full(),
                    history_len=len(history),
                )
            )
        return closed


def _predict(
    predictor: Any,
    *,
    history: RpsHistory,
    horizon_h: int,
    feature_window: int,
    ttw_ticks: int,
    tick_sec: float,
    close_time_tick: int,
) -> list[float]:
    counts = history.as_list()
    rps = history.as_rps(ttw_ticks=ttw_ticks, tick_sec=tick_sec)
    if hasattr(predictor, "predict_horizon"):
        ticks = time_window(close_time_tick, feature_window)
        return [
            float(v)
            for v in predictor.predict_horizon(rps, time_ticks=ticks, counts=counts)
        ]
    return forecast_horizon(
        rps,
        horizon_h,
        predictor,
        feature_window=feature_window,
    )


def _sum_lambda_in(env: Env, ms_id: str, tau: int) -> float:
    ms = env.get_microservice(ms_id)
    total = 0.0
    for cid in ms.container_ids:
        total += float(env.get_container(cid).history_at(tau).lambda_in)
    return total
