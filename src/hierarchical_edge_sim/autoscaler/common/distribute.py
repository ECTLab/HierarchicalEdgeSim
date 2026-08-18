"""Distribute MS-wide vertical deltas across containers (shared BEV packing)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from hierarchical_edge_sim.env.api import Env, NeedHorizontalAction, ResizeAction
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec, quantize_resource


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
        if remain_cpu <= EPS and remain_ram <= EPS:
            break
        give_cpu = min(remain_cpu, r.room_up_cpu)
        give_ram = min(remain_ram, r.room_up_ram)
        if delta_cpu > EPS and delta_ram > EPS and give_cpu <= EPS and give_ram <= EPS:
            continue
        if give_cpu <= EPS and give_ram <= EPS:
            continue
        new_cpu = quantize_resource(r.cpu_alloc + give_cpu)
        new_ram = quantize_resource(r.ram_alloc + give_ram)
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
        remain_cpu -= give_cpu
        remain_ram -= give_ram

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
) -> list[ResizeAction]:
    _ = env
    if not replicas or (delta_cpu <= EPS and delta_ram <= EPS):
        return []

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
        new_cpu = quantize_resource(max(spec.cpu_min_cores, r.cpu_alloc - take_cpu))
        new_ram = quantize_resource(max(spec.ram_min_mb, r.ram_alloc - take_ram))
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
        remain_cpu -= r.cpu_alloc - new_cpu
        remain_ram -= r.ram_alloc - new_ram
        if params.prefer_consolidate_down:
            break
    return actions


def alloc_serves(cpu_alloc: float, ram_alloc: float, spec: MicroserviceSpec, ram_modeled: bool) -> bool:
    """μ>0 iff both resources sit strictly above the deployment floor."""
    if cpu_alloc <= spec.cpu_min_cores + EPS:
        return False
    if ram_modeled and ram_alloc <= spec.ram_min_mb + EPS:
        return False
    return True


def replica_mu(replica: ReplicaView, spec: MicroserviceSpec, ram_modeled: bool) -> float:
    """Serving capacity of one replica (req/tick). Binding resource is the min."""
    if spec.cpu_per_request_cores <= EPS:
        mu_cpu = 0.0
    else:
        mu_cpu = max(0.0, replica.cpu_alloc - spec.cpu_min_cores) / spec.cpu_per_request_cores
    if not ram_modeled or spec.ram_per_request_mb <= EPS:
        return mu_cpu
    mu_ram = max(0.0, replica.ram_alloc - spec.ram_min_mb) / spec.ram_per_request_mb
    return min(mu_cpu, mu_ram)


def leftover_from_need_horizontal(actions: list) -> tuple[float, float]:
    """Return residual cores/MB from a BEV leftover signal, else (0, 0)."""
    for action in actions:
        if getattr(action, "type", "") == "need_horizontal":
            return (
                float(getattr(action, "residual_cpu_cores", 0.0) or 0.0),
                float(getattr(action, "residual_ram_mb", 0.0) or 0.0),
            )
    return (0.0, 0.0)


def strip_need_horizontal(actions: list) -> list:
    return [a for a in actions if getattr(a, "type", "") != "need_horizontal"]
