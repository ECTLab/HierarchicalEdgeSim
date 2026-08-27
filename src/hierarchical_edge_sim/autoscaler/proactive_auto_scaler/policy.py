"""Proactive front-end: sense/forecast → PredictAndDecide → ClusterManagerCycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.config import EPS

from hierarchical_edge_sim.autoscaler.common.cm_cycle import CycleIntent, cluster_manager_cycle
from hierarchical_edge_sim.autoscaler.reactive_local.allocate import (
    aggregate_ms,
    down_delta,
    ladder_down,
    ladder_up,
    reactive_pressure,
    resolve_help,
    up_delta,
)
from hierarchical_edge_sim.autoscaler.reactive_local.beh import home_cluster_id
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
    cycle: str = "cluster_manager"
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
        self._pending_ms.clear()
        self._pending_proactive_ttw.clear()
        ladder = self.params.ladder
        obs_by: dict[str, dict] = {}

        for ms_id in env.list_microservices():
            st = self._state.setdefault(ms_id, _MsState())
            if st.cooldown > 0:
                st.cooldown -= 1
            obs = aggregate_ms(env, ms_id, tau)
            obs_by[ms_id] = obs
            u_pressure, d_pressure = reactive_pressure(obs, ladder)
            st.u_streak = st.u_streak + 1 if u_pressure else 0
            st.d_streak = st.d_streak + 1 if d_pressure else 0

        def scan_ms(ms_id: str) -> CycleIntent | None:
            rec = closed.get(ms_id)
            if rec is None:
                return None
            st = self._state[ms_id]
            obs = obs_by[ms_id]
            cluster_id = home_cluster_id(env, ms_id)
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
                down_in_cd = rec.ttw_t < self._next_down_ttw.get(ms_id, 0)
                if decision.direction is Direction.UP:
                    if decision.delta_cpu <= EPS and decision.delta_ram <= EPS:
                        return None
                    need_cpu, need_ram = _clip_step(
                        decision.delta_cpu, decision.delta_ram, obs, ladder, up=True
                    )
                    return CycleIntent(
                        ms_id=ms_id,
                        cluster_id=cluster_id,
                        t_det=tau,
                        kind="up",
                        need_cpu=need_cpu,
                        need_ram=need_ram,
                        sustained=decision.sustained,
                        ttw_t=rec.ttw_t,
                    )
                if decision.direction is Direction.DOWN:
                    if down_in_cd:
                        return None
                    d_cpu, d_ram = abs(decision.delta_cpu), abs(decision.delta_ram)
                    if d_cpu <= EPS and d_ram <= EPS:
                        return None
                    d_cpu, d_ram = _clip_step(d_cpu, d_ram, obs, ladder, up=False)
                    return CycleIntent(
                        ms_id=ms_id,
                        cluster_id=cluster_id,
                        t_det=tau,
                        kind="down",
                        need_cpu=d_cpu,
                        need_ram=d_ram,
                    )
                return None

            if st.cooldown > 0:
                return None
            if st.u_streak >= ladder.x_up_streak:
                need_cpu, need_ram = up_delta(obs, ladder)
                return CycleIntent(
                    ms_id=ms_id,
                    cluster_id=cluster_id,
                    t_det=tau,
                    kind="up",
                    need_cpu=need_cpu,
                    need_ram=need_ram,
                    sustained=st.u_streak >= ladder.sustained_up_streak,
                )
            if st.d_streak >= ladder.y_down_streak:
                d_cpu, d_ram = down_delta(obs, ladder)
                return CycleIntent(
                    ms_id=ms_id,
                    cluster_id=cluster_id,
                    t_det=tau,
                    kind="down",
                    need_cpu=d_cpu,
                    need_ram=d_ram,
                )
            return None

        def allocate(intent: CycleIntent) -> tuple[list[Any], HelpRequest | None]:
            obs = obs_by[intent.ms_id]
            if intent.kind == "up":
                ms_actions, leftover = ladder_up(
                    env,
                    intent.ms_id,
                    tau,
                    obs,
                    ladder,
                    need_cpu=intent.need_cpu,
                    need_ram=intent.need_ram,
                    sustained=intent.sustained,
                )
                if (ms_actions or leftover is not None) and intent.ttw_t is not None:
                    self._pending_proactive_ttw[intent.ms_id] = intent.ttw_t
                return ms_actions, leftover
            return (
                ladder_down(
                    env,
                    intent.ms_id,
                    tau,
                    obs,
                    ladder,
                    delta_cpu=intent.need_cpu,
                    delta_ram=intent.need_ram,
                ),
                None,
            )

        actions = cluster_manager_cycle(
            env, tau, scan_ms=scan_ms, allocate=allocate, resolve_help=resolve_help
        )
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
                # Armed on Up only (HPA: 300s down window after a high rec).
                # Down itself does not restart the wait, so 100% cuts can
                # continue each tick the way HPA's 15s scaleDown period does.
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
    """Keep TCN's direction. Up is one α_up step. Down may take the full
    residual up to α_down of current alloc (Kubernetes scaleDown 100% → 1.0).
    """
    if up:
        cap_cpu = max(ladder.delta_cpu_min_cores, ladder.alpha_up * max(obs["sum_cpu_alloc"], EPS))
        need_cpu = min(need_cpu, cap_cpu)
        spec = obs["spec"]
        if spec.ram_per_request_mb > EPS and spec.cpu_per_request_cores > EPS:
            need_ram = need_cpu / spec.cpu_per_request_cores * spec.ram_per_request_mb
        return need_cpu, need_ram
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
