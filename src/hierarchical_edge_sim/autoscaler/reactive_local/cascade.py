"""CheckCascadingMigration: pull at most one borrowed replica home after local free."""

from __future__ import annotations

from hierarchical_edge_sim.env.api import Env, SpawnAction, TerminateAction
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec
from hierarchical_edge_sim.env.loans import get_loan

from .place import rank_servers_in_clusters, snapshot_free, subtract_pending


def check_cascading_migration(
    env: Env,
    *,
    ms_id: str,
    owner_cluster_id: str,
    spec: MicroserviceSpec,
    freed_cpu: float,
    freed_ram: float,
    pending: list,
    tau: int,
) -> list[SpawnAction | TerminateAction]:
    """If this down tick freed local minima, migrate one still-borrowed replica home.

    Does not change the shrink residual. Apply order is terminate-then-spawn, so a local
    replica must remain or LAST_REPLICA would reject the borrowed terminate.
    """
    if freed_cpu + EPS < spec.cpu_min_cores:
        return []
    if freed_ram + EPS < spec.ram_min_mb:
        return []

    pending_term = {
        getattr(a, "container_id", "")
        for a in pending
        if getattr(a, "type", "") == "terminate"
    }
    borrowed = _borrowed_still_live(env, ms_id, owner_cluster_id, pending_term)
    if borrowed is None:
        return []

    remaining_local = [
        cid
        for cid in env.get_microservice(ms_id).container_ids
        if cid not in pending_term and cid != borrowed and _is_local(env, cid, owner_cluster_id)
    ]
    if not remaining_local:
        return []

    free_cpu, free_ram = snapshot_free(env, [owner_cluster_id])
    subtract_pending(env, pending, free_cpu, free_ram)
    ranked = rank_servers_in_clusters(env, [owner_cluster_id], free_cpu)
    home_sid = None
    for sid in ranked:
        if free_cpu.get(sid, 0.0) + EPS < spec.cpu_min_cores:
            continue
        if free_ram.get(sid, 0.0) + EPS < spec.ram_min_mb:
            continue
        home_sid = sid
        break
    if home_sid is None:
        return []

    return [
        TerminateAction(
            type="terminate",
            ms_id=ms_id,
            container_id=borrowed,
            reason="cascade_terminate",
            tau=tau,
            actor_cluster_id=owner_cluster_id,
        ),
        SpawnAction(
            type="spawn",
            ms_id=ms_id,
            server_id=home_sid,
            cpu_alloc_cores=spec.cpu_min_cores,
            ram_alloc_mb=spec.ram_min_mb,
            reason="cascade_spawn",
            tau=tau,
            actor_cluster_id=owner_cluster_id,
        ),
    ]


def _borrowed_still_live(
    env: Env, ms_id: str, owner_cluster_id: str, pending_term: set[str]
) -> str | None:
    ranked: list[tuple[int, str]] = []
    for cid in env.get_microservice(ms_id).container_ids:
        if cid in pending_term:
            continue
        container = env.get_container(cid)
        server = env.get_server(container.server_id)
        if server.cluster_id == owner_cluster_id:
            continue
        loan = get_loan(server, owner_cluster_id, ms_id)
        ts = loan.ts if loan is not None else 0
        ranked.append((ts, cid))
    if not ranked:
        return None
    ranked.sort()
    return ranked[0][1]


def _is_local(env: Env, container_id: str, owner_cluster_id: str) -> bool:
    sid = env.get_container(container_id).server_id
    return env.get_server(sid).cluster_id == owner_cluster_id
