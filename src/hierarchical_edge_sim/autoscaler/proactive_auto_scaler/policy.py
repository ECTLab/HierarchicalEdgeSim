"""Proactive front-end: sense/forecast → PredictAndDecide → shared allocate ladder."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.config import EPS

from hierarchical_edge_sim.autoscaler.reactive_local.allocate import (
    aggregate_ms,
    down_delta,
    ladder_down,
    ladder_up,
    reactive_pressure,
    resolve_help,
    up_delta,
)
from hierarchical_edge_sim.autoscaler.reactive_local.help import HelpRequest

from .decide import Direction, predict_and_decide
from .params import ProactiveAutoScalerParams, validate_params
from .predictors.base import HorizonRpsPredictor, OneStepRpsPredictor
from .predictors.persistence import PersistencePredictor
from .sensing import ProactiveSensing


@dataclass(slots=True)
class _MsState:
    u_streak: int = 0
    d_streak: int = 0
    cooldown: int = 0


@dataclass(slots=True)
class ProactiveAutoScaler:
    name: str = "proactive_auto_scaler"
    params: ProactiveAutoScalerParams = field(default_factory=ProactiveAutoScalerParams)
    decision_every_k_ticks: int = 1
    _predictor: OneStepRpsPredictor | HorizonRpsPredictor = field(default_factory=PersistencePredictor)
    _sensing: ProactiveSensing | None = None
    _state: dict[str, _MsState] = field(default_factory=dict)
    _next_down_ttw: dict[str, int] = field(default_factory=dict)
    _pending_ms: set[str] = field(default_factory=set)
    _pending_proactive_ttw: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self._sensing is None:
            self._sensing = ProactiveSensing(params=self.params, predictor=self._predictor)

    def on_tick_end(self, env: Env, tau: int) -> list[Any]:
        assert self._sensing is not None
        closed = {rec.ms_id: rec for rec in self._sensing.on_tick(env, tau)}
        actions: list[Any] = []
        help_q: list[HelpRequest] = []
        seq = 0
        self._pending_ms.clear()
        self._pending_proactive_ttw.clear()
        ladder = self.params.ladder

        for ms_id in env.list_microservices():
            st = self._state.setdefault(ms_id, _MsState())
            if st.cooldown > 0:
                st.cooldown -= 1
            obs = aggregate_ms(env, ms_id, tau)
            u_pressure, d_pressure = reactive_pressure(obs, ladder)
            st.u_streak = st.u_streak + 1 if u_pressure else 0
            st.d_streak = st.d_streak + 1 if d_pressure else 0

            rec = closed.get(ms_id)
            if rec is None:
                continue

            if rec.history_full and rec.r_hat is not None:
                spec = obs["spec"]
                decision = predict_and_decide(
                    r_t=rec.r_t,
                    r_hat=rec.r_hat,
                    A_cpu=obs["sum_cpu_alloc"],
                    A_ram=obs["sum_ram_alloc"],
                    rho_cpu=spec.cpu_per_request_cores,
                    rho_ram=spec.ram_per_request_mb,
                    tick_sec=float(env.world_spec.sim.tick_sec),
                    u_meas=obs["q_ms"],
                    theta_up=self.params.theta_up,
                    theta_down=self.params.theta_down,
                    theta_target=self.params.theta_target,
                    sustained_tau=self.params.sustained_tau,
                    cpu_min_cores=spec.cpu_min_cores,
                    ram_min_mb=spec.ram_min_mb,
                    n_replicas=max(1, len(obs["replicas"])),
                    H_cpu=obs["sum_h_cpu"],
                    H_ram=obs.get("sum_h_ram", 0.0),
                )
                # cooldown_C is scale-down only (K8s HPA: scaleUp window 0).
                down_in_cd = rec.ttw_t < self._next_down_ttw.get(ms_id, 0)
                if decision.direction is Direction.UP:
                    if decision.delta_cpu <= EPS and decision.delta_ram <= EPS:
                        continue
                    need_cpu, need_ram = _clip_step(
                        decision.delta_cpu, decision.delta_ram, obs, ladder, up=True
                    )
                    ms_actions, leftover = ladder_up(
                        env,
                        ms_id,
                        tau,
                        obs,
                        ladder,
                        need_cpu=need_cpu,
                        need_ram=need_ram,
                        sustained=decision.sustained,
                    )
                    actions.extend(ms_actions)
                    if leftover is not None:
                        leftover.seq = seq
                        help_q.append(leftover)
                        seq += 1
                    if ms_actions or leftover is not None:
                        self._pending_proactive_ttw[ms_id] = rec.ttw_t
                elif decision.direction is Direction.DOWN:
                    if down_in_cd:
                        continue
                    d_cpu, d_ram = abs(decision.delta_cpu), abs(decision.delta_ram)
                    if d_cpu <= EPS and d_ram <= EPS:
                        continue
                    d_cpu, d_ram = _clip_step(d_cpu, d_ram, obs, ladder, up=False)
                    down_actions = ladder_down(
                        env,
                        ms_id,
                        tau,
                        obs,
                        ladder,
                        delta_cpu=d_cpu,
                        delta_ram=d_ram,
                        protect_last_serving=True,
                    )
                    actions.extend(down_actions)
                    if down_actions:
                        self._pending_proactive_ttw[ms_id] = rec.ttw_t
                continue

            # Cold start: history not full → reactive-only on this TTW close.
            if st.cooldown > 0:
                continue
            if st.u_streak >= ladder.x_up_streak:
                need_cpu, need_ram = up_delta(obs, ladder)
                ms_actions, leftover = ladder_up(
                    env,
                    ms_id,
                    tau,
                    obs,
                    ladder,
                    need_cpu=need_cpu,
                    need_ram=need_ram,
                    sustained=st.u_streak >= ladder.sustained_up_streak,
                )
                actions.extend(ms_actions)
                if leftover is not None:
                    leftover.seq = seq
                    help_q.append(leftover)
                    seq += 1
            elif st.d_streak >= ladder.y_down_streak:
                d_cpu, d_ram = down_delta(obs, ladder)
                actions.extend(
                    ladder_down(
                        env,
                        ms_id,
                        tau,
                        obs,
                        ladder,
                        delta_cpu=d_cpu,
                        delta_ram=d_ram,
                        protect_last_serving=True,
                    )
                )

        actions.extend(resolve_help(env, help_q, actions, tau))
        self._pending_ms = {
            getattr(a, "ms_id", "")
            for a in actions
            if getattr(a, "type", "") in {"resize", "spawn", "terminate"} and getattr(a, "ms_id", "")
        }
        return actions

    def on_actions_applied(self, results: list[Any]) -> None:
        if any(getattr(r, "ok", False) for r in results):
            for ms_id in self._pending_ms:
                st = self._state.setdefault(ms_id, _MsState())
                st.u_streak = 0
                st.d_streak = 0
                st.cooldown = self.params.ladder.cooldown_ticks
            for ms_id, ttw_t in self._pending_proactive_ttw.items():
                self._next_down_ttw[ms_id] = ttw_t + self.params.cooldown_C + 1
        self._pending_ms.clear()
        self._pending_proactive_ttw.clear()


def _clip_step(
    need_cpu: float,
    need_ram: float,
    obs: dict,
    ladder,
    *,
    up: bool,
) -> tuple[float, float]:
    """Keep TCN's direction; apply at most one reactive-sized step per decision."""
    if up:
        cap_cpu = max(ladder.delta_cpu_min_cores, ladder.alpha_up * max(obs["sum_cpu_alloc"], EPS))
        cap_ram = max(ladder.delta_ram_min_mb, ladder.alpha_up * max(obs["sum_ram_alloc"], EPS))
    else:
        cap_cpu, cap_ram = down_delta(obs, ladder)
    return min(need_cpu, cap_cpu), min(need_ram, cap_ram)


def _default_predictor(params: ProactiveAutoScalerParams) -> OneStepRpsPredictor | HorizonRpsPredictor:
    if params.predictor == "tcn_delta":
        from .predictors.tcn import TcnDeltaPredictor

        return TcnDeltaPredictor.from_model_dir(params.model_dir)
    return PersistencePredictor(horizon_h=params.horizon_H)


def build(
    params: dict,
    decision_every_k_ticks: int = 1,
    *,
    predictor: OneStepRpsPredictor | HorizonRpsPredictor | None = None,
) -> ProactiveAutoScaler:
    _ = decision_every_k_ticks
    validated = validate_params(params)
    pred = predictor if predictor is not None else _default_predictor(validated)
    sensing = ProactiveSensing(params=validated, predictor=pred)
    return ProactiveAutoScaler(
        params=validated,
        _predictor=pred,
        _sensing=sensing,
    )
