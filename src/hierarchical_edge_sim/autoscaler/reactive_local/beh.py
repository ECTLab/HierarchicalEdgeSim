"""In-cluster best-effort horizontal (BEH) for reactive_local."""

from __future__ import annotations

import math

from hierarchical_edge_sim.autoscaler.common.distribute import ReplicaView
from hierarchical_edge_sim.env.api import Env, SpawnAction, TerminateAction
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec


def home_cluster_id(env: Env, ms_id: str) -> str:
    """App-owning cluster (paper stamp). BEH stays inside this cluster; S4 places leftovers."""
    return env.get_app_owner_cluster_id(ms_id)


def rank_servers_for_spawn(env: Env, ms_id: str, cluster_id: str) -> list[str]:
    """Already-hosting servers first, then by free CPU descending, then id."""
    ms = env.get_microservice(ms_id)
    hosting = {env.get_container(cid).server_id for cid in ms.container_ids}
    servers = list(env.get_cluster(cluster_id).server_ids)

    def key(sid: str) -> tuple[int, float, str]:
        free_cpu, _ = env.get_server_free(sid)
        already = 0 if sid in hosting else 1
        return (already, -free_cpu, sid)

    return sorted(servers, key=key)


def n_new_replicas(
    remain_cpu: float,
    remain_ram: float,
    cpu_min: float,
    ram_min: float,
    ram_modeled: bool,
) -> int:
    parts: list[float] = []
    if remain_cpu > EPS and cpu_min > EPS:
        parts.append(remain_cpu / cpu_min)
    if ram_modeled and remain_ram > EPS and ram_min > EPS:
        parts.append(remain_ram / ram_min)
    if not parts:
        return 0
    return max(1, math.ceil(max(parts) - 1e-12))


def beh_up(
    *,
    env: Env,
    ms_id: str,
    spec: MicroserviceSpec,
    cluster_id: str,
    remain_cpu: float,
    remain_ram: float,
    tau: int,
    pending_resize: list,
) -> tuple[list[SpawnAction], float, float]:
    """Spawn at MS minima on home-cluster servers until residual is covered or full."""
    ram_modeled = spec.ram_per_request_mb > EPS
    n_new = n_new_replicas(
        remain_cpu, remain_ram, spec.cpu_min_cores, spec.ram_min_mb, ram_modeled
    )
    if n_new <= 0:
        return ([], remain_cpu, remain_ram)

    free_cpu: dict[str, float] = {}
    free_ram: dict[str, float] = {}
    for sid in env.get_cluster(cluster_id).server_ids:
        fc, fr = env.get_server_free(sid)
        free_cpu[sid] = fc
        free_ram[sid] = fr
    _subtract_pending_resizes(env, pending_resize, free_cpu, free_ram)

    ranked = rank_servers_for_spawn(env, ms_id, cluster_id)
    actions: list[SpawnAction] = []
    for _ in range(n_new):
        placed = False
        for sid in ranked:
            if free_cpu[sid] + EPS < spec.cpu_min_cores:
                continue
            if free_ram[sid] + EPS < spec.ram_min_mb:
                continue
            actions.append(
                SpawnAction(
                    type="spawn",
                    ms_id=ms_id,
                    server_id=sid,
                    cpu_alloc_cores=spec.cpu_min_cores,
                    ram_alloc_mb=spec.ram_min_mb,
                    reason="beh_spawn",
                    tau=tau,
                )
            )
            free_cpu[sid] -= spec.cpu_min_cores
            free_ram[sid] -= spec.ram_min_mb
            remain_cpu = max(0.0, remain_cpu - spec.cpu_min_cores)
            remain_ram = max(0.0, remain_ram - spec.ram_min_mb)
            placed = True
            break
        if not placed:
            break
    return (actions, remain_cpu, remain_ram)


def beh_down(
    *,
    env: Env,
    replicas: list[ReplicaView],
    ms_id: str,
    owner_cluster_id: str,
    remain_cpu: float,
    remain_ram: float,
    ram_modeled: bool,
    skip_ids: set[str],
    tau: int,
) -> list[TerminateAction]:
    """Terminate borrowed replicas first, then coldest local (never the last).

    Full global→vicinity→local order is S6; S4 only prefers any remote loan over local.
    """
    live = [r for r in replicas if r.container_id not in skip_ids]

    def _key(r: ReplicaView) -> tuple[int, float, float, str]:
        sid = r.server_id or env.get_container(r.container_id).server_id
        remote = 0 if env.get_server(sid).cluster_id != owner_cluster_id else 1
        return (remote, r.q, -r.slack, r.container_id)

    ranked = sorted(live, key=_key)
    actions: list[TerminateAction] = []
    n_live = len(replicas)
    for r in ranked:
        if remain_cpu <= EPS and (not ram_modeled or remain_ram <= EPS):
            break
        if n_live - len(actions) <= 1:
            break
        actions.append(
            TerminateAction(
                type="terminate",
                ms_id=ms_id,
                container_id=r.container_id,
                reason="beh_terminate",
                tau=tau,
            )
        )
        remain_cpu = max(0.0, remain_cpu - r.cpu_alloc)
        remain_ram = max(0.0, remain_ram - r.ram_alloc)
    return actions


def _subtract_pending_resizes(
    env: Env,
    pending_resize: list,
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
) -> None:
    for action in pending_resize:
        if getattr(action, "type", "") != "resize":
            continue
        cid = getattr(action, "container_id", "")
        if cid not in env.world.containers:
            continue
        container = env.get_container(cid)
        sid = container.server_id
        if sid not in free_cpu:
            continue
        if action.cpu_alloc_cores is not None:
            free_cpu[sid] -= float(action.cpu_alloc_cores) - container.cpu_alloc_cores
        if action.ram_alloc_mb is not None:
            free_ram[sid] -= float(action.ram_alloc_mb) - container.ram_alloc_mb
