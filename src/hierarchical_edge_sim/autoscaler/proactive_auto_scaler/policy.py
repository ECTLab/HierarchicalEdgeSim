"""Proactive autoscaler: sense/forecast → decide → allocate."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.autoscaler.common.snapshot import snapshot_ms
from hierarchical_edge_sim.env.api import Env

from .allocate import allocate_vertical
from .decide import Direction, predict_and_decide
from .params import ProactiveAutoScalerParams, validate_params
from .predictors.base import OneStepRpsPredictor
from .sensing import ProactiveSensing, RpsForecastLogRow  # re-exported for callers


@dataclass(slots=True)
class ProactiveAutoScaler:
    name: str = "proactive_auto_scaler"
    params: ProactiveAutoScalerParams = field(default_factory=ProactiveAutoScalerParams)
    decision_every_k_ticks: int = 1  # unused; TTW gate is ttw_ticks
    rps_forecast_log: list[RpsForecastLogRow] = field(default_factory=list)
    _predictor: OneStepRpsPredictor = field(default_factory=lambda: _make_predictor(ProactiveAutoScalerParams()))
    _sensing: ProactiveSensing | None = None
    _next_allowed_ttw: dict[str, int] = field(default_factory=dict)
    _pending_proactive_ttw: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self._sensing is None:
            self._sensing = ProactiveSensing(
                params=self.params,
                predictor=self._predictor,
                rps_forecast_log=self.rps_forecast_log,
            )

    def on_tick_end(self, env: Env, tau: int) -> list[Any]:
        assert self._sensing is not None
        closed = self._sensing.on_tick(env, tau)
        if not closed:
            return []

        actions: list[Any] = []
        self._pending_proactive_ttw.clear()

        for rec in closed:
            if not rec.history_full or rec.r_hat is None:
                continue
            if self._in_cooldown(rec.ms_id, rec.ttw_t):
                continue

            snap = snapshot_ms(env, rec.ms_id, tau)
            decision = predict_and_decide(
                r_t=rec.r_t,
                r_hat=rec.r_hat,
                A_cpu=snap.A_cpu,
                A_ram=snap.A_ram,
                rho_cpu=snap.rho_cpu,
                rho_ram=snap.rho_ram,
                tick_sec=snap.tick_sec,
                u_meas=snap.u_meas,
                theta_up=self.params.theta_up,
                theta_down=self.params.theta_down,
                theta_target=self.params.theta_target,
                sustained_tau=self.params.sustained_tau,
                cpu_min_cores=snap.spec.cpu_min_cores,
                ram_min_mb=snap.spec.ram_min_mb,
            )
            if decision.direction is Direction.NONE:
                continue

            ms_actions = allocate_vertical(
                env,
                snap=snap,
                tau=tau,
                decision=decision,
                params=self.params.distribute,
            )
            if any(getattr(a, "type", "") == "resize" for a in ms_actions):
                self._pending_proactive_ttw[rec.ms_id] = rec.ttw_t
            actions.extend(ms_actions)
        return actions

    def on_actions_applied(self, results: list[Any]) -> None:
        if any(getattr(r, "ok", False) for r in results):
            for ms_id, ttw_t in self._pending_proactive_ttw.items():
                self._next_allowed_ttw[ms_id] = ttw_t + self.params.cooldown_C + 1
        self._pending_proactive_ttw.clear()

    def _in_cooldown(self, ms_id: str, ttw_t: int) -> bool:
        return ttw_t < self._next_allowed_ttw.get(ms_id, 0)


def build(params: dict, decision_every_k_ticks: int = 1) -> ProactiveAutoScaler:
    _ = decision_every_k_ticks
    validated = validate_params(params)
    predictor = _make_predictor(validated)
    log: list[RpsForecastLogRow] = []
    sensing = ProactiveSensing(params=validated, predictor=predictor, rps_forecast_log=log)
    return ProactiveAutoScaler(
        params=validated,
        rps_forecast_log=log,
        _predictor=predictor,
        _sensing=sensing,
    )


def _make_predictor(params: ProactiveAutoScalerParams) -> OneStepRpsPredictor:
    from .predictors.lstm_torch import build_lstm_predictor

    return build_lstm_predictor(
        feature_window=params.feature_window,
        model_path=params.model_path,
        scaler_path=params.scaler_path,
        meta_path=params.meta_path,
    )
