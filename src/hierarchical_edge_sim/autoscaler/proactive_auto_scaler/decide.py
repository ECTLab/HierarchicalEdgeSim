"""PredictAndDecide: RPS trajectory → Up/Down/None + residuals + sustained (pure)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from hierarchical_edge_sim.env.config import EPS


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class DecideResult:
    direction: Direction
    delta_cpu: float
    delta_ram: float
    sustained: bool
    u_obs: float
    r_star: float


def predict_and_decide(
    *,
    r_t: float,
    r_hat: Sequence[float],
    A_cpu: float,
    A_ram: float,
    rho_cpu: float,
    rho_ram: float,
    tick_sec: float,
    u_meas: float,
    theta_up: float,
    theta_down: float,
    theta_target: float,
    sustained_tau: int,
    cpu_min_cores: float = 0.0,
    ram_min_mb: float = 0.0,
    eps: float = EPS,
) -> DecideResult:
    if tick_sec <= 0:
        raise ValueError("tick_sec must be > 0")
    hats = [max(0.0, float(x)) for x in r_hat]
    r_t = max(0.0, float(r_t))

    c_full_cpu = (A_cpu / max(rho_cpu, eps)) / tick_sec
    u_cpu_obs = r_t / max(c_full_cpu, eps)
    u_cpu_hats = [h / max(c_full_cpu, eps) for h in hats]

    ram_mode = rho_ram > eps
    if ram_mode:
        c_full_ram = (A_ram / max(rho_ram, eps)) / tick_sec
        u_ram_obs = r_t / max(c_full_ram, eps)
        u_ram_hats = [h / max(c_full_ram, eps) for h in hats]
        u_rps = max(u_cpu_obs, u_ram_obs)
        u_hats = [max(uc, ur) for uc, ur in zip(u_cpu_hats, u_ram_hats)]
    else:
        u_rps = u_cpu_obs
        u_hats = u_cpu_hats

    u_obs = max(u_rps, float(u_meas))
    max_u_hat = max(u_hats) if u_hats else 0.0

    if u_obs >= theta_up or max_u_hat >= theta_up:
        direction = Direction.UP
    elif u_obs <= theta_down and max_u_hat <= theta_down:
        direction = Direction.DOWN
    else:
        direction = Direction.NONE

    sustained = False
    if direction is Direction.UP:
        sustained = sum(1 for u in u_hats if u >= theta_up) >= sustained_tau

    r_star = r_t if not hats else max(r_t, max(hats))
    a_req_cpu = cpu_min_cores + (rho_cpu * r_star * tick_sec) / theta_target
    delta_cpu = a_req_cpu - A_cpu
    if ram_mode:
        a_req_ram = ram_min_mb + (rho_ram * r_star * tick_sec) / theta_target
        delta_ram = a_req_ram - A_ram
    else:
        delta_ram = 0.0

    if direction is Direction.UP:
        delta_cpu = max(0.0, delta_cpu)
        delta_ram = max(0.0, delta_ram)
    elif direction is Direction.DOWN:
        delta_cpu = min(0.0, delta_cpu)
        delta_ram = min(0.0, delta_ram)
    else:
        delta_cpu = 0.0
        delta_ram = 0.0

    return DecideResult(
        direction=direction,
        delta_cpu=delta_cpu,
        delta_ram=delta_ram,
        sustained=sustained,
        u_obs=u_obs,
        r_star=r_star,
    )
