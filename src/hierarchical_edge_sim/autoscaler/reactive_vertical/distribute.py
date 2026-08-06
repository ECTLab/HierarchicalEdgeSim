"""Distribute MS-wide vertical deltas across containers."""

from __future__ import annotations

from dataclasses import dataclass

from hierarchical_edge_sim.env.api import Env, NeedHorizontalAction, ResizeAction
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec

from .params import ReactiveVerticalParams


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


def distribute_up(
    *,
    env: Env,
    ms_id: str,
    spec: MicroserviceSpec,
    params: ReactiveVerticalParams,
    replicas: list[ReplicaView],
    delta_cpu: float,
    delta_ram: float,
    tau: int,
) -> list[ResizeAction | NeedHorizontalAction]:
    if not replicas or (delta_cpu <= EPS and delta_ram <= EPS):
        return []

    max_room = max((r.room_up_cpu for r in replicas), default=0.0) or 1.0
    total_drop = sum(r.drop for r in replicas) or 1.0
    w1, w2, w3 = params.grow_weights

    def score(r: ReplicaView) -> tuple[float, str]:
        s = (
            w1 * (r.drop / total_drop)
            + w2 * min(r.q, 1.0)
            + w3 * (r.room_up_cpu / max_room)
        )
        return (-s, r.container_id)  # higher score first; tie-break id asc via sort key

    ranked = sorted(replicas, key=score)
    actions: list[ResizeAction | NeedHorizontalAction] = []
    remain_cpu, remain_ram = delta_cpu, delta_ram

    for r in ranked:
        if remain_cpu <= EPS and remain_ram <= EPS:
            break
        give_cpu = min(remain_cpu, r.room_up_cpu)
        give_ram = min(remain_ram, r.room_up_ram)
        # Keep CPU/RAM paired when both requested
        if delta_cpu > EPS and delta_ram > EPS and give_cpu <= EPS and give_ram <= EPS:
            continue
        if give_cpu <= EPS and give_ram <= EPS:
            continue
        # If one dimension blocked, still apply the other when unconstrained side has room
        new_cpu = r.cpu_alloc + give_cpu
        new_ram = r.ram_alloc + give_ram
        actions.append(
            ResizeAction(
                type="resize",
                ms_id=ms_id,
                container_id=r.container_id,
                cpu_alloc_cores=new_cpu,
                ram_alloc_mb=new_ram,
                reason="reactive_up",
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
    params: ReactiveVerticalParams,
    replicas: list[ReplicaView],
    delta_cpu: float,
    delta_ram: float,
    tau: int,
) -> list[ResizeAction]:
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
            # Prefer shrinking one/few cold replicas
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
        new_cpu = max(spec.cpu_min_cores, r.cpu_alloc - take_cpu)
        new_ram = max(spec.ram_min_mb, r.ram_alloc - take_ram)
        actions.append(
            ResizeAction(
                type="resize",
                ms_id=ms_id,
                container_id=r.container_id,
                cpu_alloc_cores=new_cpu,
                ram_alloc_mb=new_ram,
                reason="reactive_down",
                tau=tau,
            )
        )
        remain_cpu -= r.cpu_alloc - new_cpu
        remain_ram -= r.ram_alloc - new_ram
        if params.prefer_consolidate_down:
            break
    return actions
