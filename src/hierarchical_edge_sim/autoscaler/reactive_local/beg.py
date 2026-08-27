"""Best-Effort Global (paper BEG, lite): leftover after vicinity, outside V_home."""

from __future__ import annotations

from hierarchical_edge_sim.env.api import Env, NeedGlobalHelpAction
from hierarchical_edge_sim.env.config import EPS

from .help import HelpRequest, help_fcfs_key
from .place import (
    cluster_free_cpu,
    place_packed_spawns,
    rank_servers_in_clusters,
    snapshot_free,
    subtract_pending,
)


def schedule_beg(
    env: Env,
    requests: list[HelpRequest],
    *,
    pending: list,
    tau: int,
) -> tuple[list, list[HelpRequest]]:
    """Serialize BEG in this window. Candidates are C minus home minus V_home (no distance/γ)."""
    if env.root is None or not requests:
        return ([], list(requests))

    queued = sorted(requests, key=lambda r: (*help_fcfs_key(r), r.seq))
    clusters = env.list_clusters()
    free_cpu, free_ram = snapshot_free(env, clusters)
    subtract_pending(env, pending, free_cpu, free_ram)

    spawns: list = []
    unresolved: list[HelpRequest] = []
    for req in queued:
        load = {cid: cluster_free_cpu(env, cid, free_cpu) for cid in clusters}
        candidates = env.root.rank_beg_candidates(req.home_cluster_id, load)
        ranked = rank_servers_in_clusters(env, candidates, free_cpu)
        placed, req.remain_cpu, req.remain_ram = place_packed_spawns(
            env,
            req,
            ranked_servers=ranked,
            free_cpu=free_cpu,
            free_ram=free_ram,
            tau=tau,
            reason="beg_spawn",
            loan_tier="global",
        )
        spawns.extend(placed)
        if req.remain_cpu > EPS or req.remain_ram > EPS:
            unresolved.append(req)
    return (spawns, unresolved)


def leftover_to_global_help(req: HelpRequest) -> NeedGlobalHelpAction:
    return NeedGlobalHelpAction(
        type="need_global_help",
        ms_id=req.ms_id,
        reason="need_global_help",
        tau=req.tau,
        residual_cpu_cores=req.remain_cpu,
        residual_ram_mb=req.remain_ram,
        cluster_id=req.home_cluster_id,
    )
