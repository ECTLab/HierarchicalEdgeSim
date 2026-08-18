"""Shared packed spawn placement for vicinity help and BEG."""

from __future__ import annotations

from hierarchical_edge_sim.env.api import Env, SpawnAction
from hierarchical_edge_sim.env.config import EPS

from .beh import packed_spawn_size
from .help import HelpRequest


def snapshot_free(env: Env, cluster_ids: list[str]) -> tuple[dict[str, float], dict[str, float]]:
    free_cpu: dict[str, float] = {}
    free_ram: dict[str, float] = {}
    for cluster_id in cluster_ids:
        for sid in env.get_cluster(cluster_id).server_ids:
            fc, fr = env.get_server_free(sid)
            free_cpu[sid] = fc
            free_ram[sid] = fr
    return free_cpu, free_ram


def cluster_free_cpu(env: Env, cluster_id: str, free_cpu: dict[str, float]) -> float:
    return sum(free_cpu.get(sid, 0.0) for sid in env.get_cluster(cluster_id).server_ids)


def rank_servers_in_clusters(
    env: Env,
    cluster_ids: list[str],
    free_cpu: dict[str, float],
) -> list[str]:
    ranked: list[str] = []
    for cluster_id in cluster_ids:
        sids = list(env.get_cluster(cluster_id).server_ids)
        sids.sort(key=lambda sid: (-free_cpu.get(sid, 0.0), sid))
        ranked.extend(sids)
    return ranked


def place_packed_spawns(
    env: Env,
    req: HelpRequest,
    *,
    ranked_servers: list[str],
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
    tau: int,
    reason: str,
    loan_tier: str,
) -> tuple[list[SpawnAction], float, float]:
    """Place leftover demand as serving replicas (floor + headroom), same as BEH.

    Skip a server that can only fit the deployment floor: routing gives it no
    load until a later BEV-up, and a floor-full worker never gets that up.
    """
    spec = env.get_ms_spec(req.ms_id)
    actions: list[SpawnAction] = []
    remain_cpu, remain_ram = req.remain_cpu, req.remain_ram
    while remain_cpu > EPS or remain_ram > EPS:
        placed = False
        for sid in ranked_servers:
            packed = packed_spawn_size(
                remain_cpu=remain_cpu,
                remain_ram=remain_ram,
                spec=spec,
                free_cpu=free_cpu.get(sid, 0.0),
                free_ram=free_ram.get(sid, 0.0),
                min_head_cpu=req.min_head_cpu,
                min_head_ram=req.min_head_ram,
            )
            if packed is None:
                continue
            cpu, ram, head_cpu, head_ram = packed
            actions.append(
                SpawnAction(
                    type="spawn",
                    ms_id=req.ms_id,
                    server_id=sid,
                    cpu_alloc_cores=cpu,
                    ram_alloc_mb=ram,
                    reason=reason,
                    tau=tau,
                    actor_cluster_id=req.home_cluster_id,
                    loan_tier=loan_tier,
                )
            )
            free_cpu[sid] -= cpu
            free_ram[sid] -= ram
            remain_cpu = max(0.0, remain_cpu - head_cpu)
            remain_ram = max(0.0, remain_ram - head_ram)
            placed = True
            break
        if not placed:
            break
    return (actions, remain_cpu, remain_ram)


def subtract_pending(
    env: Env,
    pending: list,
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
) -> None:
    for action in pending:
        kind = getattr(action, "type", "")
        if kind == "resize":
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
        elif kind == "spawn":
            sid = getattr(action, "server_id", "")
            if sid not in free_cpu:
                continue
            cpu = getattr(action, "cpu_alloc_cores", None)
            ram = getattr(action, "ram_alloc_mb", None)
            if cpu is not None:
                free_cpu[sid] -= float(cpu)
            if ram is not None:
                free_ram[sid] -= float(ram)
        elif kind == "terminate":
            cid = getattr(action, "container_id", "")
            if cid not in env.world.containers:
                continue
            container = env.get_container(cid)
            sid = container.server_id
            if sid not in free_cpu:
                continue
            free_cpu[sid] += container.cpu_alloc_cores
            free_ram[sid] += container.ram_alloc_mb
