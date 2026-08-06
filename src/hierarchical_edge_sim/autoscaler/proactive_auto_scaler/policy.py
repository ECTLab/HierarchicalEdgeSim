"""Proactive autoscaler: TTW RPS + one-step forecast + long log (no actions yet)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.env.api import Env

from .forecast import forecast_horizon
from .history import RpsHistory
from .params import ProactiveAutoScalerParams, validate_params
from .predictors.average import AveragePredictor
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


@dataclass(slots=True)
class ProactiveAutoScaler:
    name: str = "proactive_auto_scaler"
    params: ProactiveAutoScalerParams = field(default_factory=ProactiveAutoScalerParams)
    decision_every_k_ticks: int = 1  # unused; TTW gate is ttw_ticks
    rps_forecast_log: list[RpsForecastLogRow] = field(default_factory=list)
    _histories: dict[str, RpsHistory] = field(default_factory=dict)
    _bucket_n: dict[str, float] = field(default_factory=dict)
    _predictor: OneStepRpsPredictor = field(default_factory=AveragePredictor)

    def on_tick_end(self, env: Env, tau: int) -> list[Any]:
        tick_sec = float(env.world_spec.sim.tick_sec)
        L = self.params.ttw_ticks

        for ms_id in env.list_microservices():
            self._bucket_n[ms_id] = self._bucket_n.get(ms_id, 0.0) + _sum_lambda_in(env, ms_id, tau)

        if not is_ttw_close(tau, L):
            return []

        t = ttw_index(tau, L)
        for ms_id in env.list_microservices():
            n = self._bucket_n.get(ms_id, 0.0)
            self._bucket_n[ms_id] = 0.0
            r_t = counts_to_rps(n, ttw_ticks=L, tick_sec=tick_sec)
            hist = self._histories.setdefault(ms_id, RpsHistory(self.params.feature_window))
            hist.append(r_t)
            history_len = len(hist)

            self.rps_forecast_log.append(
                RpsForecastLogRow(
                    tau=tau,
                    ttw=t,
                    ms_id=ms_id,
                    lead=0,
                    target_ttw=t,
                    r_t=r_t,
                    r_hat=None,
                    history_len=history_len,
                    forecast_ready=False,
                )
            )

            if hist.is_full():
                features = hist.as_list()
                if len(features) != self.params.feature_window:
                    raise RuntimeError(
                        f"feature vector length {len(features)} != feature_window "
                        f"{self.params.feature_window}"
                    )
                preds = forecast_horizon(
                    features,
                    self.params.horizon_H,
                    self._predictor,
                    feature_window=self.params.feature_window,
                )
                for h, r_hat in enumerate(preds, start=1):
                    self.rps_forecast_log.append(
                        RpsForecastLogRow(
                            tau=tau,
                            ttw=t,
                            ms_id=ms_id,
                            lead=h,
                            target_ttw=t + h,
                            r_t=None,
                            r_hat=r_hat,
                            history_len=history_len,
                            forecast_ready=True,
                        )
                    )
        return []

    def on_actions_applied(self, results: list[Any]) -> None:
        # No actions emitted yet; hook kept for protocol compatibility.
        return None


def build(params: dict, decision_every_k_ticks: int = 1) -> ProactiveAutoScaler:
    # decision_every_k_ticks is ignored; aggregation/decision period is ttw_ticks.
    _ = decision_every_k_ticks
    validated = validate_params(params)
    return ProactiveAutoScaler(params=validated, _predictor=_make_predictor(validated))


def _make_predictor(params: ProactiveAutoScalerParams) -> OneStepRpsPredictor:
    if params.predictor == "average":
        return AveragePredictor()
    if params.predictor == "lstm":
        from .predictors.lstm_torch import build_lstm_predictor

        return build_lstm_predictor(
            feature_window=params.feature_window,
            model_path=params.model_path,
            scaler_path=params.scaler_path,
            meta_path=params.meta_path,
        )
    raise ValueError(f"unsupported predictor: {params.predictor}")


def _sum_lambda_in(env: Env, ms_id: str, tau: int) -> float:
    ms = env.get_microservice(ms_id)
    total = 0.0
    for cid in ms.container_ids:
        total += float(env.get_container(cid).history_at(tau).lambda_in)
    return total
