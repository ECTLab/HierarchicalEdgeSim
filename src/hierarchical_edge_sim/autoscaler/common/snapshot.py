"""Per-MS replica snapshot for vertical packing (shared by scalers)."""

from __future__ import annotations

from dataclasses import dataclass

from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec


@dataclass(slots=True)
class ReplicaView:
    container_id: str
    server_id: str
    drop: float
    q: float
    slack: float
    cpu_alloc: float
    ram_alloc: float
    room_up_cpu: float
    room_up_ram: float
    room_down_cpu: float
    room_down_ram: float


@dataclass(slots=True)
class MsSnapshot:
    ms_id: str
    spec: MicroserviceSpec
    replicas: list[ReplicaView]
    offered_total: float
    served_total: float
    dropped_total: float
    util_ratio: float
    slack_ratio: float
    A_cpu: float
    A_ram: float
    rho_cpu: float
    rho_ram: float
    tick_sec: float
    u_meas: float
    room_up_cpu: float
    room_up_ram: float
    room_down_cpu: float
    room_down_ram: float


def snapshot_ms(env: Env, ms_id: str, tau: int) -> MsSnapshot:
    """Build a typed MS view including per-replica room (MS max ∩ server free)."""
    ms = env.get_microservice(ms_id)
    spec = env.get_ms_spec(ms_id)
    tick_sec = float(env.world_spec.sim.tick_sec)
    replicas: list[ReplicaView] = []
    sum_in = sum_served = sum_drop = 0.0
    sum_h_cpu = sum_h_ram = 0.0
    sum_used_cpu = sum_used_ram = 0.0
    room_up_cpu = room_up_ram = room_down_cpu = room_down_ram = 0.0
    u_meas = 0.0

    for cid in sorted(ms.container_ids):
        c = env.get_container(cid)
        rec = c.history_at(tau)
        h_cpu = max(0.0, c.cpu_alloc_cores - spec.cpu_min_cores)
        h_ram = max(0.0, c.ram_alloc_mb - spec.ram_min_mb)
        used_cpu = rec.lambda_served * spec.cpu_per_request_cores
        used_ram = rec.lambda_served * spec.ram_per_request_mb

        q_cpu = _clamp_util(rec.q_cpu)
        q_ram = _clamp_util(rec.q_ram)
        q_c = max(q_cpu, q_ram)
        u_meas = max(u_meas, q_cpu, q_ram)
        slack_c = 1.0 - q_c

        free_cpu, free_ram = env.get_server_free(c.server_id)
        rup_cpu = max(0.0, min(spec.cpu_max_cores - c.cpu_alloc_cores, free_cpu))
        rup_ram = max(0.0, min(spec.ram_max_mb - c.ram_alloc_mb, free_ram))
        rdown_cpu = max(0.0, c.cpu_alloc_cores - spec.cpu_min_cores)
        rdown_ram = max(0.0, c.ram_alloc_mb - spec.ram_min_mb)

        replicas.append(
            ReplicaView(
                container_id=cid,
                server_id=c.server_id,
                drop=rec.lambda_dropped,
                q=q_c,
                slack=slack_c,
                cpu_alloc=c.cpu_alloc_cores,
                ram_alloc=c.ram_alloc_mb,
                room_up_cpu=rup_cpu,
                room_up_ram=rup_ram,
                room_down_cpu=rdown_cpu,
                room_down_ram=rdown_ram,
            )
        )
        sum_in += rec.lambda_in
        sum_served += rec.lambda_served
        sum_drop += rec.lambda_dropped
        sum_h_cpu += h_cpu
        sum_h_ram += h_ram
        sum_used_cpu += used_cpu
        sum_used_ram += used_ram
        room_up_cpu += rup_cpu
        room_up_ram += rup_ram
        room_down_cpu += rdown_cpu
        room_down_ram += rdown_ram

    q_cpu = sum_used_cpu / max(sum_h_cpu, EPS)
    if spec.ram_per_request_mb > EPS:
        q_ram = sum_used_ram / max(sum_h_ram, EPS)
        util_ratio = min(max(max(q_cpu, q_ram), 0.0), 1.0)
    else:
        util_ratio = min(max(q_cpu, 0.0), 1.0)

    return MsSnapshot(
        ms_id=ms_id,
        spec=spec,
        replicas=replicas,
        offered_total=sum_in,
        served_total=sum_served,
        dropped_total=sum_drop,
        util_ratio=util_ratio,
        slack_ratio=1.0 - util_ratio,
        A_cpu=sum(r.cpu_alloc for r in replicas),
        A_ram=sum(r.ram_alloc for r in replicas),
        rho_cpu=spec.cpu_per_request_cores,
        rho_ram=spec.ram_per_request_mb,
        tick_sec=tick_sec,
        u_meas=u_meas,
        room_up_cpu=room_up_cpu,
        room_up_ram=room_up_ram,
        room_down_cpu=room_down_cpu,
        room_down_ram=room_down_ram,
    )


def _clamp_util(qv: float) -> float:
    if qv != qv or qv == float("inf"):  # NaN or Inf
        return 1.0
    return min(max(qv, 0.0), 1.0)
