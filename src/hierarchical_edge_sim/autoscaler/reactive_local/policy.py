"""Per-MS reactive ladder: BEV then BEH then vicinity help then BEG."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.env.api import Env, ResizeResult

from hierarchical_edge_sim.autoscaler.common.cm_cycle import CycleIntent, cluster_manager_cycle

from .allocate import (
    aggregate_ms,
    down_delta,
    ladder_down,
    ladder_up,
    reactive_pressure,
    resolve_help,
    up_delta,
)
from .beh import home_cluster_id
from .help import HelpRequest
from .params import ReactiveLocalParams, validate_params


@dataclass(slots=True)
class _MsState:
    u_streak: int = 0
    d_streak: int = 0
    cooldown: int = 0


@dataclass(slots=True)
class ReactiveLocalAutoscaler:
    name: str = "reactive_local"
    cycle: str = "cluster_manager"
    params: ReactiveLocalParams = field(default_factory=ReactiveLocalParams)
    decision_every_k_ticks: int = 1
    _state: dict[str, _MsState] = field(default_factory=dict)
    _pending_ms: set[str] = field(default_factory=set)

    def on_tick_end(self, env: Env, tau: int) -> list[Any]:
        self._pending_ms.clear()
        obs_by: dict[str, dict] = {}
        for ms_id in env.list_microservices():
            st = self._state.setdefault(ms_id, _MsState())
            if st.cooldown > 0:
                st.cooldown -= 1
            obs = aggregate_ms(env, ms_id, tau)
            obs_by[ms_id] = obs
            u_pressure, d_pressure = reactive_pressure(obs, self.params)
            st.u_streak = st.u_streak + 1 if u_pressure else 0
            st.d_streak = st.d_streak + 1 if d_pressure else 0

        def scan_ms(ms_id: str) -> CycleIntent | None:
            if tau % self.decision_every_k_ticks != 0:
                return None
            st = self._state[ms_id]
            if st.cooldown > 0:
                return None
            cluster_id = home_cluster_id(env, ms_id)
            obs = obs_by[ms_id]
            if st.u_streak >= self.params.x_up_streak:
                need_cpu, need_ram = up_delta(obs, self.params)
                return CycleIntent(
                    ms_id=ms_id,
                    cluster_id=cluster_id,
                    t_det=tau,
                    kind="up",
                    need_cpu=need_cpu,
                    need_ram=need_ram,
                    sustained=st.u_streak >= self.params.sustained_up_streak,
                )
            if st.d_streak >= self.params.y_down_streak:
                d_cpu, d_ram = down_delta(obs, self.params)
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
                return ladder_up(
                    env,
                    intent.ms_id,
                    tau,
                    obs,
                    self.params,
                    need_cpu=intent.need_cpu,
                    need_ram=intent.need_ram,
                    sustained=intent.sustained,
                )
            return (
                ladder_down(
                    env,
                    intent.ms_id,
                    tau,
                    obs,
                    self.params,
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

    def on_actions_applied(self, results: list[ResizeResult]) -> None:
        if any(getattr(r, "ok", False) for r in results):
            for ms_id in self._pending_ms:
                st = self._state.setdefault(ms_id, _MsState())
                st.u_streak = 0
                st.d_streak = 0
                st.cooldown = self.params.cooldown_ticks
        self._pending_ms.clear()


def build(params: dict, decision_every_k_ticks: int = 1) -> ReactiveLocalAutoscaler:
    return ReactiveLocalAutoscaler(
        params=validate_params(params),
        decision_every_k_ticks=decision_every_k_ticks,
    )
