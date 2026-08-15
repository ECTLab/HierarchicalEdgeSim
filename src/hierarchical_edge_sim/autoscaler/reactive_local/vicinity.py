"""Vicinity-leader FCFS help (paper VicinityLeaderSchedule, lite)."""

from __future__ import annotations

from dataclasses import dataclass

from hierarchical_edge_sim.env.api import Env, NeedVicinityHelpAction, SpawnAction
from hierarchical_edge_sim.env.config import EPS

from .beh import n_new_replicas


@dataclass(slots=True)
class HelpRequest:
    seq: int
    tau: int
    ms_id: str
    home_cluster_id: str
    remain_cpu: float
    remain_ram: float
    cpu_min: float
    ram_min: float


def schedule_vicinity_help(
    env: Env,
    requests: list[HelpRequest],
    *,
    pending: list,
    tau: int,
) -> tuple[list[SpawnAction], list[HelpRequest]]:
    """One FCFS round per vicinity. Places on non-home members only (S4: no Reserve)."""
    if env.root is None or not requests:
        return ([], list(requests))

    by_vicinity: dict[str, list[HelpRequest]] = {}
    for req in requests:
        vid = env.vicinity_of(req.home_cluster_id)
        by_vicinity.setdefault(vid, []).append(req)

    spawns: list[SpawnAction] = []
    unresolved: list[HelpRequest] = []
    for vid in sorted(by_vicinity):
        queued = sorted(by_vicinity[vid], key=lambda r: (r.seq, r.ms_id))
        members = env.list_vicinity_members(vid)
        free_cpu, free_ram = _vicinity_free(env, members)
        _subtract_pending(env, pending + spawns, free_cpu, free_ram)
        for req in queued:
            placed, req.remain_cpu, req.remain_ram = _place_one(
                env,
                req,
                members=members,
                free_cpu=free_cpu,
                free_ram=free_ram,
                tau=tau,
            )
            spawns.extend(placed)
            if req.remain_cpu > EPS or req.remain_ram > EPS:
                unresolved.append(req)
    return (spawns, unresolved)


def leftover_to_help_action(req: HelpRequest) -> NeedVicinityHelpAction:
    return NeedVicinityHelpAction(
        type="need_vicinity_help",
        ms_id=req.ms_id,
        reason="need_vicinity_help",
        tau=req.tau,
        residual_cpu_cores=req.remain_cpu,
        residual_ram_mb=req.remain_ram,
        cluster_id=req.home_cluster_id,
    )


def _place_one(
    env: Env,
    req: HelpRequest,
    *,
    members: list[str],
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
    tau: int,
) -> tuple[list[SpawnAction], float, float]:
    spec = env.get_ms_spec(req.ms_id)
    ram_modeled = spec.ram_per_request_mb > EPS
    n_new = n_new_replicas(req.remain_cpu, req.remain_ram, req.cpu_min, req.ram_min, ram_modeled)
    ranked = _rank_neighbor_servers(env, members, req.home_cluster_id, free_cpu)
    actions: list[SpawnAction] = []
    remain_cpu, remain_ram = req.remain_cpu, req.remain_ram
    for _ in range(n_new):
        placed = False
        for sid in ranked:
            if free_cpu.get(sid, 0.0) + EPS < req.cpu_min:
                continue
            if free_ram.get(sid, 0.0) + EPS < req.ram_min:
                continue
            actions.append(
                SpawnAction(
                    type="spawn",
                    ms_id=req.ms_id,
                    server_id=sid,
                    cpu_alloc_cores=req.cpu_min,
                    ram_alloc_mb=req.ram_min,
                    reason="vicinity_spawn",
                    tau=tau,
                    actor_cluster_id=req.home_cluster_id,
                    loan_tier="vicinity",
                )
            )
            free_cpu[sid] -= req.cpu_min
            free_ram[sid] -= req.ram_min
            remain_cpu = max(0.0, remain_cpu - req.cpu_min)
            remain_ram = max(0.0, remain_ram - req.ram_min)
            placed = True
            break
        if not placed:
            break
    return (actions, remain_cpu, remain_ram)


def _rank_neighbor_servers(
    env: Env,
    members: list[str],
    home_cluster_id: str,
    free_cpu: dict[str, float],
) -> list[str]:
    """Config member order (skip home), then free CPU descending, then server id."""
    ranked: list[str] = []
    for cluster_id in members:
        if cluster_id == home_cluster_id:
            continue
        sids = list(env.get_cluster(cluster_id).server_ids)
        sids.sort(key=lambda sid: (-free_cpu.get(sid, 0.0), sid))
        ranked.extend(sids)
    return ranked


def _vicinity_free(env: Env, members: list[str]) -> tuple[dict[str, float], dict[str, float]]:
    free_cpu: dict[str, float] = {}
    free_ram: dict[str, float] = {}
    for cluster_id in members:
        for sid in env.get_cluster(cluster_id).server_ids:
            fc, fr = env.get_server_free(sid)
            free_cpu[sid] = fc
            free_ram[sid] = fr
    return free_cpu, free_ram


def _subtract_pending(
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
