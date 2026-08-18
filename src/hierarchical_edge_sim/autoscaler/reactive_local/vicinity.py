"""Vicinity-leader FCFS help (paper VicinityLeaderSchedule, lite)."""

from __future__ import annotations

from hierarchical_edge_sim.env.api import Env, NeedVicinityHelpAction
from hierarchical_edge_sim.env.config import EPS

from .help import HelpRequest
from .place import place_packed_spawns, snapshot_free, subtract_pending

__all__ = ["HelpRequest", "leftover_to_help_action", "schedule_vicinity_help"]


def schedule_vicinity_help(
    env: Env,
    requests: list[HelpRequest],
    *,
    pending: list,
    tau: int,
) -> tuple[list, list[HelpRequest]]:
    """One FCFS round per vicinity. Places on non-home members only (S4: no Reserve)."""
    if env.root is None or not requests:
        return ([], list(requests))

    by_vicinity: dict[str, list[HelpRequest]] = {}
    for req in requests:
        vid = env.vicinity_of(req.home_cluster_id)
        by_vicinity.setdefault(vid, []).append(req)

    spawns: list = []
    unresolved: list[HelpRequest] = []
    for vid in sorted(by_vicinity):
        queued = sorted(by_vicinity[vid], key=lambda r: (r.seq, r.ms_id))
        members = env.list_vicinity_members(vid)
        free_cpu, free_ram = snapshot_free(env, members)
        subtract_pending(env, pending + spawns, free_cpu, free_ram)
        for req in queued:
            ranked = _rank_neighbor_servers(env, members, req.home_cluster_id, free_cpu)
            placed, req.remain_cpu, req.remain_ram = place_packed_spawns(
                env,
                req,
                ranked_servers=ranked,
                free_cpu=free_cpu,
                free_ram=free_ram,
                tau=tau,
                reason="vicinity_spawn",
                loan_tier="vicinity",
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
