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
    return delta_cpu, delta_ram


def down_delta(obs: dict, params: ReactiveLocalParams) -> tuple[float, float]:
    """MS-wide CPU/RAM to release this down tick (surplus of serving capacity).

    Target ``μ = Λ / (1-θ_free)`` and release only ``max(0, μ − μ_tgt)``
    converted through per-request costs. CPU and RAM stay coupled so idle RAM
    cannot justify killing CPU that the load still needs. Never take ``Δ_min``
    past that surplus — that overshoot is what drove the last replica through
    ``μ = 0``. Extra replicas that add no μ still get a rate-cap token so BEH
    can terminate them.
    """
    spec = obs["spec"]
    ram_modeled = spec.ram_per_request_mb > EPS
    cap_cpu, cap_ram = _down_rate_cap(obs, params, ram_modeled)
    load = float(obs.get("Lambda") or 0.0)
    q_tgt = min(max(1.0 - params.theta_free, EPS), 1.0)
    mu_tgt = load / q_tgt
    mu = _fleet_mu(obs, ram_modeled)
    surplus_mu = max(0.0, mu - mu_tgt)
    n_replicas = len(obs.get("replicas") or [])
    delta_cpu = surplus_mu * spec.cpu_per_request_cores
    delta_ram = surplus_mu * spec.ram_per_request_mb if ram_modeled else 0.0
    if n_replicas <= 1:
        return (
            min(delta_cpu, cap_cpu) if delta_cpu > EPS else 0.0,
            min(delta_ram, cap_ram) if delta_ram > EPS else 0.0,
        )
    if surplus_mu > EPS:
        return delta_cpu, delta_ram
    # Borrowed replicas at cpu_min add no μ; still allow BEH to reclaim them.
    if mu <= EPS:
        return cap_cpu, cap_ram
    return 0.0, 0.0


def _fleet_mu(obs: dict, ram_modeled: bool) -> float:
    spec = obs["spec"]
    if spec.cpu_per_request_cores <= EPS:
        mu_cpu = 0.0
    else:
        mu_cpu = float(obs.get("sum_h_cpu") or 0.0) / spec.cpu_per_request_cores
    if not ram_modeled:
        return mu_cpu
    mu_ram = float(obs.get("sum_h_ram") or 0.0) / spec.ram_per_request_mb
    return min(mu_cpu, mu_ram)


def _down_rate_cap(obs: dict, params: ReactiveLocalParams, ram_modeled: bool) -> tuple[float, float]:
    cap_cpu = max(params.delta_cpu_min_cores, params.alpha_down * max(obs["sum_cpu_alloc"], EPS))
    cap_ram = (
        max(params.delta_ram_min_mb, params.alpha_down * max(obs["sum_ram_alloc"], EPS))
        if ram_modeled
        else 0.0
    )
    return cap_cpu, cap_ram


def target_mu(obs: dict, params: ReactiveLocalParams) -> float:
    load = float(obs.get("Lambda") or 0.0)
    q_tgt = min(max(1.0 - params.theta_free, EPS), 1.0)
    return load / q_tgt


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
) -> list[Any]:
    spec = obs["spec"]
    replicas: list[ReplicaView] = obs["replicas"]
    ram_modeled = spec.ram_per_request_mb > EPS
    cap_cpu, cap_ram = _down_rate_cap(obs, params, ram_modeled)
    n_replicas = len(replicas)
    # Extras: reclaim replica count first. Do not BEV-shrink the seed in the
    # same tick as a terminate — that is what left μ too small and bounced UP.
    if n_replicas > 1:
        bev: list[Any] = []
        remain_cpu, remain_ram = delta_cpu, delta_ram
    else:
        bev = distribute_down(
            env=env,
            ms_id=ms_id,
            spec=spec,
            params=params,
            replicas=replicas,
            delta_cpu=min(delta_cpu, cap_cpu),
            delta_ram=min(delta_ram, cap_ram) if ram_modeled else 0.0,
            tau=tau,
            reason="bev_down",
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
        mu_tgt=target_mu(obs, params),
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
