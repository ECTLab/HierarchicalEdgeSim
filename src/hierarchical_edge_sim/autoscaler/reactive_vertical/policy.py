"""Per-MS reactive vertical autoscaler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.env.api import Env, NeedHorizontalAction, ResizeAction, ResizeResult
from hierarchical_edge_sim.env.config import EPS

from .distribute import ReplicaView, distribute_down, distribute_up
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
        for ms_id in env.list_microservices():
            st = self._state.setdefault(ms_id, _MsState())
            if st.cooldown > 0:
                st.cooldown -= 1

            obs = _aggregate_ms(env, ms_id, tau, self.params)
            u_pressure = obs["D"] > self.params.eps_drop
            if self.params.use_near_saturation_up and obs["q_ms"] >= self.params.theta_high:
                u_pressure = True
            d_pressure = (
                obs["D"] <= self.params.eps_drop
                and obs["slack_ms"] >= self.params.theta_free
                and obs["room_down_cpu"] > EPS
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
                if obs["room_up_cpu"] > EPS or obs["room_up_ram"] > EPS:
                    intent = "UP"
                else:
                    intent = "NEED_HORIZONTAL"
            elif st.d_streak >= self.params.y_down_streak and obs["room_down_cpu"] > EPS:
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
                        residual_cpu_cores=obs["D"] * obs["spec"].cpu_per_request_cores,
                        residual_ram_mb=obs["D"] * obs["spec"].ram_per_request_mb,
                    )
                )
                continue

            ms_actions = _intent_to_actions(env, ms_id, tau, intent, obs, self.params)
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


def _aggregate_ms(env: Env, ms_id: str, tau: int, params: ReactiveVerticalParams) -> dict:
    ms = env.get_microservice(ms_id)
    spec = env.get_ms_spec(ms_id)
    replicas: list[ReplicaView] = []
    sum_in = sum_served = sum_drop = 0.0
    sum_h_cpu = sum_h_ram = 0.0
    sum_used_cpu = sum_used_ram = 0.0
    room_up_cpu = room_up_ram = room_down_cpu = room_down_ram = 0.0

    for cid in sorted(ms.container_ids):
        c = env.get_container(cid)
        rec = c.history_at(tau)
        h_cpu = max(0.0, c.cpu_alloc_cores - spec.cpu_min_cores)
        h_ram = max(0.0, c.ram_alloc_mb - spec.ram_min_mb)
        used_cpu = rec.lambda_served * spec.cpu_per_request_cores
        used_ram = rec.lambda_served * spec.ram_per_request_mb
        q_c = 0.0
        for qv in (rec.q_cpu, rec.q_ram):
            if qv != qv or qv == float("inf"):  # NaN or inf
                q_c = max(q_c, 1.0)
            else:
                q_c = max(q_c, min(max(qv, 0.0), 1.0))
        slack_c = 1.0 - q_c

        free_cpu, free_ram = env.get_server_free(c.server_id)
        rup_cpu = min(spec.cpu_max_cores - c.cpu_alloc_cores, free_cpu)
        rup_ram = min(spec.ram_max_mb - c.ram_alloc_mb, free_ram)
        rdown_cpu = max(0.0, c.cpu_alloc_cores - spec.cpu_min_cores)
        rdown_ram = max(0.0, c.ram_alloc_mb - spec.ram_min_mb)

        replicas.append(
            ReplicaView(
                container_id=cid,
                drop=rec.lambda_dropped,
                q=q_c,
                slack=slack_c,
                cpu_alloc=c.cpu_alloc_cores,
                ram_alloc=c.ram_alloc_mb,
                room_up_cpu=max(0.0, rup_cpu),
                room_up_ram=max(0.0, rup_ram),
                room_down_cpu=rdown_cpu,
                room_down_ram=rdown_ram,
            )
        )
        sum_in += rec.lambda_in
        sum_served += rec.lambda_served
        sum_drop += rec.lambda_dropped
        sum_h_cpu += h_cpu
        sum_h_ram += h_ram
        sum_used_cpu += used_cpu
        sum_used_ram += used_ram
        room_up_cpu += max(0.0, rup_cpu)
        room_up_ram += max(0.0, rup_ram)
        room_down_cpu += rdown_cpu
        room_down_ram += rdown_ram

    q_cpu = sum_used_cpu / max(sum_h_cpu, EPS)
    if spec.ram_per_request_mb > EPS:
        q_ram = sum_used_ram / max(sum_h_ram, EPS)
        q_ms = min(max(max(q_cpu, q_ram), 0.0), 1.0)
    else:
        q_ms = min(max(q_cpu, 0.0), 1.0)
    slack_ms = 1.0 - q_ms

    return {
        "Lambda": sum_in,
        "S": sum_served,
        "D": sum_drop,
        "q_ms": q_ms,
        "slack_ms": slack_ms,
        "replicas": replicas,
        "room_up_cpu": room_up_cpu,
        "room_up_ram": room_up_ram,
        "room_down_cpu": room_down_cpu,
        "room_down_ram": room_down_ram,
        "sum_cpu_alloc": sum(r.cpu_alloc for r in replicas),
        "sum_ram_alloc": sum(r.ram_alloc for r in replicas),
        "sum_h_cpu": sum_h_cpu,
        "spec": spec,
    }


def _intent_to_actions(env: Env, ms_id: str, tau: int, intent: str, obs: dict, params: ReactiveVerticalParams):
    spec = obs["spec"]
    replicas: list[ReplicaView] = obs["replicas"]
    if intent == "UP":
        deficit = obs["D"]
        need_cpu = deficit * spec.cpu_per_request_cores
        need_ram = deficit * spec.ram_per_request_mb
        delta_cpu = min(max(need_cpu, params.delta_cpu_min_cores), params.alpha_up * max(obs["sum_cpu_alloc"], EPS))
        if spec.ram_per_request_mb > EPS:
            delta_ram = min(max(need_ram, params.delta_ram_min_mb), params.alpha_up * max(obs["sum_ram_alloc"], EPS))
        else:
            delta_ram = 0.0
        delta_cpu = min(delta_cpu, obs["room_up_cpu"]) if obs["room_up_cpu"] > 0 else delta_cpu
        delta_ram = min(delta_ram, obs["room_up_ram"]) if obs["room_up_ram"] > 0 else delta_ram
        return distribute_up(
            env=env,
            ms_id=ms_id,
            spec=spec,
            params=params,
            replicas=replicas,
            delta_cpu=delta_cpu,
            delta_ram=delta_ram,
            tau=tau,
        )

    # DOWN
    delta_cpu = max(params.delta_cpu_min_cores, params.alpha_down * obs["sum_cpu_alloc"])
    delta_ram = (
        max(params.delta_ram_min_mb, params.alpha_down * obs["sum_ram_alloc"])
        if spec.ram_per_request_mb > EPS
        else 0.0
    )
    return distribute_down(
        env=env,
        ms_id=ms_id,
        spec=spec,
        params=params,
        replicas=replicas,
        delta_cpu=delta_cpu,
        delta_ram=delta_ram,
        tau=tau,
    )
