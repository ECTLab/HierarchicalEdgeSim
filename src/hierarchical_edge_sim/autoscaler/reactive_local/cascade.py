"""CheckCascadingMigration (paper Alg. cascade): cross-MS Evict via the leader."""

from __future__ import annotations

from hierarchical_edge_sim.env.api import Env, SpawnAction
from hierarchical_edge_sim.env.config import EPS

from .help import ReleaseIntent
from .horizontal import packed_spawn_size
from .place import rank_servers_in_clusters, snapshot_free, subtract_pending
from .release import cluster_distance


def check_cascading_migration(
    env: Env,
    *,
    shrinking_ms_id: str,
    owner_cluster_id: str,
    freed_cpu: float,
    freed_ram: float,
    pending: list,
    tau: int,
    queued_releases: list | None = None,
) -> tuple[list[SpawnAction], ReleaseIntent | None]:
    """After m shrinks locally, pull at most one borrowed replica of a different m* home.

    Local spawn is queued here (applied with the rest of AllocateResources). The
    remote drop is an Evict ξ for ScheduleReleases — never m itself, never an
    m* already in R_V. Last-replica stays in force.
    """
    queued_ms = {
        str(getattr(item, "ms_id", ""))
        for item in (queued_releases or [])
        if str(getattr(item, "ms_id", ""))
    }
    pending_term = {
        str(getattr(action, "container_id", ""))
        for action in pending
        if getattr(action, "type", "") == "terminate" and getattr(action, "container_id", "")
    }
    choice = _pick_evict(
        env,
        shrinking_ms_id=shrinking_ms_id,
        owner_cluster_id=owner_cluster_id,
        freed_cpu=freed_cpu,
        freed_ram=freed_ram,
        pending_term=pending_term,
        queued_ms=queued_ms,
    )
    if choice is None:
        return [], None
    ms_star, container_id, server_id = choice
    spec = env.get_ms_spec(ms_star)
    free_cpu, free_ram = snapshot_free(env, [owner_cluster_id])
    subtract_pending(env, pending, free_cpu, free_ram)
    ranked = rank_servers_in_clusters(env, [owner_cluster_id], free_cpu)
    spawn: SpawnAction | None = None
    for sid in ranked:
        packed = packed_spawn_size(
            remain_cpu=max(freed_cpu, spec.cpu_min_cores),
            remain_ram=max(freed_ram, spec.ram_min_mb),
            spec=spec,
            free_cpu=free_cpu.get(sid, 0.0),
            free_ram=free_ram.get(sid, 0.0),
            min_head_cpu=0.25,
            min_head_ram=128.0,
        )
        if packed is None:
            continue
        cpu, ram, _head_cpu, _head_ram = packed
        spawn = SpawnAction(
            type="spawn",
            ms_id=ms_star,
            server_id=sid,
            cpu_alloc_cores=cpu,
            ram_alloc_mb=ram,
            reason="cascade_spawn",
            tau=tau,
            actor_cluster_id=owner_cluster_id,
        )
        break
    if spawn is None:
        return [], None
    evict = ReleaseIntent(
        seq=0,
        tau=tau,
        ms_id=ms_star,
        home_cluster_id=owner_cluster_id,
        remain_cpu=0.0,
        remain_ram=0.0,
        t_det=tau,
        kind="evict",
        evict_container_id=container_id,
        evict_server_id=server_id,
    )
    return [spawn], evict


def _pick_evict(
    env: Env,
    *,
    shrinking_ms_id: str,
    owner_cluster_id: str,
    freed_cpu: float,
    freed_ram: float,
    pending_term: set[str],
    queued_ms: set[str],
) -> tuple[str, str, str] | None:
    ranked: list[tuple[float, str, str, str]] = []
    for ms_id in env.list_microservices():
        if env.get_app_owner_cluster_id(ms_id) != owner_cluster_id:
            continue
        if ms_id == shrinking_ms_id or ms_id in queued_ms:
            continue
        spec = env.get_ms_spec(ms_id)
        ram_modeled = spec.ram_per_request_mb > EPS
        if freed_cpu + EPS < spec.cpu_min_cores:
            continue
        if ram_modeled and freed_ram + EPS < spec.ram_min_mb:
            continue
        live = [
            cid
            for cid in env.get_microservice(ms_id).container_ids
            if cid not in pending_term
        ]
        borrowed = []
        for cid in live:
            container = env.get_container(cid)
            cluster_id = env.get_server(container.server_id).cluster_id
            if cluster_id == owner_cluster_id:
                continue
            borrowed.append(cid)
        if not borrowed:
            continue
        if len(live) <= 1:
            continue
        for cid in borrowed:
            container = env.get_container(cid)
            cluster_id = env.get_server(container.server_id).cluster_id
            dist = cluster_distance(env, owner_cluster_id, cluster_id)
            ranked.append((-dist, ms_id, container.server_id, cid))
    if not ranked:
        return None
    ranked.sort()
    _dist, ms_id, server_id, cid = ranked[0]
    return ms_id, cid, server_id
