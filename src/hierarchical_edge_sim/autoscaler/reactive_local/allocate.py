"""AllocateResources (paper Algorithm allocate).

The listing is the local escalator only: VerticalScaling then
HorizontalScaling on workers the cluster owns. Up leftover is ρ; Down
splits the remote share L into ξ (Eq. split) before touching N_c.
VicinityRound is Algorithm 2's ``resolve_help``: every member reports,
only ℓ(V) schedules, ApplyVicinityPlan emits the actions.

Cooldown sits outside this module (policy apply hook). The residual is
not α-clipped; AllocateResources applies it in one window.
See ``docs/allocate-resources.md``.
"""

from __future__ import annotations

from typing import Any

from hierarchical_edge_sim.autoscaler.common.distribute import (
    ReplicaView,
    distribute_down,
    distribute_up,
    leftover_from_need_horizontal,
    strip_need_horizontal,
)
from hierarchical_edge_sim.autoscaler.common.mu_scale import up_delta
from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.config import EPS

from .cascade import check_cascading_migration
from .help import HelpRequest, ReleaseIntent
from .horizontal import home_cluster_id, home_replicas, horizontal_down, horizontal_up
from .params import ReactiveLocalParams
from .release import borrowed_footprint, split_borrowed_share
from .vicinity import leftover_to_help_action, leftover_to_unmet_demand, schedule_vicinity_help


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


def down_delta(obs: dict, params: ReactiveLocalParams) -> tuple[float, float]:
    """MS-wide CPU/RAM to release this down tick.

    Size each resource's serving headroom to ``μ_tgt · ρ``. Idle RAM (or CPU)
    above that is surplus even when the other resource still binds. Last replica
    releases the full surplus toward ``μ_tgt``; extras still get a token so
    HorizontalScaling can terminate floor replicas.
    """
    spec = obs["spec"]
    ram_modeled = spec.ram_per_request_mb > EPS
    rho_cpu = spec.cpu_per_request_cores
    rho_ram = spec.ram_per_request_mb
    load = float(obs.get("Lambda") or 0.0)
    q_tgt = min(max(1.0 - params.theta_free, EPS), 1.0)
    mu_tgt = load / q_tgt
    mu = _fleet_mu(obs, ram_modeled)
    n_replicas = len(obs.get("replicas") or [])
    h_cpu_tgt = mu_tgt * rho_cpu if rho_cpu > EPS else 0.0
    h_ram_tgt = mu_tgt * rho_ram if ram_modeled and rho_ram > EPS else 0.0
    delta_cpu = max(0.0, float(obs.get("sum_h_cpu") or 0.0) - h_cpu_tgt)
    delta_ram = max(0.0, float(obs.get("sum_h_ram") or 0.0) - h_ram_tgt) if ram_modeled else 0.0
    if n_replicas <= 1:
        return delta_cpu, delta_ram
    if mu <= EPS:
        return params.delta_cpu_min_cores, (params.delta_ram_min_mb if ram_modeled else 0.0)
    if delta_cpu > EPS or delta_ram > EPS:
        return delta_cpu, delta_ram
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
    """Algorithm allocate Up: Vertical (unless sustained) → Horizontal → optional leftover ρ."""
    spec = obs["spec"]
    cluster_id = home_cluster_id(env, ms_id)
    replicas: list[ReplicaView] = home_replicas(env, obs["replicas"], cluster_id)
    actions: list[Any] = []
    remain_cpu, remain_ram = need_cpu, need_ram

    if not sustained and replicas and (need_cpu > EPS or need_ram > EPS):
        bev = distribute_up(
            env=env,
            ms_id=ms_id,
            spec=spec,
            params=params,
            replicas=replicas,
            delta_cpu=need_cpu,
            delta_ram=need_ram,
            tau=tau,
            reason="vertical_up",
        )
        remain_cpu, remain_ram = leftover_from_need_horizontal(bev)
        if not any(getattr(a, "type", "") == "need_horizontal" for a in bev):
            remain_cpu, remain_ram = 0.0, 0.0
        actions.extend(strip_need_horizontal(bev))

    spawns, remain_cpu, remain_ram = horizontal_up(
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
            min_head_cpu=params.delta_cpu_min_cores,
            min_head_ram=params.delta_ram_min_mb,
            t_det=tau,
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
    queued_releases: list | None = None,
) -> tuple[list[Any], ReleaseIntent | list[ReleaseIntent] | None]:
    """Algorithm allocate Down: split ξ first, then Vertical/Horizontal on N_c.

    Extra local replicas: skip vertical shrink of the seed in the same tick as a
    terminate (tex would shrink and kill together). Cascade is Algorithm
    cascade: a different m* comes home via Evict ξ, never m itself.
    """
    spec = obs["spec"]
    replicas: list[ReplicaView] = obs["replicas"]
    ram_modeled = spec.ram_per_request_mb > EPS
    owner = home_cluster_id(env, ms_id)
    local = home_replicas(env, replicas, owner)
    b_cpu, b_ram = borrowed_footprint(env, replicas, owner)
    l_cpu, l_ram, local_cpu, local_ram = split_borrowed_share(
        delta_cpu, delta_ram, b_cpu, b_ram
    )
    xi: ReleaseIntent | None = None
    if l_cpu > EPS or l_ram > EPS:
        xi = ReleaseIntent(
            seq=0,
            tau=tau,
            ms_id=ms_id,
            home_cluster_id=owner,
            remain_cpu=l_cpu,
            remain_ram=l_ram,
            t_det=tau,
            mu_tgt=target_mu(obs, params),
        )

    remain_cpu = local_cpu
    remain_ram = local_ram if ram_modeled else 0.0
    # Extras: reclaim replica count first. Do not vertical-shrink the seed in the
    # same tick as a terminate — that is what left μ too small and bounced UP.
    if len(local) > 1:
        bev: list[Any] = []
    else:
        bev = distribute_down(
            env=env,
            ms_id=ms_id,
            spec=spec,
            params=params,
            replicas=local,
            delta_cpu=remain_cpu,
            delta_ram=remain_ram,
            tau=tau,
            reason="vertical_down",
            mu_tgt=target_mu(obs, params),
        )
        granted_cpu, granted_ram = _granted_down(local, bev)
        remain_cpu = max(0.0, remain_cpu - granted_cpu)
        remain_ram = max(0.0, remain_ram - granted_ram) if ram_modeled else 0.0
    skip_ids = {a.container_id for a in bev}
    terms = horizontal_down(
        env=env,
        replicas=local,
        ms_id=ms_id,
        owner_cluster_id=owner,
        remain_cpu=remain_cpu,
        remain_ram=remain_ram,
        ram_modeled=ram_modeled,
        skip_ids=skip_ids,
        tau=tau,
        spec=spec,
        mu_tgt=target_mu(obs, params),
        n_live=len(replicas),
        fleet_replicas=replicas,
    )
    actions: list[Any] = [*bev, *terms]
    leftovers: list[ReleaseIntent] = []
    if xi is not None:
        leftovers.append(xi)
    if params.cascade_home:
        freed_cpu, freed_ram = _freed_local(env, replicas, actions, owner)
        spawn, evict = check_cascading_migration(
            env,
            shrinking_ms_id=ms_id,
            owner_cluster_id=owner,
            freed_cpu=freed_cpu,
            freed_ram=freed_ram,
            pending=actions,
            tau=tau,
            queued_releases=[*(queued_releases or []), *leftovers],
        )
        actions.extend(spawn)
        if evict is not None:
            leftovers.append(evict)
    if not leftovers:
        return actions, None
    if len(leftovers) == 1:
        return actions, leftovers[0]
    return actions, leftovers


def resolve_help(
    env: Env,
    help_q: list[HelpRequest],
    pending: list[Any],
    tau: int,
    releases: list[ReleaseIntent] | None = None,
) -> list[Any]:
    releases = releases or []
    if env.root is None:
        return [leftover_to_help_action(u) for u in help_q]
    actions, unresolved = schedule_vicinity_help(
        env, help_q, pending=pending, tau=tau, releases=releases
    )
    actions.extend(leftover_to_unmet_demand(u) for u in unresolved)
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
    """Local CPU/RAM released this tick by vertical shrink or local terminate (not loans)."""
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
