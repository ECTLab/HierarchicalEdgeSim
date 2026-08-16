"""AllocateResources: BEV → BEH → vicinity → BEG, plus cost-ordered down."""

from __future__ import annotations

from typing import Any

from hierarchical_edge_sim.autoscaler.common.distribute import (
    ReplicaView,
    distribute_down,
    distribute_up,
    leftover_from_need_horizontal,
    strip_need_horizontal,
)
from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.config import EPS

from .beg import leftover_to_global_help, schedule_beg
from .beh import beh_down, beh_up, home_cluster_id
from .cascade import check_cascading_migration
from .help import HelpRequest
from .params import ReactiveLocalParams
from .vicinity import leftover_to_help_action, schedule_vicinity_help


def aggregate_ms(env: Env, ms_id: str, tau: int) -> dict:
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

    # Headroom 0 + load ⇒ saturated (floors buy no μ). Do not report q=0.
    q_cpu = (
        1.0
        if sum_h_cpu <= EPS and sum_in > EPS
        else (sum_used_cpu / max(sum_h_cpu, EPS) if sum_h_cpu > EPS else 0.0)
    )
    if spec.ram_per_request_mb > EPS:
        q_ram = (
            1.0
            if sum_h_ram <= EPS and sum_in > EPS
            else (sum_used_ram / max(sum_h_ram, EPS) if sum_h_ram > EPS else 0.0)
        )
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
        "sum_h_ram": sum_h_ram,
        "spec": spec,
    }


def reactive_pressure(obs: dict, params: ReactiveLocalParams) -> tuple[bool, bool]:
    n_replicas = len(obs["replicas"])
    u_pressure = obs["D"] > params.eps_drop
    if params.use_near_saturation_up and obs["q_ms"] >= params.theta_high:
        u_pressure = True
    replica_slack = (
        1.0 - (sum(r.q for r in obs["replicas"]) / len(obs["replicas"])) if obs["replicas"] else 0.0
    )
    d_pressure = (
        obs["D"] <= params.eps_drop
        and replica_slack >= params.theta_free
        and (obs["room_down_cpu"] > EPS or n_replicas > 1)
    )
    if u_pressure:
        d_pressure = False
    return u_pressure, d_pressure


def up_delta(obs: dict, params: ReactiveLocalParams) -> tuple[float, float]:
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


def down_delta(obs: dict, params: ReactiveLocalParams) -> tuple[float, float]:
    spec = obs["spec"]
    delta_cpu = max(params.delta_cpu_min_cores, params.alpha_down * obs["sum_cpu_alloc"])
    ram_modeled = spec.ram_per_request_mb > EPS
    delta_ram = (
        max(params.delta_ram_min_mb, params.alpha_down * obs["sum_ram_alloc"]) if ram_modeled else 0.0
    )
    return delta_cpu, delta_ram


def ladder_up(
    env: Env,
    ms_id: str,
    tau: int,
    obs: dict,
    params: ReactiveLocalParams,
    *,
    need_cpu: float,
    need_ram: float,
    sustained: bool,
) -> tuple[list[Any], HelpRequest | None]:
    spec = obs["spec"]
    replicas: list[ReplicaView] = obs["replicas"]
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
        min_head_cpu=params.delta_cpu_min_cores,
        min_head_ram=params.delta_ram_min_mb,
    )
    actions.extend(spawns)
    leftover: HelpRequest | None = None
    if remain_cpu > EPS or remain_ram > EPS:
        leftover = HelpRequest(
            seq=0,
            tau=tau,
            ms_id=ms_id,
            home_cluster_id=cluster_id,
            remain_cpu=remain_cpu,
            remain_ram=remain_ram,
            cpu_min=spec.cpu_min_cores,
            ram_min=spec.ram_min_mb,
        )
    return actions, leftover


def ladder_down(
    env: Env,
    ms_id: str,
    tau: int,
    obs: dict,
    params: ReactiveLocalParams,
    *,
    delta_cpu: float,
    delta_ram: float,
    protect_last_serving: bool = False,
) -> list[Any]:
    spec = obs["spec"]
    replicas: list[ReplicaView] = obs["replicas"]
    ram_modeled = spec.ram_per_request_mb > EPS
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
        protect_last_serving=protect_last_serving,
    )
    granted_cpu, granted_ram = _granted_down(replicas, bev)
    remain_cpu = max(0.0, delta_cpu - granted_cpu)
    remain_ram = max(0.0, delta_ram - granted_ram) if ram_modeled else 0.0
    skip_ids = {a.container_id for a in bev}
    owner = home_cluster_id(env, ms_id)
    terms = beh_down(
        env=env,
        replicas=replicas,
        ms_id=ms_id,
        owner_cluster_id=owner,
        remain_cpu=remain_cpu,
        remain_ram=remain_ram,
        ram_modeled=ram_modeled,
        skip_ids=skip_ids,
        tau=tau,
        spec=spec,
        protect_last_serving=protect_last_serving,
    )
    actions: list[Any] = [*bev, *terms]
    if params.cascade_home:
        freed_cpu, freed_ram = _freed_local(env, replicas, actions, owner)
        actions.extend(
            check_cascading_migration(
                env,
                ms_id=ms_id,
                owner_cluster_id=owner,
                spec=spec,
                freed_cpu=freed_cpu,
                freed_ram=freed_ram,
                pending=actions,
                tau=tau,
            )
        )
    return actions


def resolve_help(
    env: Env,
    help_q: list[HelpRequest],
    pending: list[Any],
    tau: int,
) -> list[Any]:
    if not help_q:
        return []
    if env.root is None:
        return [leftover_to_help_action(u) for u in help_q]
    actions: list[Any] = []
    vspawns, unresolved = schedule_vicinity_help(env, help_q, pending=pending, tau=tau)
    actions.extend(vspawns)
    gspawns, still = schedule_beg(env, unresolved, pending=[*pending, *actions], tau=tau)
    actions.extend(gspawns)
    actions.extend(leftover_to_global_help(u) for u in still)
    return actions


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


def _freed_local(
    env: Env,
    replicas: list[ReplicaView],
    actions: list,
    owner_cluster_id: str,
) -> tuple[float, float]:
    """Local CPU/RAM released this tick by BEV shrink or local terminate (not loans)."""
    by_id = {r.container_id: r for r in replicas}
    cpu = ram = 0.0
    for action in actions:
        view = by_id.get(getattr(action, "container_id", ""), None)
        if view is None:
            continue
        sid = view.server_id or env.get_container(view.container_id).server_id
        if env.get_server(sid).cluster_id != owner_cluster_id:
            continue
        kind = getattr(action, "type", "")
        if kind == "resize":
            if action.cpu_alloc_cores is not None:
                cpu += max(0.0, view.cpu_alloc - float(action.cpu_alloc_cores))
            if action.ram_alloc_mb is not None:
                ram += max(0.0, view.ram_alloc - float(action.ram_alloc_mb))
        elif kind == "terminate":
            cpu += view.cpu_alloc
            ram += view.ram_alloc
    return cpu, ram
