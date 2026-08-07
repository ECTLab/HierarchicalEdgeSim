"""TTW sensing + forecast logging for proactive_auto_scaler."""

from __future__ import annotations

from dataclasses import dataclass, field

from hierarchical_edge_sim.env.api import Env

from .forecast import forecast_horizon
from .history import RpsHistory
from .params import ProactiveAutoScalerParams
from .predictors.base import OneStepRpsPredictor
from .ttw_rps import counts_to_rps, is_ttw_close, ttw_index


@dataclass(frozen=True, slots=True)
class RpsForecastLogRow:
    tau: int
    ttw: int
    ms_id: str
    lead: int
    target_ttw: int
    r_t: float | None
    r_hat: float | None
    history_len: int
    forecast_ready: bool


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
    predictor: OneStepRpsPredictor
    rps_forecast_log: list[RpsForecastLogRow] = field(default_factory=list)
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
        closed: list[SenseCloseResult] = []
        for ms_id in env.list_microservices():
            n_requests = self._ttw_request_totals.get(ms_id, 0.0)
            self._ttw_request_totals[ms_id] = 0.0
            r_t = counts_to_rps(n_requests, ttw_ticks=ttw_len, tick_sec=tick_sec)
            rps_history = self._histories.setdefault(ms_id, RpsHistory(self.params.feature_window))
            rps_history.append(r_t)
            history_len = len(rps_history)

            self.rps_forecast_log.append(
                RpsForecastLogRow(
                    tau=tau,
                    ttw=ttw_t,
                    ms_id=ms_id,
                    lead=0,
                    target_ttw=ttw_t,
                    r_t=r_t,
                    r_hat=None,
                    history_len=history_len,
                    forecast_ready=False,
                )
            )

            forecast_rps: tuple[float, ...] | None = None
            if rps_history.is_full():
                rps_window = rps_history.as_list()
                if len(rps_window) != self.params.feature_window:
                    raise RuntimeError(
                        f"feature vector length {len(rps_window)} != feature_window "
                        f"{self.params.feature_window}"
                    )
                preds = forecast_horizon(
                    rps_window,
                    self.params.horizon_H,
                    self.predictor,
                    feature_window=self.params.feature_window,
                )
                forecast_rps = tuple(preds)
                for lead, r_hat in enumerate(preds, start=1):
                    self.rps_forecast_log.append(
                        RpsForecastLogRow(
                            tau=tau,
                            ttw=ttw_t,
                            ms_id=ms_id,
                            lead=lead,
                            target_ttw=ttw_t + lead,
                            r_t=None,
                            r_hat=r_hat,
                            history_len=history_len,
                            forecast_ready=True,
                        )
                    )

            closed.append(
                SenseCloseResult(
                    ms_id=ms_id,
                    ttw_t=ttw_t,
                    r_t=r_t,
                    r_hat=forecast_rps,
                    history_full=rps_history.is_full(),
                    history_len=history_len,
                )
            )
        return closed


def _sum_lambda_in(env: Env, ms_id: str, tau: int) -> float:
    ms = env.get_microservice(ms_id)
    total = 0.0
    for cid in ms.container_ids:
        total += float(env.get_container(cid).history_at(tau).lambda_in)
    return total
