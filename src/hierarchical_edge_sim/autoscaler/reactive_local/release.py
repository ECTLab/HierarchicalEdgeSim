"""ScheduleReleases (paper Alg. release): borrowed scale-down through VicinityRound."""

from __future__ import annotations

from hierarchical_edge_sim.autoscaler.common.distribute import ReplicaView, replica_mu
from hierarchical_edge_sim.env.api import Env, ResizeAction, TerminateAction
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec, quantize_resource

from .help import ReleaseIntent, help_fcfs_key
from .horizontal import replica_cluster_id


def split_borrowed_share(
    delta_cpu: float,
    delta_ram: float,
    borrowed_cpu: float,
    borrowed_ram: float,
) -> tuple[float, float, float, float]:
    """Eq. split: L = min(R, B) per resource; local share is R − L."""
    l_cpu = min(max(0.0, delta_cpu), max(0.0, borrowed_cpu))
    l_ram = min(max(0.0, delta_ram), max(0.0, borrowed_ram))
    return l_cpu, l_ram, max(0.0, delta_cpu - l_cpu), max(0.0, delta_ram - l_ram)


def borrowed_footprint(
    env: Env, replicas: list[ReplicaView], owner_cluster_id: str
) -> tuple[float, float]:
    cpu = ram = 0.0
    for replica in replicas:
        if replica_cluster_id(env, replica) == owner_cluster_id:
            continue
        cpu += replica.cpu_alloc
        ram += replica.ram_alloc
    return cpu, ram


def cluster_distance(env: Env, a: str, b: str) -> float:
    """d(c,c'). 0 when the world has no distance matrix (YAML groups, no coords)."""
    root = env.root
    if root is None or root.distances is None:
        return 0.0
    try:
        return env.distance(a, b)
    except (RuntimeError, KeyError):
        return 0.0


def schedule_releases(
    env: Env,
    intents: list[ReleaseIntent],
    *,
    pending: list,
    tau: int,
) -> list[TerminateAction | ResizeAction]:
    """Terminate farthest lenders first, then shrink leftovers (Alg. release).

    J is N_V \\ N_home. Floor extras (μ=0) are fully releasable even when L is
    smaller than the instance — a minima replica serves nothing in this env.
    Last replica and μ_tgt surplus-down stay in force.
    """
    if env.root is None or not intents:
        return []

    actions: list[TerminateAction | ResizeAction] = []
    queued = sorted(intents, key=lambda item: (*help_fcfs_key(item), item.seq))
    pending_term = _pending_terminates(pending)
    for intent in queued:
        vid = env.vicinity_of(intent.home_cluster_id)
        members = set(env.list_vicinity_members(vid))
        actions.extend(
            _release_one(
                env,
                intent,
                members=members,
                pending_term=pending_term,
                tau=tau,
            )
        )
        pending_term.update(
            a.container_id for a in actions if getattr(a, "type", "") == "terminate"
        )
    return actions


def _release_one(
    env: Env,
    intent: ReleaseIntent,
    *,
    members: set[str],
    pending_term: set[str],
    tau: int,
) -> list[TerminateAction | ResizeAction]:
    spec = env.get_ms_spec(intent.ms_id)
    ram_modeled = spec.ram_per_request_mb > EPS
    remain_cpu, remain_ram = intent.remain_cpu, intent.remain_ram
    replicas = _borrowed_replicas(
        env, intent.ms_id, intent.home_cluster_id, members, pending_term
    )
    if not replicas or (remain_cpu <= EPS and (not ram_modeled or remain_ram <= EPS)):
        return []

    fleet_mu = _fleet_mu(env, intent.ms_id, spec, ram_modeled, pending_term)
    ranked_servers = _rank_lender_servers(env, replicas, intent.home_cluster_id)
    by_server: dict[str, list[ReplicaView]] = {}
    for replica in replicas:
        by_server.setdefault(replica.server_id, []).append(replica)
    for sid in ranked_servers:
        by_server[sid].sort(key=lambda r: r.container_id)

    n_live = _n_live(env, intent.ms_id, pending_term)
    actions: list[TerminateAction | ResizeAction] = []
    for sid in ranked_servers:
        live = [r for r in by_server[sid] if r.container_id not in pending_term]
        for replica in list(live):
            if remain_cpu <= EPS and (not ram_modeled or remain_ram <= EPS):
                return actions
            if n_live <= 1:
                return actions
            extra_mu = replica_mu(replica, spec, ram_modeled)
            floor_extra = extra_mu <= EPS
            if not floor_extra and not _covers_instance(
                remain_cpu, remain_ram, replica, ram_modeled
            ):
                continue
            if intent.mu_tgt is not None and extra_mu > EPS:
                if fleet_mu - extra_mu + EPS < intent.mu_tgt:
                    continue
            actions.append(
                TerminateAction(
                    type="terminate",
                    ms_id=intent.ms_id,
                    container_id=replica.container_id,
                    reason="vicinity_terminate",
                    tau=tau,
                    actor_cluster_id=intent.home_cluster_id,
                )
            )
            pending_term.add(replica.container_id)
            live.remove(replica)
            n_live -= 1
            fleet_mu = max(0.0, fleet_mu - extra_mu)
            remain_cpu = max(0.0, remain_cpu - replica.cpu_alloc)
            remain_ram = max(0.0, remain_ram - replica.ram_alloc)
        if remain_cpu <= EPS and (not ram_modeled or remain_ram <= EPS):
            return actions
        if not live:
            continue
        # Too small for a whole instance: shrink the leftover on this host.
        leftover = _shrink_leftover(
            intent=intent,
            spec=spec,
            ram_modeled=ram_modeled,
            replica=live[0],
            remain_cpu=remain_cpu,
            remain_ram=remain_ram,
            fleet_mu=fleet_mu,
            tau=tau,
        )
        if leftover is None:
            continue
        resize, take_cpu, take_ram, lost_mu = leftover
        actions.append(resize)
        remain_cpu = max(0.0, remain_cpu - take_cpu)
        remain_ram = max(0.0, remain_ram - take_ram)
        fleet_mu = max(0.0, fleet_mu - lost_mu)
        if remain_cpu <= EPS and (not ram_modeled or remain_ram <= EPS):
            return actions
    return actions


def _shrink_leftover(
    *,
    intent: ReleaseIntent,
    spec: MicroserviceSpec,
    ram_modeled: bool,
    replica: ReplicaView,
    remain_cpu: float,
    remain_ram: float,
    fleet_mu: float,
    tau: int,
) -> tuple[ResizeAction, float, float, float] | None:
    take_cpu = min(remain_cpu, max(0.0, replica.cpu_alloc - spec.cpu_min_cores))
    take_ram = (
        min(remain_ram, max(0.0, replica.ram_alloc - spec.ram_min_mb)) if ram_modeled else 0.0
    )
    if take_cpu <= EPS and take_ram <= EPS:
        return None
    new_cpu = quantize_resource(replica.cpu_alloc - take_cpu)
    new_ram = quantize_resource(replica.ram_alloc - take_ram if ram_modeled else replica.ram_alloc)
    if new_cpu + EPS < spec.cpu_min_cores:
        new_cpu = spec.cpu_min_cores
    if ram_modeled and new_ram + EPS < spec.ram_min_mb:
        new_ram = spec.ram_min_mb
    take_cpu = max(0.0, replica.cpu_alloc - new_cpu)
    take_ram = max(0.0, replica.ram_alloc - new_ram) if ram_modeled else 0.0
    if take_cpu <= EPS and take_ram <= EPS:
        return None
    old_mu = replica_mu(replica, spec, ram_modeled)
    new_mu = replica_mu(
        ReplicaView(
            container_id=replica.container_id,
            drop=replica.drop,
            q=replica.q,
            slack=replica.slack,
            cpu_alloc=new_cpu,
            ram_alloc=new_ram,
            room_up_cpu=replica.room_up_cpu,
            room_up_ram=replica.room_up_ram,
            room_down_cpu=max(0.0, new_cpu - spec.cpu_min_cores),
            room_down_ram=max(0.0, new_ram - spec.ram_min_mb),
            server_id=replica.server_id,
        ),
        spec,
        ram_modeled,
    )
    lost_mu = max(0.0, old_mu - new_mu)
    if intent.mu_tgt is not None and lost_mu > EPS and fleet_mu - lost_mu + EPS < intent.mu_tgt:
        return None
    return (
        ResizeAction(
            type="resize",
            ms_id=intent.ms_id,
            container_id=replica.container_id,
            cpu_alloc_cores=new_cpu,
            ram_alloc_mb=new_ram,
            reason="vicinity_down",
            tau=tau,
            actor_cluster_id=intent.home_cluster_id,
        ),
        take_cpu,
        take_ram,
        lost_mu,
    )


def _borrowed_replicas(
    env: Env,
    ms_id: str,
    home_cluster_id: str,
    members: set[str],
    pending_term: set[str],
) -> list[ReplicaView]:
    replicas: list[ReplicaView] = []
    spec = env.get_ms_spec(ms_id)
    for cid in env.get_microservice(ms_id).container_ids:
        if cid in pending_term:
            continue
        container = env.get_container(cid)
        cluster_id = env.get_server(container.server_id).cluster_id
        if cluster_id == home_cluster_id or cluster_id not in members:
            continue
        replicas.append(
            ReplicaView(
                container_id=cid,
                drop=0.0,
                q=0.0,
                slack=1.0,
                cpu_alloc=container.cpu_alloc_cores,
                ram_alloc=container.ram_alloc_mb,
                room_up_cpu=0.0,
                room_up_ram=0.0,
                room_down_cpu=max(0.0, container.cpu_alloc_cores - spec.cpu_min_cores),
                room_down_ram=max(0.0, container.ram_alloc_mb - spec.ram_min_mb),
                server_id=container.server_id,
            )
        )
    return replicas


def _rank_lender_servers(
    env: Env, replicas: list[ReplicaView], home_cluster_id: str
) -> list[str]:
    """Farthest lender cluster first, then server id."""
    seen: list[str] = []
    for replica in replicas:
        if replica.server_id not in seen:
            seen.append(replica.server_id)

    def key(sid: str) -> tuple[float, str, str]:
        cluster_id = env.get_server(sid).cluster_id
        dist = cluster_distance(env, home_cluster_id, cluster_id)
        return (-dist, cluster_id, sid)

    return sorted(seen, key=key)


def _covers_instance(
    remain_cpu: float, remain_ram: float, replica: ReplicaView, ram_modeled: bool
) -> bool:
    if remain_cpu + EPS < replica.cpu_alloc:
        return False
    if ram_modeled and remain_ram + EPS < replica.ram_alloc:
        return False
    return True


def _pending_terminates(pending: list) -> set[str]:
    return {
        getattr(a, "container_id", "")
        for a in pending
        if getattr(a, "type", "") == "terminate" and getattr(a, "container_id", "")
    }


def _n_live(env: Env, ms_id: str, pending_term: set[str]) -> int:
    return sum(
        1 for cid in env.get_microservice(ms_id).container_ids if cid not in pending_term
    )


def _fleet_mu(
    env: Env,
    ms_id: str,
    spec: MicroserviceSpec,
    ram_modeled: bool,
    pending_term: set[str],
) -> float:
    total = 0.0
    for cid in env.get_microservice(ms_id).container_ids:
        if cid in pending_term:
            continue
        container = env.get_container(cid)
        total += replica_mu(
            ReplicaView(
                container_id=cid,
                drop=0.0,
                q=0.0,
                slack=1.0,
                cpu_alloc=container.cpu_alloc_cores,
                ram_alloc=container.ram_alloc_mb,
                room_up_cpu=0.0,
                room_up_ram=0.0,
                room_down_cpu=0.0,
                room_down_ram=0.0,
                server_id=container.server_id,
            ),
            spec,
            ram_modeled,
        )
    return total
