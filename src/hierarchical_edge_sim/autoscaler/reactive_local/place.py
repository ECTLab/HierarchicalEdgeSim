"""SchedulePlacements (paper Alg. place): grow existing, then packed spawn on N_V."""

from __future__ import annotations

from hierarchical_edge_sim.autoscaler.common.distribute import alloc_serves
from hierarchical_edge_sim.autoscaler.common.mu_scale import remain_to_mu
from hierarchical_edge_sim.env.api import Env, ResizeAction, SpawnAction
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec, quantize_resource

from .help import HelpRequest
from .horizontal import packed_spawn_size
from .release import cluster_distance


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


def rank_placement_servers(
    env: Env,
    members: list[str],
    home_cluster_id: str,
    ms_id: str,
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
    pending: list,
) -> list[str]:
    """N_pref: home, already-hosting, nearer lender, then min(free)."""
    member_set = set(members)
    hosting = _hosting_servers(env, ms_id, member_set, pending)
    sids: list[str] = []
    for cluster_id in members:
        sids.extend(env.get_cluster(cluster_id).server_ids)

    def key(sid: str) -> tuple[int, int, float, float, str, str]:
        cluster_id = env.get_server(sid).cluster_id
        is_home = 0 if cluster_id == home_cluster_id else 1
        has_m = 0 if sid in hosting else 1
        dist = cluster_distance(env, home_cluster_id, cluster_id)
        slack = min(free_cpu.get(sid, 0.0), free_ram.get(sid, 0.0))
        return (is_home, has_m, dist, -slack, cluster_id, sid)

    return sorted(sids, key=key)


def grow_existing_instances(
    env: Env,
    req: HelpRequest,
    *,
    members: list[str],
    pending: list,
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
    tau: int,
) -> tuple[list[ResizeAction], float, float]:
    """Grow hosts of m for c': local before remote, nearer lenders first (Alg. place).

    Amount is a serving-μ step through ρ, capped by post-release free and
    cpu_max/ram_max. Independent wallet fill toward ram_max is not used.
    """
    spec = env.get_ms_spec(req.ms_id)
    ram_modeled = spec.ram_per_request_mb > EPS
    remain_cpu, remain_ram = req.remain_cpu, req.remain_ram
    pending_term = _pending_terminates(pending)
    replicas = _grow_replicas(env, req.ms_id, req.home_cluster_id, members, pending_term)
    actions: list[ResizeAction] = []
    work = list(pending)
    for cid, sid, _cluster_id in replicas:
        if remain_cpu <= EPS and (not ram_modeled or remain_ram <= EPS):
            break
        grown = _grow_one(
            env,
            spec=spec,
            ram_modeled=ram_modeled,
            container_id=cid,
            remain_cpu=remain_cpu,
            remain_ram=remain_ram,
            free_cpu=free_cpu.get(sid, 0.0),
            free_ram=free_ram.get(sid, 0.0),
            pending=work + actions,
        )
        if grown is None:
            continue
        new_cpu, new_ram, give_cpu, give_ram = grown
        actions.append(
            ResizeAction(
                type="resize",
                ms_id=req.ms_id,
                container_id=cid,
                cpu_alloc_cores=new_cpu,
                ram_alloc_mb=new_ram,
                reason="vicinity_up",
                tau=tau,
                actor_cluster_id=req.home_cluster_id,
            )
        )
        free_cpu[sid] = free_cpu.get(sid, 0.0) - give_cpu
        free_ram[sid] = free_ram.get(sid, 0.0) - give_ram
        remain_cpu = max(0.0, remain_cpu - give_cpu)
        remain_ram = max(0.0, remain_ram - give_ram) if ram_modeled else remain_ram
        if remain_cpu <= EPS:
            remain_ram = 0.0
    return actions, remain_cpu, remain_ram


def place_packed_spawns(
    env: Env,
    req: HelpRequest,
    *,
    ranked_servers: list[str],
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
    tau: int,
    reason: str = "vicinity_spawn",
    loan_tier: str = "vicinity",
) -> tuple[list[SpawnAction], float, float]:
    """Place leftover demand as serving replicas (floor + leftover headroom).

    Skip a server that can only fit the deployment floor. Recycle onto home is
    a local spawn (no loan); remote placement keeps the vicinity loan.
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
            on_home = env.get_server(sid).cluster_id == req.home_cluster_id
            actions.append(
                SpawnAction(
                    type="spawn",
                    ms_id=req.ms_id,
                    server_id=sid,
                    cpu_alloc_cores=cpu,
                    ram_alloc_mb=ram,
                    reason="horizontal_spawn" if on_home else reason,
                    tau=tau,
                    actor_cluster_id=req.home_cluster_id,
                    loan_tier="" if on_home else loan_tier,
                )
            )
            free_cpu[sid] -= cpu
            free_ram[sid] -= ram
            remain_cpu = max(0.0, remain_cpu - head_cpu)
            remain_ram = max(0.0, remain_ram - head_ram)
            if remain_cpu <= EPS:
                remain_ram = 0.0
            placed = True
            break
        if not placed:
            break
    return (actions, remain_cpu, remain_ram)


def schedule_placements(
    env: Env,
    requests: list[HelpRequest],
    *,
    members: list[str],
    pending: list,
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
    tau: int,
) -> tuple[list, list[HelpRequest]]:
    """Alg. place over N_V: grow, then packed spawn. Leftover ρ is unmet."""
    actions: list = []
    unmet: list[HelpRequest] = []
    work = list(pending)
    for req in requests:
        grown, remain_cpu, remain_ram = grow_existing_instances(
            env,
            req,
            members=members,
            pending=work,
            free_cpu=free_cpu,
            free_ram=free_ram,
            tau=tau,
        )
        actions.extend(grown)
        work.extend(grown)
        req.remain_cpu = remain_cpu
        req.remain_ram = remain_ram
        if remain_cpu <= EPS and remain_ram <= EPS:
            continue
        ranked = rank_placement_servers(
            env,
            members,
            req.home_cluster_id,
            req.ms_id,
            free_cpu,
            free_ram,
            work,
        )
        placed, remain_cpu, remain_ram = place_packed_spawns(
            env,
            req,
            ranked_servers=ranked,
            free_cpu=free_cpu,
            free_ram=free_ram,
            tau=tau,
        )
        actions.extend(placed)
        work.extend(placed)
        req.remain_cpu = remain_cpu
        req.remain_ram = remain_ram
        if remain_cpu > EPS or remain_ram > EPS:
            unmet.append(req)
    return actions, unmet


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


def _pending_terminates(pending: list) -> set[str]:
    return {
        str(getattr(action, "container_id", ""))
        for action in pending
        if getattr(action, "type", "") == "terminate" and getattr(action, "container_id", "")
    }


def _hosting_servers(env: Env, ms_id: str, members: set[str], pending: list) -> set[str]:
    pending_term = _pending_terminates(pending)
    hosting: set[str] = set()
    for cid in env.get_microservice(ms_id).container_ids:
        if cid in pending_term:
            continue
        sid = env.get_container(cid).server_id
        if env.get_server(sid).cluster_id in members:
            hosting.add(sid)
    for action in pending:
        if getattr(action, "type", "") != "spawn":
            continue
        if str(getattr(action, "ms_id", "")) != ms_id:
            continue
        sid = str(getattr(action, "server_id", "") or "")
        if sid:
            hosting.add(sid)
    return hosting


def _grow_replicas(
    env: Env,
    ms_id: str,
    home_cluster_id: str,
    members: list[str],
    pending_term: set[str],
) -> list[tuple[str, str, str]]:
    member_set = set(members)
    items: list[tuple[str, str, str]] = []
    for cid in env.get_microservice(ms_id).container_ids:
        if cid in pending_term:
            continue
        container = env.get_container(cid)
        sid = container.server_id
        cluster_id = env.get_server(sid).cluster_id
        if cluster_id not in member_set:
            continue
        items.append((cid, sid, cluster_id))

    def key(item: tuple[str, str, str]) -> tuple[int, float, str, str, str]:
        cid, sid, cluster_id = item
        is_home = 0 if cluster_id == home_cluster_id else 1
        dist = cluster_distance(env, home_cluster_id, cluster_id)
        return (is_home, dist, cluster_id, sid, cid)

    return sorted(items, key=key)


def _effective_alloc(env: Env, container_id: str, pending: list) -> tuple[float, float]:
    container = env.get_container(container_id)
    cpu, ram = container.cpu_alloc_cores, container.ram_alloc_mb
    for action in pending:
        if getattr(action, "type", "") != "resize":
            continue
        if str(getattr(action, "container_id", "")) != container_id:
            continue
        if action.cpu_alloc_cores is not None:
            cpu = float(action.cpu_alloc_cores)
        if action.ram_alloc_mb is not None:
            ram = float(action.ram_alloc_mb)
    return cpu, ram


def _grow_one(
    env: Env,
    *,
    spec: MicroserviceSpec,
    ram_modeled: bool,
    container_id: str,
    remain_cpu: float,
    remain_ram: float,
    free_cpu: float,
    free_ram: float,
    pending: list,
) -> tuple[float, float, float, float] | None:
    current_cpu, current_ram = _effective_alloc(env, container_id, pending)
    room_cpu = min(max(0.0, spec.cpu_max_cores - current_cpu), max(0.0, free_cpu))
    room_ram = (
        min(max(0.0, spec.ram_max_mb - current_ram), max(0.0, free_ram)) if ram_modeled else 0.0
    )
    if room_cpu <= EPS and (not ram_modeled or room_ram <= EPS):
        return None
    rho_cpu = spec.cpu_per_request_cores
    rho_ram = spec.ram_per_request_mb
    if rho_cpu <= EPS:
        return None
    add_mu = remain_to_mu(remain_cpu, remain_ram, spec)
    if add_mu <= EPS:
        return None
    mu_cpu = max(0.0, current_cpu - spec.cpu_min_cores) / rho_cpu
    mu_ram = (
        max(0.0, current_ram - spec.ram_min_mb) / rho_ram
        if ram_modeled and rho_ram > EPS
        else add_mu
    )
    room_mu_cpu = room_cpu / rho_cpu
    room_mu_ram = room_ram / rho_ram if ram_modeled and rho_ram > EPS else add_mu
    if ram_modeled and mu_ram + EPS < mu_cpu:
        if remain_ram <= EPS:
            return None
        add_mu = min(add_mu, room_mu_ram)
        give_cpu = 0.0
        give_ram = add_mu * rho_ram
    else:
        spare_ram_mu = max(0.0, mu_ram - mu_cpu) if ram_modeled else add_mu
        add_mu = min(add_mu, room_mu_cpu, spare_ram_mu + room_mu_ram)
        give_cpu = add_mu * rho_cpu
        give_ram = max(0.0, add_mu - spare_ram_mu) * rho_ram if ram_modeled else 0.0
    if add_mu <= EPS:
        return None
    give_cpu = min(give_cpu, room_cpu)
    give_ram = min(give_ram, room_ram) if ram_modeled else 0.0
    new_cpu = quantize_resource(current_cpu + give_cpu)
    new_ram = quantize_resource(current_ram + give_ram if ram_modeled else current_ram)
    if not alloc_serves(new_cpu, new_ram, spec, ram_modeled):
        return None
    if abs(new_cpu - current_cpu) <= EPS and abs(new_ram - current_ram) <= EPS:
        return None
    give_cpu = max(0.0, new_cpu - current_cpu)
    give_ram = max(0.0, new_ram - current_ram) if ram_modeled else 0.0
    if give_cpu <= EPS and give_ram <= EPS:
        return None
    return new_cpu, new_ram, give_cpu, give_ram
