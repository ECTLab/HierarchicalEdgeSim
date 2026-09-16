"""Lender Reserve_c and per-worker safe_j (paper Eq. reserve / Eq. safe)."""

from __future__ import annotations

from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.config import EPS

from .help import HelpRequest
from .place import snapshot_free, subtract_pending


def member_safe_ceilings(
    env: Env,
    members: list[str],
    pending: list,
    requests: list[HelpRequest],
) -> tuple[dict[str, float], dict[str, float]]:
    """Post-local safe_j: leftover own ρ is reserved, not offered to the group.

    ``safe_j = f_j * max(0, 1 - Reserve_c / F_c)`` per resource, with F_c the
    cluster's post-local free. Empty-offer members have Reserve=0 so safe=free.
    """
    free_cpu, free_ram = snapshot_free(env, members)
    subtract_pending(env, pending, free_cpu, free_ram)
    reserve_cpu = {cluster_id: 0.0 for cluster_id in members}
    reserve_ram = {cluster_id: 0.0 for cluster_id in members}
    member_set = set(members)
    for req in requests:
        if req.home_cluster_id not in member_set:
            continue
        reserve_cpu[req.home_cluster_id] += max(0.0, req.remain_cpu)
        reserve_ram[req.home_cluster_id] += max(0.0, req.remain_ram)
    safe_cpu: dict[str, float] = {}
    safe_ram: dict[str, float] = {}
    for cluster_id in members:
        sids = list(env.get_cluster(cluster_id).server_ids)
        total_cpu = sum(free_cpu.get(sid, 0.0) for sid in sids)
        total_ram = sum(free_ram.get(sid, 0.0) for sid in sids)
        factor_cpu = 0.0 if total_cpu <= EPS else max(0.0, 1.0 - reserve_cpu[cluster_id] / total_cpu)
        factor_ram = 0.0 if total_ram <= EPS else max(0.0, 1.0 - reserve_ram[cluster_id] / total_ram)
        for sid in sids:
            safe_cpu[sid] = max(0.0, free_cpu.get(sid, 0.0) * factor_cpu)
            safe_ram[sid] = max(0.0, free_ram.get(sid, 0.0) * factor_ram)
    return safe_cpu, safe_ram
