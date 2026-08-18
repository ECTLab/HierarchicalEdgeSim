"""Per-MS reactive ladder: BEV then BEH then vicinity help then BEG."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.env.api import Env, ResizeResult

from .allocate import (
    aggregate_ms,
    down_delta,
    ladder_down,
    ladder_up,
    reactive_pressure,
    resolve_help,
    up_delta,
)
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
    params: ReactiveLocalParams = field(default_factory=ReactiveLocalParams)
    decision_every_k_ticks: int = 1
    _state: dict[str, _MsState] = field(default_factory=dict)
    _pending_ms: set[str] = field(default_factory=set)

    def on_tick_end(self, env: Env, tau: int) -> list[Any]:
        actions: list[Any] = []
        help_q: list[HelpRequest] = []
        seq = 0
        self._pending_ms.clear()
        for ms_id in env.list_microservices():
            st = self._state.setdefault(ms_id, _MsState())
            if st.cooldown > 0:
                st.cooldown -= 1

            obs = aggregate_ms(env, ms_id, tau)
            u_pressure, d_pressure = reactive_pressure(obs, self.params)
            st.u_streak = st.u_streak + 1 if u_pressure else 0
            st.d_streak = st.d_streak + 1 if d_pressure else 0

            if tau % self.decision_every_k_ticks != 0:
                continue
            if st.cooldown > 0:
                continue

            if st.u_streak >= self.params.x_up_streak:
                need_cpu, need_ram = up_delta(obs, self.params)
                ms_actions, leftover = ladder_up(
                    env,
                    ms_id,
                    tau,
                    obs,
                    self.params,
                    need_cpu=need_cpu,
                    need_ram=need_ram,
                    sustained=st.u_streak >= self.params.sustained_up_streak,
                )
                actions.extend(ms_actions)
                if leftover is not None:
                    leftover.seq = seq
                    help_q.append(leftover)
                    seq += 1
            elif st.d_streak >= self.params.y_down_streak:
                d_cpu, d_ram = down_delta(obs, self.params)
                actions.extend(
                    ladder_down(
                        env,
                        ms_id,
                        tau,
                        obs,
                        self.params,
                        delta_cpu=d_cpu,
                        delta_ram=d_ram,
                    )
                )

        actions.extend(resolve_help(env, help_q, actions, tau))
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
