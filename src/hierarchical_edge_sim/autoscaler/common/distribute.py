"""Distribute MS-wide vertical deltas across containers (shared VerticalScaling packing)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from hierarchical_edge_sim.env.api import Env, NeedHorizontalAction, ResizeAction
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec, quantize_resource

from .mu_scale import remain_to_mu


class DistributeParams(Protocol):
    grow_weights: tuple[float, float, float]
    shrink_weights: tuple[float, float, float]
    eps_drop: float
    prefer_consolidate_down: bool
    theta_free: float


@dataclass(slots=True)
class ReplicaView:
    container_id: str
    drop: float
    q: float
    slack: float
    cpu_alloc: float
    ram_alloc: float
    room_up_cpu: float
    room_up_ram: float
    room_down_cpu: float
    room_down_ram: float
    server_id: str = ""


def distribute_up(
    *,
    env: Env,
    ms_id: str,
    spec: MicroserviceSpec,
    params: DistributeParams,
    replicas: list[ReplicaView],
    delta_cpu: float,
    delta_ram: float,
    tau: int,
    reason: str = "reactive_up",
) -> list[ResizeAction | NeedHorizontalAction]:
    _ = env
    if not replicas or (delta_cpu <= EPS and delta_ram <= EPS):
        return []

    ram_modeled = spec.ram_per_request_mb > EPS
    rho_cpu = spec.cpu_per_request_cores
    rho_ram = spec.ram_per_request_mb
    max_room = max((r.room_up_cpu for r in replicas), default=0.0) or 1.0
    total_drop = sum(r.drop for r in replicas) or 1.0
    w1, w2, w3 = params.grow_weights

    def score(r: ReplicaView) -> tuple[float, str]:
        s = (
            w1 * (r.drop / total_drop)
            + w2 * min(r.q, 1.0)
            + w3 * (r.room_up_cpu / max_room)
        )
        return (-s, r.container_id)

    ranked = sorted(replicas, key=score)
    actions: list[ResizeAction | NeedHorizontalAction] = []
    remain_cpu, remain_ram = delta_cpu, delta_ram

    for r in ranked:
        if remain_cpu <= EPS and (not ram_modeled or remain_ram <= EPS):
            break
        if rho_cpu <= EPS:
            break
        add_mu = remain_to_mu(remain_cpu, remain_ram, spec)
        if add_mu <= EPS:
            continue
        mu_cpu = max(0.0, r.cpu_alloc - spec.cpu_min_cores) / rho_cpu
        mu_ram = (
            max(0.0, r.ram_alloc - spec.ram_min_mb) / rho_ram
            if ram_modeled and rho_ram > EPS
            else add_mu
        )
        room_mu_cpu = r.room_up_cpu / rho_cpu
        room_mu_ram = (
            r.room_up_ram / rho_ram if ram_modeled and rho_ram > EPS else add_mu
        )
        if ram_modeled and mu_ram + EPS < mu_cpu:
            if remain_ram <= EPS:
                continue
            add_mu = min(add_mu, room_mu_ram)
            give_cpu = 0.0
            give_ram = add_mu * rho_ram
        else:
            spare_ram_mu = max(0.0, mu_ram - mu_cpu) if ram_modeled else add_mu
            add_mu = min(add_mu, room_mu_cpu, spare_ram_mu + room_mu_ram)
            give_cpu = add_mu * rho_cpu
            give_ram = max(0.0, add_mu - spare_ram_mu) * rho_ram if ram_modeled else 0.0
        if add_mu <= EPS:
            continue
        give_cpu = min(give_cpu, r.room_up_cpu)
        give_ram = min(give_ram, r.room_up_ram) if ram_modeled else 0.0
        new_cpu = quantize_resource(r.cpu_alloc + give_cpu)
        new_ram = quantize_resource(r.ram_alloc + give_ram if ram_modeled else r.ram_alloc)
        if not alloc_serves(new_cpu, new_ram, spec, ram_modeled):
            continue
        if abs(new_cpu - r.cpu_alloc) <= EPS and abs(new_ram - r.ram_alloc) <= EPS:
            continue
        actions.append(
            ResizeAction(
                type="resize",
                ms_id=ms_id,
                container_id=r.container_id,
                cpu_alloc_cores=new_cpu,
                ram_alloc_mb=new_ram,
                reason=reason,
                tau=tau,
            )
        )
        remain_cpu = max(0.0, remain_cpu - add_mu * rho_cpu)
        if ram_modeled and rho_ram > EPS:
            remain_ram = max(0.0, remain_ram - add_mu * rho_ram)

    if remain_cpu > EPS or remain_ram > EPS:
        actions.append(
            NeedHorizontalAction(
                type="need_horizontal",
                ms_id=ms_id,
                reason="need_horizontal",
                tau=tau,
                residual_cpu_cores=remain_cpu if remain_cpu > EPS else 0.0,
                residual_ram_mb=remain_ram if remain_ram > EPS else 0.0,
            )
        )
    return actions


def distribute_down(
    *,
    env: Env,
    ms_id: str,
    spec: MicroserviceSpec,
    params: DistributeParams,
    replicas: list[ReplicaView],
    delta_cpu: float,
    delta_ram: float,
    tau: int,
    reason: str = "reactive_down",
    mu_tgt: float | None = None,
) -> list[ResizeAction]:
    _ = env
    if not replicas or (delta_cpu <= EPS and delta_ram <= EPS):
        return []

    ram_modeled = spec.ram_per_request_mb > EPS
    max_room = max((r.room_down_cpu for r in replicas), default=0.0) or 1.0
    w1, w2, w3 = params.shrink_weights

    def score(r: ReplicaView) -> tuple[float, str]:
        no_drop = 1.0 if r.drop <= params.eps_drop else 0.0
        s = w1 * r.slack + w2 * no_drop + w3 * (r.room_down_cpu / max_room)
        return (-s, r.container_id)

    ranked = sorted(replicas, key=score)
    actions: list[ResizeAction] = []
    remain_cpu, remain_ram = delta_cpu, delta_ram

    for r in ranked:
        if params.prefer_consolidate_down and actions:
            if remain_cpu <= EPS and remain_ram <= EPS:
                break
        if remain_cpu <= EPS and remain_ram <= EPS:
            break
        if r.slack + EPS < params.theta_free and r.drop > params.eps_drop:
            continue
        take_cpu = min(remain_cpu, r.room_down_cpu)
        take_ram = min(remain_ram, r.room_down_ram)
        if take_cpu <= EPS and take_ram <= EPS:
            continue
        floor_cpu, floor_ram = _down_floors(spec, ram_modeled, mu_tgt)
        new_cpu = quantize_resource(max(floor_cpu, r.cpu_alloc - take_cpu))
        new_ram = quantize_resource(max(floor_ram, r.ram_alloc - take_ram))
        if abs(new_cpu - r.cpu_alloc) <= EPS and abs(new_ram - r.ram_alloc) <= EPS:
            continue
        old_mu = alloc_mu(r.cpu_alloc, r.ram_alloc, spec, ram_modeled)
        new_mu = alloc_mu(new_cpu, new_ram, spec, ram_modeled)
        if not _accept_down_resize(
            params,
            spec,
            ram_modeled,
            old_mu=old_mu,
            new_mu=new_mu,
            old_cpu=r.cpu_alloc,
            new_cpu=new_cpu,
            old_ram=r.ram_alloc,
            new_ram=new_ram,
        ):
            continue
        actions.append(
            ResizeAction(
                type="resize",
                ms_id=ms_id,
                container_id=r.container_id,
                cpu_alloc_cores=new_cpu,
                ram_alloc_mb=new_ram,
                reason=reason,
                tau=tau,
            )
        )
        remain_cpu -= r.cpu_alloc - new_cpu
        remain_ram -= r.ram_alloc - new_ram
        if params.prefer_consolidate_down:
            break
    return actions


def _down_floors(
    spec: MicroserviceSpec, ram_modeled: bool, mu_tgt: float | None
) -> tuple[float, float]:
    floor_cpu = spec.cpu_min_cores
    floor_ram = spec.ram_min_mb
    if mu_tgt is not None and mu_tgt > EPS:
        if spec.cpu_per_request_cores > EPS:
            floor_cpu = max(floor_cpu, spec.cpu_min_cores + mu_tgt * spec.cpu_per_request_cores)
        if ram_modeled and spec.ram_per_request_mb > EPS:
            floor_ram = max(floor_ram, spec.ram_min_mb + mu_tgt * spec.ram_per_request_mb)
    return floor_cpu, floor_ram


def _accept_down_resize(
    params: DistributeParams,
    spec: MicroserviceSpec,
    ram_modeled: bool,
    *,
    old_mu: float,
    new_mu: float,
    old_cpu: float,
    new_cpu: float,
    old_ram: float,
    new_ram: float,
) -> bool:
    """Apply if μ falls, or a real idle trim of the non-binding resource.

    Tiny RAM-only shaves after the CPU quantum already holds μ are skipped.
    """
    if new_mu + EPS < old_mu:
        return True
    cpu_moved = abs(new_cpu - old_cpu) > EPS
    ram_moved = abs(new_ram - old_ram) > EPS
    if not cpu_moved and not ram_moved:
        return False
    if cpu_moved and ram_moved:
        return True
    min_ram_step = float(getattr(params, "delta_ram_min_mb", 128.0) or 128.0)
    min_cpu_step = float(getattr(params, "delta_cpu_min_cores", 0.25) or 0.25)
    matched_ram = spec.ram_min_mb
    matched_cpu = spec.cpu_min_cores
    if spec.cpu_per_request_cores > EPS:
        matched_cpu = spec.cpu_min_cores + old_mu * spec.cpu_per_request_cores
    if ram_modeled and spec.ram_per_request_mb > EPS:
        matched_ram = spec.ram_min_mb + old_mu * spec.ram_per_request_mb
    if ram_moved and not cpu_moved:
        take = old_ram - new_ram
        if take + EPS >= min_ram_step:
            return True
        return new_ram <= matched_ram + EPS
    take = old_cpu - new_cpu
    if take + EPS >= min_cpu_step:
        return True
    return new_cpu <= matched_cpu + EPS


def alloc_serves(cpu_alloc: float, ram_alloc: float, spec: MicroserviceSpec, ram_modeled: bool) -> bool:
    """μ>0 iff both resources sit strictly above the deployment floor."""
    if cpu_alloc <= spec.cpu_min_cores + EPS:
        return False
    if ram_modeled and ram_alloc <= spec.ram_min_mb + EPS:
        return False
    return True


def alloc_mu(cpu_alloc: float, ram_alloc: float, spec: MicroserviceSpec, ram_modeled: bool) -> float:
    """Serving capacity of one alloc (req/tick). Binding resource is the min."""
    if spec.cpu_per_request_cores <= EPS:
        mu_cpu = 0.0
    else:
        mu_cpu = max(0.0, cpu_alloc - spec.cpu_min_cores) / spec.cpu_per_request_cores
    if not ram_modeled or spec.ram_per_request_mb <= EPS:
        return mu_cpu
    mu_ram = max(0.0, ram_alloc - spec.ram_min_mb) / spec.ram_per_request_mb
    return min(mu_cpu, mu_ram)


def replica_mu(replica: ReplicaView, spec: MicroserviceSpec, ram_modeled: bool) -> float:
    """Serving capacity of one replica (req/tick). Binding resource is the min."""
    return alloc_mu(replica.cpu_alloc, replica.ram_alloc, spec, ram_modeled)


def leftover_from_need_horizontal(actions: list) -> tuple[float, float]:
    """Return residual cores/MB from a vertical leftover signal, else (0, 0)."""
    for action in actions:
        if getattr(action, "type", "") == "need_horizontal":
            return (
                float(getattr(action, "residual_cpu_cores", 0.0) or 0.0),
                float(getattr(action, "residual_ram_mb", 0.0) or 0.0),
            )
    return (0.0, 0.0)


def strip_need_horizontal(actions: list) -> list:
    return [a for a in actions if getattr(a, "type", "") != "need_horizontal"]
