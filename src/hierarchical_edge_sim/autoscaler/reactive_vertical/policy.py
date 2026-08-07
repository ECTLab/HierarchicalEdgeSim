"""Per-MS reactive vertical autoscaler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.autoscaler.common.distribute import (
    distribute_down,
    distribute_params_from_reactive,
    distribute_up,
)
from hierarchical_edge_sim.autoscaler.common.snapshot import MsSnapshot, snapshot_ms
from hierarchical_edge_sim.env.api import Env, NeedHorizontalAction, ResizeResult
from hierarchical_edge_sim.env.config import EPS

from .params import ReactiveVerticalParams, validate_params


@dataclass(slots=True)
class _MsState:
    u_streak: int = 0
    d_streak: int = 0
    cooldown: int = 0


@dataclass(slots=True)
class ReactiveVerticalAutoscaler:
    name: str = "reactive_vertical"
    params: ReactiveVerticalParams = field(default_factory=ReactiveVerticalParams)
    decision_every_k_ticks: int = 1
    _state: dict[str, _MsState] = field(default_factory=dict)
    _pending_ms: set[str] = field(default_factory=set)

    def on_tick_end(self, env: Env, tau: int) -> list[Any]:
        actions: list[Any] = []
        self._pending_ms.clear()
        dist = distribute_params_from_reactive(self.params)
        for ms_id in env.list_microservices():
            st = self._state.setdefault(ms_id, _MsState())
            if st.cooldown > 0:
                st.cooldown -= 1

            snap = snapshot_ms(env, ms_id, tau)
            u_pressure = snap.dropped_total > self.params.eps_drop
            if self.params.use_near_saturation_up and snap.util_ratio >= self.params.theta_high:
                u_pressure = True
            d_pressure = (
                snap.dropped_total <= self.params.eps_drop
                and snap.slack_ratio >= self.params.theta_free
                and snap.room_down_cpu > EPS
            )
            if u_pressure:
                d_pressure = False

            st.u_streak = st.u_streak + 1 if u_pressure else 0
            st.d_streak = st.d_streak + 1 if d_pressure else 0

            if tau % self.decision_every_k_ticks != 0:
                continue
            if st.cooldown > 0:
                continue

            intent = "HOLD"
            if st.u_streak >= self.params.x_up_streak:
                if snap.room_up_cpu > EPS or snap.room_up_ram > EPS:
                    intent = "UP"
                else:
                    intent = "NEED_HORIZONTAL"
            elif st.d_streak >= self.params.y_down_streak and snap.room_down_cpu > EPS:
                intent = "DOWN"

            if intent == "HOLD":
                continue

            if intent == "NEED_HORIZONTAL":
                actions.append(
                    NeedHorizontalAction(
                        type="need_horizontal",
                        ms_id=ms_id,
                        reason="need_horizontal",
                        tau=tau,
                        residual_cpu_cores=snap.dropped_total * snap.spec.cpu_per_request_cores,
                        residual_ram_mb=snap.dropped_total * snap.spec.ram_per_request_mb,
                    )
                )
                continue

            ms_actions = _intent_to_actions(env, ms_id, tau, intent, snap, self.params, dist)
            if any(getattr(a, "type", "") == "resize" for a in ms_actions):
                self._pending_ms.add(ms_id)
            actions.extend(ms_actions)
        return actions

    def on_actions_applied(self, results: list[ResizeResult]) -> None:
        if any(r.ok for r in results):
            for ms_id in self._pending_ms:
                st = self._state.setdefault(ms_id, _MsState())
                st.u_streak = 0
                st.d_streak = 0
                st.cooldown = self.params.cooldown_ticks
        self._pending_ms.clear()


def build(params: dict, decision_every_k_ticks: int = 1) -> ReactiveVerticalAutoscaler:
    return ReactiveVerticalAutoscaler(
        params=validate_params(params),
        decision_every_k_ticks=decision_every_k_ticks,
    )


def _intent_to_actions(
    env: Env,
    ms_id: str,
    tau: int,
    intent: str,
    snap: MsSnapshot,
    params: ReactiveVerticalParams,
    dist_params: Any,
):
    spec = snap.spec
    replicas = snap.replicas
    if intent == "UP":
        if params.up_mode == "deficit":
            deficit = snap.dropped_total
            need_cpu = deficit * spec.cpu_per_request_cores
            need_ram = deficit * spec.ram_per_request_mb
            delta_cpu = min(max(need_cpu, params.delta_cpu_min_cores), params.alpha_up * max(snap.A_cpu, EPS))
            if spec.ram_per_request_mb > EPS:
                delta_ram = min(max(need_ram, params.delta_ram_min_mb), params.alpha_up * max(snap.A_ram, EPS))
            else:
                delta_ram = 0.0
        else:
            delta_cpu = max(params.delta_cpu_min_cores, params.alpha_up * snap.A_cpu)
            delta_ram = (
                max(params.delta_ram_min_mb, params.alpha_up * snap.A_ram)
                if spec.ram_per_request_mb > EPS
                else 0.0
            )
        delta_cpu = min(delta_cpu, snap.room_up_cpu) if snap.room_up_cpu > 0 else delta_cpu
        delta_ram = min(delta_ram, snap.room_up_ram) if snap.room_up_ram > 0 else delta_ram
        return distribute_up(
            env=env,
            ms_id=ms_id,
            spec=spec,
            params=dist_params,
            replicas=replicas,
            delta_cpu=delta_cpu,
            delta_ram=delta_ram,
            tau=tau,
            reason="reactive_up",
        )

    delta_cpu = max(params.delta_cpu_min_cores, params.alpha_down * snap.A_cpu)
    delta_ram = (
        max(params.delta_ram_min_mb, params.alpha_down * snap.A_ram)
        if spec.ram_per_request_mb > EPS
        else 0.0
    )
    return distribute_down(
        env=env,
        ms_id=ms_id,
        spec=spec,
        params=dist_params,
        replicas=replicas,
        delta_cpu=delta_cpu,
        delta_ram=delta_ram,
        tau=tau,
        reason="reactive_down",
    )
