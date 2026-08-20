"""Convert a serving-μ step through per-request costs so CPU and RAM stay matched."""

from __future__ import annotations

from typing import Any, Protocol

from hierarchical_edge_sim.env.config import EPS, MicroserviceSpec


class UpDeltaParams(Protocol):
    delta_cpu_min_cores: float
    alpha_up: float


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

    Rate-limit in μ-space using the CPU wallet (``δ_cpu_min`` / ``α_up · ΣA_cpu``),
    then convert both resources through ρ. Do not floor RAM at ``δ_ram_min`` or
    cap it at ``α_up · ΣA_ram`` — those independent wallets pumped RAM while
    CPU was already binding.
    """
    spec: MicroserviceSpec = obs["spec"]
    rho_cpu = spec.cpu_per_request_cores
    if rho_cpu <= EPS:
        return 0.0, 0.0
    need_mu = float(obs.get("D") or 0.0)
    min_mu = params.delta_cpu_min_cores / rho_cpu
    cap_cpu = params.alpha_up * max(float(obs.get("sum_cpu_alloc") or 0.0), EPS)
    cap_mu = cap_cpu / rho_cpu
    step_mu = min(max(need_mu, min_mu), cap_mu)
    return deltas_for_mu_step(step_mu, spec)
