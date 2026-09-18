"""Convert a serving-μ step through per-request costs so CPU and RAM stay matched."""

from __future__ import annotations

from typing import Any, Protocol

from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec


class UpDeltaParams(Protocol):
    min_mu_step: float


def deltas_for_mu_step(step_mu: float, spec: MicroserviceSpec) -> tuple[float, float]:
    """CPU/RAM wallets for one serving-μ increment (req/tick)."""
    step = max(0.0, step_mu)
    cpu = step * spec.cpu_per_request_cores
    ram = step * spec.ram_per_request_mb if spec.ram_per_request_mb > EPS else 0.0
    return cpu, ram


def remain_to_mu(remain_cpu: float, remain_ram: float, spec: MicroserviceSpec) -> float:
    """μ implied by leftover wallets. One-sided leftover still counts; both → min."""
    mus: list[float] = []
    if spec.cpu_per_request_cores > EPS and remain_cpu > EPS:
        mus.append(remain_cpu / spec.cpu_per_request_cores)
    if spec.ram_per_request_mb > EPS and remain_ram > EPS:
        mus.append(remain_ram / spec.ram_per_request_mb)
    if not mus:
        return 0.0
    return min(mus)


def up_delta(obs: dict[str, Any], params: UpDeltaParams) -> tuple[float, float]:
    """MS-wide CPU/RAM to add this up tick, from one μ step.

    Convert dropped demand through ρ. Floor at ``min_mu_step`` so a tiny D still
    moves; do not cap as a fraction of current alloc. RAM follows the same μ.
    """
    spec: MicroserviceSpec = obs["spec"]
    rho_cpu = spec.cpu_per_request_cores
    if rho_cpu <= EPS:
        return 0.0, 0.0
    need_mu = float(obs.get("D") or 0.0)
    min_mu = max(0.0, float(params.min_mu_step))
    step_mu = max(need_mu, min_mu)
    return deltas_for_mu_step(step_mu, spec)
