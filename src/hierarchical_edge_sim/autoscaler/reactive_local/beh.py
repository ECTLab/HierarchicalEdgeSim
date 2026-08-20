"""In-cluster best-effort horizontal (BEH) for reactive_local."""

from __future__ import annotations

import math

from hierarchical_edge_sim.autoscaler.common.distribute import ReplicaView, replica_mu
from hierarchical_edge_sim.env.api import Env, SpawnAction, TerminateAction
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec, quantize_resource
from hierarchical_edge_sim.env.loans import get_loan
from hierarchical_edge_sim.env.models import LoanTier


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


def packed_spawn_size(
    *,
    remain_cpu: float,
    remain_ram: float,
    spec: MicroserviceSpec,
    free_cpu: float,
    free_ram: float,
    min_head_cpu: float,
    min_head_ram: float,
) -> tuple[float, float, float, float] | None:
    """Size a spawn as floor + leftover headroom so μ>0, or None if it cannot serve."""
    ram_modeled = spec.ram_per_request_mb > EPS
    if free_cpu + EPS < spec.cpu_min_cores:
        return None
    if free_ram + EPS < spec.ram_min_mb:
        return None
    max_head_cpu = max(0.0, min(spec.cpu_max_cores - spec.cpu_min_cores, free_cpu - spec.cpu_min_cores))
    max_head_ram = max(0.0, min(spec.ram_max_mb - spec.ram_min_mb, free_ram - spec.ram_min_mb))
    head_cpu = min(max(0.0, remain_cpu), max_head_cpu)
    head_ram = min(max(0.0, remain_ram), max_head_ram) if ram_modeled else 0.0
    if head_cpu <= EPS:
        head_cpu = min(max(0.0, min_head_cpu), max_head_cpu)
    if ram_modeled and head_ram <= EPS:
        head_ram = min(max(0.0, min_head_ram), max_head_ram)
    if head_cpu <= EPS:
        return None
    if ram_modeled and head_ram <= EPS:
        return None
    cpu = quantize_resource(spec.cpu_min_cores + head_cpu)
    ram = quantize_resource(spec.ram_min_mb + head_ram if ram_modeled else spec.ram_min_mb)
    head_cpu = quantize_resource(cpu - spec.cpu_min_cores)
    head_ram = quantize_resource(ram - spec.ram_min_mb) if ram_modeled else 0.0
    if cpu > free_cpu + EPS or ram > free_ram + EPS:
        return None
    return cpu, ram, head_cpu, head_ram


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
    min_head_cpu: float = 0.25,
    min_head_ram: float = 128.0,
) -> tuple[list[SpawnAction], float, float]:
    """Pack leftover onto home-cluster spawns above minima so each new replica can serve."""
    if remain_cpu <= EPS and remain_ram <= EPS:
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
    while remain_cpu > EPS or remain_ram > EPS:
        placed = False
        for sid in ranked:
            packed = packed_spawn_size(
                remain_cpu=remain_cpu,
                remain_ram=remain_ram,
                spec=spec,
                free_cpu=free_cpu[sid],
                free_ram=free_ram[sid],
                min_head_cpu=min_head_cpu,
                min_head_ram=min_head_ram,
            )
            if packed is None:
                continue
            cpu, ram, head_cpu, head_ram = packed
            actions.append(
                SpawnAction(
                    type="spawn",
                    ms_id=ms_id,
                    server_id=sid,
                    cpu_alloc_cores=cpu,
                    ram_alloc_mb=ram,
                    reason="beh_spawn",
                    tau=tau,
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
    spec: MicroserviceSpec | None = None,
    mu_tgt: float | None = None,
) -> list[TerminateAction]:
    """Terminate global loans, then vicinity loans, then coldest local (never the last).

    Reason follows the loan rung: ``beg_terminate``, ``vicinity_terminate``, or
    ``beh_terminate``. Unknown remotes (no loan row) are global, same as rank.
    """
    live = [r for r in replicas if r.container_id not in skip_ids]
    fleet_mu = (
        sum(replica_mu(r, spec, ram_modeled) for r in replicas)
        if mu_tgt is not None and spec is not None
        else 0.0
    )

    def _key(r: ReplicaView) -> tuple[int, int, float, float, float, str]:
        mu = replica_mu(r, spec, ram_modeled) if spec is not None else 0.0
        return (*_reclaim_key(env, r, owner_cluster_id, ms_id), mu, r.q, -r.slack, r.container_id)

    ranked = sorted(live, key=_key)
    actions: list[TerminateAction] = []
    n_live = len(replicas)
    for r in ranked:
        if remain_cpu <= EPS and (not ram_modeled or remain_ram <= EPS):
            break
        if n_live - len(actions) <= 1:
            break
        if mu_tgt is not None and spec is not None:
            extra_mu = replica_mu(r, spec, ram_modeled)
            if extra_mu > EPS and fleet_mu - extra_mu + EPS < mu_tgt:
                continue
            fleet_mu = max(0.0, fleet_mu - extra_mu)
        tier, _ = _reclaim_key(env, r, owner_cluster_id, ms_id)
        actions.append(
            TerminateAction(
                type="terminate",
                ms_id=ms_id,
                container_id=r.container_id,
                reason=_reclaim_terminate_reason(tier),
                tau=tau,
            )
        )
        remain_cpu = max(0.0, remain_cpu - r.cpu_alloc)
        remain_ram = max(0.0, remain_ram - r.ram_alloc)
    return actions


def _reclaim_terminate_reason(tier: int) -> str:
    """Stamp terminate with the same rung as spawn: BEG / vicinity / local BEH."""
    if tier == 2:
        return "beh_terminate"
    if tier == 1:
        return "vicinity_terminate"
    return "beg_terminate"


def _reclaim_key(
    env: Env, replica: ReplicaView, owner_cluster_id: str, ms_id: str
) -> tuple[int, int]:
    """(tier, ts): global=0, vicinity=1, local=2; older loan ts first."""
    sid = replica.server_id or env.get_container(replica.container_id).server_id
    server = env.get_server(sid)
    if server.cluster_id == owner_cluster_id:
        return (2, 0)
    loan = get_loan(server, owner_cluster_id, ms_id)
    if loan is not None and loan.tier == LoanTier.VICINITY:
        return (1, loan.ts)
    ts = loan.ts if loan is not None else 0
    return (0, ts)


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
