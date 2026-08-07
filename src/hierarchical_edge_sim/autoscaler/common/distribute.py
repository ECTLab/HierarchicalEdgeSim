"""Vertical packing of MS-wide deltas across containers (shared by scalers)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hierarchical_edge_sim.env.api import Env, NeedHorizontalAction, ResizeAction
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec

from .snapshot import ReplicaView


@dataclass(frozen=True, slots=True)
class DistributeParams:
    eps_drop: float = 1.0e-9
    theta_free: float = 0.35
    prefer_consolidate_down: bool = True
    grow_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)
    shrink_weights: tuple[float, float, float] = (0.5, 0.3, 0.2)


def validate_distribute_params(raw: dict[str, Any] | None) -> DistributeParams:
    data = dict(raw or {})
    grow = _parse_grow_weights(data.pop("grow_weights", None))
    shrink = _parse_shrink_weights(data.pop("shrink_weights", None))
    params = DistributeParams(
        eps_drop=float(data.pop("eps_drop", 1.0e-9)),
        theta_free=float(data.pop("theta_free", 0.35)),
        prefer_consolidate_down=bool(data.pop("prefer_consolidate_down", True)),
        grow_weights=grow,
        shrink_weights=shrink,
    )
    if data:
        raise ValueError(f"unknown distribute params: {sorted(data)}")
    if not (0.0 < params.theta_free <= 1.0):
        raise ValueError("theta_free must be in (0, 1]")
    return params


def distribute_params_from_reactive(params: Any) -> DistributeParams:
    """Build DistributeParams from an object that carries the packing knobs (e.g. ReactiveVerticalParams)."""
    return DistributeParams(
        eps_drop=float(params.eps_drop),
        theta_free=float(params.theta_free),
        prefer_consolidate_down=bool(params.prefer_consolidate_down),
        grow_weights=tuple(params.grow_weights),
        shrink_weights=tuple(params.shrink_weights),
    )


def _parse_grow_weights(val: Any) -> tuple[float, float, float]:
    if val is None:
        return (0.5, 0.3, 0.2)
    if isinstance(val, dict):
        return (float(val["drop"]), float(val["util"]), float(val["room"]))
    if isinstance(val, (list, tuple)) and len(val) == 3:
        return (float(val[0]), float(val[1]), float(val[2]))
    raise ValueError("grow_weights must be {drop,util,room} or a 3-tuple")


def _parse_shrink_weights(val: Any) -> tuple[float, float, float]:
    if val is None:
        return (0.5, 0.3, 0.2)
    if isinstance(val, dict):
        return (float(val["slack"]), float(val["no_drop"]), float(val["room"]))
    if isinstance(val, (list, tuple)) and len(val) == 3:
        return (float(val[0]), float(val[1]), float(val[2]))
    raise ValueError("shrink_weights must be {slack,no_drop,room} or a 3-tuple")


def _ram_mode(spec: MicroserviceSpec) -> bool:
    return spec.ram_per_request_mb > EPS


def _paired_room_norm(r: ReplicaView, *, max_cpu: float, max_ram: float, ram_mode: bool) -> float:
    cpu_n = r.room_up_cpu / max_cpu if max_cpu > EPS else 0.0
    if not ram_mode:
        return cpu_n
    ram_n = r.room_up_ram / max_ram if max_ram > EPS else 0.0
    return min(cpu_n, ram_n)


def _paired_down_norm(r: ReplicaView, *, max_cpu: float, max_ram: float, ram_mode: bool) -> float:
    cpu_n = r.room_down_cpu / max_cpu if max_cpu > EPS else 0.0
    if not ram_mode:
        return cpu_n
    ram_n = r.room_down_ram / max_ram if max_ram > EPS else 0.0
    return min(cpu_n, ram_n)


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
    reason: str = "resize_up",
) -> list[ResizeAction | NeedHorizontalAction]:
    _ = env  # reserved; rooms come from snapshot + local free tracking
    if not replicas or (delta_cpu <= EPS and delta_ram <= EPS):
        return []

    ram_mode = _ram_mode(spec)
    if not ram_mode:
        delta_ram = 0.0

    max_cpu = max((r.room_up_cpu for r in replicas), default=0.0) or 1.0
    max_ram = max((r.room_up_ram for r in replicas), default=0.0) or 1.0
    total_drop = sum(r.drop for r in replicas) or 1.0
    w_drop, w_util, w_room = params.grow_weights

    def score(r: ReplicaView) -> tuple[float, str]:
        room_n = _paired_room_norm(r, max_cpu=max_cpu, max_ram=max_ram, ram_mode=ram_mode)
        s = w_drop * (r.drop / total_drop) + w_util * min(r.q, 1.0) + w_room * room_n
        return (-s, r.container_id)

    ranked = sorted(replicas, key=score)
    actions: list[ResizeAction | NeedHorizontalAction] = []
    remain_cpu, remain_ram = delta_cpu, delta_ram

    # Per-server remaining free (Q1a), seeded from live env free capacity.
    server_free_cpu: dict[str, float] = {}
    server_free_ram: dict[str, float] = {}

    def _server_avail(server_id: str) -> tuple[float, float]:
        if server_id not in server_free_cpu:
            fc, fr = env.get_server_free(server_id)
            server_free_cpu[server_id] = max(0.0, fc)
            server_free_ram[server_id] = max(0.0, fr)
        return server_free_cpu[server_id], server_free_ram[server_id]

    for r in ranked:
        if remain_cpu <= EPS and (not ram_mode or remain_ram <= EPS):
            break

        free_cpu, free_ram = _server_avail(r.server_id)
        avail_cpu = min(r.room_up_cpu, free_cpu)
        avail_ram = min(r.room_up_ram, free_ram)
        give_cpu = min(remain_cpu, avail_cpu) if remain_cpu > EPS else 0.0
        give_ram = min(remain_ram, avail_ram) if ram_mode and remain_ram > EPS else 0.0

        need_cpu = remain_cpu > EPS
        need_ram = ram_mode and remain_ram > EPS
        if need_cpu and need_ram:
            # Both short of target: prefer paired move; if one dim is at its bound, allow the other.
            if give_cpu > EPS and give_ram > EPS:
                pass
            elif give_cpu > EPS and avail_ram <= EPS:
                give_ram = 0.0
            elif give_ram > EPS and avail_cpu <= EPS:
                give_cpu = 0.0
            else:
                continue
        elif need_cpu:
            if give_cpu <= EPS:
                continue
            give_ram = 0.0
        elif need_ram:
            if give_ram <= EPS:
                continue
            give_cpu = 0.0
        else:
            break

        new_cpu = r.cpu_alloc + give_cpu
        new_ram = r.ram_alloc + give_ram
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
        server_free_cpu[r.server_id] = max(0.0, server_free_cpu[r.server_id] - give_cpu)
        server_free_ram[r.server_id] = max(0.0, server_free_ram[r.server_id] - give_ram)

    if remain_cpu > EPS or (ram_mode and remain_ram > EPS):
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
    reason: str = "resize_down",
) -> list[ResizeAction]:
    _ = env
    if not replicas or (delta_cpu <= EPS and delta_ram <= EPS):
        return []

    ram_mode = _ram_mode(spec)
    if not ram_mode:
        delta_ram = 0.0

    max_cpu = max((r.room_down_cpu for r in replicas), default=0.0) or 1.0
    max_ram = max((r.room_down_ram for r in replicas), default=0.0) or 1.0
    w_slack, w_no_drop, w_room = params.shrink_weights

    def score(r: ReplicaView) -> tuple[float, str]:
        no_drop = 1.0 if r.drop <= params.eps_drop else 0.0
        room_n = _paired_down_norm(r, max_cpu=max_cpu, max_ram=max_ram, ram_mode=ram_mode)
        s = w_slack * r.slack + w_no_drop * no_drop + w_room * room_n
        return (-s, r.container_id)

    ranked = sorted(replicas, key=score)
    actions: list[ResizeAction] = []
    remain_cpu, remain_ram = delta_cpu, delta_ram

    for r in ranked:
        if remain_cpu <= EPS and (not ram_mode or remain_ram <= EPS):
            break
        if r.slack + EPS < params.theta_free and r.drop > params.eps_drop:
            continue

        take_cpu = min(remain_cpu, r.room_down_cpu) if remain_cpu > EPS else 0.0
        take_ram = min(remain_ram, r.room_down_ram) if ram_mode and remain_ram > EPS else 0.0

        need_cpu = remain_cpu > EPS
        need_ram = ram_mode and remain_ram > EPS
        if need_cpu and need_ram:
            if take_cpu > EPS and take_ram > EPS:
                pass
            elif take_cpu > EPS and r.room_down_ram <= EPS:
                take_ram = 0.0
            elif take_ram > EPS and r.room_down_cpu <= EPS:
                take_cpu = 0.0
            else:
                continue
        elif need_cpu:
            if take_cpu <= EPS:
                continue
            take_ram = 0.0
        elif need_ram:
            if take_ram <= EPS:
                continue
            take_cpu = 0.0
        else:
            break

        new_cpu = max(spec.cpu_min_cores, r.cpu_alloc - take_cpu)
        new_ram = max(spec.ram_min_mb, r.ram_alloc - take_ram) if take_ram > EPS else r.ram_alloc
        # Recompute actual take after min clamp
        actual_cpu = r.cpu_alloc - new_cpu
        actual_ram = r.ram_alloc - new_ram
        if actual_cpu <= EPS and actual_ram <= EPS:
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
        remain_cpu -= actual_cpu
        remain_ram -= actual_ram
        if params.prefer_consolidate_down:
            break
    return actions
