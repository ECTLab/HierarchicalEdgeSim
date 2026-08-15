"""Per-MS reactive local ladder: BEV then in-cluster BEH."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.autoscaler.common.distribute import (
    ReplicaView,
    distribute_down,
    distribute_up,
    leftover_from_need_horizontal,
    strip_need_horizontal,
)
from hierarchical_edge_sim.env.api import Env, NeedVicinityHelpAction, ResizeResult
from hierarchical_edge_sim.env.config import EPS

from .beh import beh_down, beh_up, home_cluster_id
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
        self._pending_ms.clear()
        for ms_id in env.list_microservices():
            st = self._state.setdefault(ms_id, _MsState())
            if st.cooldown > 0:
                st.cooldown -= 1

            obs = _aggregate_ms(env, ms_id, tau)
            n_replicas = len(obs["replicas"])
            u_pressure = obs["D"] > self.params.eps_drop
            if self.params.use_near_saturation_up and obs["q_ms"] >= self.params.theta_high:
                u_pressure = True
            replica_slack = (
                1.0 - (sum(r.q for r in obs["replicas"]) / len(obs["replicas"]))
                if obs["replicas"]
                else 0.0
            )
            d_pressure = (
                obs["D"] <= self.params.eps_drop
                and replica_slack >= self.params.theta_free
                and (obs["room_down_cpu"] > EPS or n_replicas > 1)
            )
            if u_pressure:
                d_pressure = False

            st.u_streak = st.u_streak + 1 if u_pressure else 0
            st.d_streak = st.d_streak + 1 if d_pressure else 0

            if tau % self.decision_every_k_ticks != 0:
                continue
            if st.cooldown > 0:
                continue

            if st.u_streak >= self.params.x_up_streak:
                ms_actions = _ladder_up(env, ms_id, tau, obs, self.params, st)
            elif st.d_streak >= self.params.y_down_streak:
                ms_actions = _ladder_down(env, ms_id, tau, obs, self.params)
            else:
                continue

            if any(getattr(a, "type", "") in {"resize", "spawn", "terminate"} for a in ms_actions):
                self._pending_ms.add(ms_id)
            actions.extend(ms_actions)
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


def _ladder_up(
    env: Env,
    ms_id: str,
    tau: int,
    obs: dict,
    params: ReactiveLocalParams,
    st: _MsState,
) -> list[Any]:
    spec = obs["spec"]
    replicas: list[ReplicaView] = obs["replicas"]
    need_cpu, need_ram = _up_delta(obs, params)
    sustained = st.u_streak >= params.sustained_up_streak
    actions: list[Any] = []
    remain_cpu, remain_ram = need_cpu, need_ram

    if not sustained and (need_cpu > EPS or need_ram > EPS):
        bev = distribute_up(
            env=env,
            ms_id=ms_id,
            spec=spec,
            params=params,
            replicas=replicas,
            delta_cpu=need_cpu,
            delta_ram=need_ram,
            tau=tau,
            reason="bev_up",
        )
        remain_cpu, remain_ram = leftover_from_need_horizontal(bev)
        if not any(getattr(a, "type", "") == "need_horizontal" for a in bev):
            remain_cpu, remain_ram = 0.0, 0.0
        actions.extend(strip_need_horizontal(bev))

    cluster_id = home_cluster_id(env, ms_id)
    spawns, remain_cpu, remain_ram = beh_up(
        env=env,
        ms_id=ms_id,
        spec=spec,
        cluster_id=cluster_id,
        remain_cpu=remain_cpu,
        remain_ram=remain_ram,
        tau=tau,
        pending_resize=actions,
    )
    actions.extend(spawns)
    if remain_cpu > EPS or remain_ram > EPS:
        actions.append(
            NeedVicinityHelpAction(
                type="need_vicinity_help",
                ms_id=ms_id,
                reason="need_vicinity_help",
                tau=tau,
                residual_cpu_cores=remain_cpu,
                residual_ram_mb=remain_ram,
                cluster_id=cluster_id,
            )
        )
    return actions


def _ladder_down(
    env: Env,
    ms_id: str,
    tau: int,
    obs: dict,
    params: ReactiveLocalParams,
) -> list[Any]:
    spec = obs["spec"]
    replicas: list[ReplicaView] = obs["replicas"]
    delta_cpu = max(params.delta_cpu_min_cores, params.alpha_down * obs["sum_cpu_alloc"])
    ram_modeled = spec.ram_per_request_mb > EPS
    delta_ram = (
        max(params.delta_ram_min_mb, params.alpha_down * obs["sum_ram_alloc"]) if ram_modeled else 0.0
    )
    bev = distribute_down(
        env=env,
        ms_id=ms_id,
        spec=spec,
        params=params,
        replicas=replicas,
        delta_cpu=delta_cpu,
        delta_ram=delta_ram,
        tau=tau,
        reason="bev_down",
    )
    granted_cpu, granted_ram = _granted_down(replicas, bev)
    remain_cpu = max(0.0, delta_cpu - granted_cpu)
    remain_ram = max(0.0, delta_ram - granted_ram) if ram_modeled else 0.0
    skip_ids = {a.container_id for a in bev}
    terms = beh_down(
        replicas=replicas,
        ms_id=ms_id,
        remain_cpu=remain_cpu,
        remain_ram=remain_ram,
        ram_modeled=ram_modeled,
        skip_ids=skip_ids,
        tau=tau,
    )
    return [*bev, *terms]


def _up_delta(obs: dict, params: ReactiveLocalParams) -> tuple[float, float]:
    spec = obs["spec"]
    if params.up_mode == "deficit":
        need_cpu = obs["D"] * spec.cpu_per_request_cores
        need_ram = obs["D"] * spec.ram_per_request_mb
        delta_cpu = min(max(need_cpu, params.delta_cpu_min_cores), params.alpha_up * max(obs["sum_cpu_alloc"], EPS))
        if spec.ram_per_request_mb > EPS:
            delta_ram = min(
                max(need_ram, params.delta_ram_min_mb),
                params.alpha_up * max(obs["sum_ram_alloc"], EPS),
            )
        else:
            delta_ram = 0.0
    else:
        delta_cpu = max(params.delta_cpu_min_cores, params.alpha_up * obs["sum_cpu_alloc"])
        delta_ram = (
            max(params.delta_ram_min_mb, params.alpha_up * obs["sum_ram_alloc"])
            if spec.ram_per_request_mb > EPS
            else 0.0
        )
    return delta_cpu, delta_ram


def _granted_down(replicas: list[ReplicaView], actions: list) -> tuple[float, float]:
    by_id = {r.container_id: r for r in replicas}
    cpu = ram = 0.0
    for action in actions:
        if getattr(action, "type", "") != "resize":
            continue
        view = by_id.get(action.container_id)
        if view is None:
            continue
        if action.cpu_alloc_cores is not None:
            cpu += max(0.0, view.cpu_alloc - float(action.cpu_alloc_cores))
        if action.ram_alloc_mb is not None:
            ram += max(0.0, view.ram_alloc - float(action.ram_alloc_mb))
    return cpu, ram


def _aggregate_ms(env: Env, ms_id: str, tau: int) -> dict:
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
            if qv != qv or qv == float("inf"):
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
                server_id=c.server_id,
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
