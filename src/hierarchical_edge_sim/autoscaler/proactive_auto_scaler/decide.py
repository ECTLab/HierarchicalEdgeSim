"""PredictAndDecide (paper Algorithm predict / Algorithm 3).

Control shape matches the listing: Up / Down / None + sustained + residuals.
Utilization and residual use serving headroom, not total alloc (floors buy
no μ). Names avoid paper letters that mean something else:

- observed_rps / forecast_rps / peak_rps — not paper r* (predictor index)
- cpu_per_request / ram_per_request — not paper rho (help-request payload)
- headroom_cpu / headroom_ram — not paper H (forecast horizon)
- rps_capacity_* — RPS that fills headroom (no paper name)
- sustained_steps — paper persistence tau (sim tau is the tick)
"""

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
    peak_rps: float
    u_hat_max: float = 0.0


def predict_and_decide(
    *,
    observed_rps: float,
    forecast_rps: Sequence[float],
    A_cpu: float,
    A_ram: float,
    cpu_per_request: float,
    ram_per_request: float,
    tick_sec: float,
    u_meas: float,
    theta_up: float,
    theta_down: float,
    theta_target: float,
    sustained_steps: int,
    cpu_min_cores: float = 0.0,
    ram_min_mb: float = 0.0,
    n_replicas: int = 1,
    headroom_cpu: float | None = None,
    headroom_ram: float | None = None,
    eps: float = EPS,
    trust_forecast: bool = True,
) -> DecideResult:
    """Paper Algorithm 3 gate: Up / Down / None + sustained + residuals.

    Utilization and residual use serving headroom, not total alloc. See
    ``docs/predict-and-decide.md``.
    """
    if tick_sec <= 0:
        raise ValueError("tick_sec must be > 0")
    if n_replicas < 1:
        raise ValueError("n_replicas must be >= 1")
    hats = [max(0.0, float(x)) for x in forecast_rps]
    if not trust_forecast:
        hats = []
    observed_rps = max(0.0, float(observed_rps))
    n = int(n_replicas)
    head_cpu = (
        float(headroom_cpu)
        if headroom_cpu is not None
        else max(0.0, float(A_cpu) - n * float(cpu_min_cores))
    )
    head_ram = (
        float(headroom_ram)
        if headroom_ram is not None
        else max(0.0, float(A_ram) - n * float(ram_min_mb))
    )

    # Floors buy no throughput (env/usage.py). Util and residual use headroom.
    rps_capacity_cpu = (head_cpu / max(cpu_per_request, eps)) / tick_sec
    u_cpu_obs = observed_rps / max(rps_capacity_cpu, eps)
    u_cpu_hats = [h / max(rps_capacity_cpu, eps) for h in hats]

    ram_mode = ram_per_request > eps
    if ram_mode:
        rps_capacity_ram = (head_ram / max(ram_per_request, eps)) / tick_sec
        u_ram_obs = observed_rps / max(rps_capacity_ram, eps)
        u_ram_hats = [h / max(rps_capacity_ram, eps) for h in hats]
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
        sustained = sum(1 for u in u_hats if u >= theta_up) >= sustained_steps

    peak_rps = observed_rps if not hats else max(observed_rps, max(hats))
    a_req_cpu = n * cpu_min_cores + (cpu_per_request * peak_rps * tick_sec) / theta_target
    delta_cpu = a_req_cpu - A_cpu
    if ram_mode:
        a_req_ram = n * ram_min_mb + (ram_per_request * peak_rps * tick_sec) / theta_target
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
        peak_rps=peak_rps,
        u_hat_max=max_u_hat,
    )
