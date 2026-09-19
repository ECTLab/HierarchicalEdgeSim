"""Convert a serving-μ step through per-request costs so CPU and RAM stay matched."""

from __future__ import annotations

import math
from typing import Any, Protocol

from hierarchical_edge_sim.env.config import DEFAULT_SLA_TIMEOUT_SEC, EPS, MicroserviceSpec

# M/M/1 sojourn is Exp(μ−λ). P99 wait = this times 1/(μ−λ).
_LN_P99 = -math.log(0.01)


class UpDeltaParams(Protocol):
    min_mu_step: float


class TargetMuParams(Protocol):
    theta_free: float
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


def target_mu(obs: dict[str, Any], params: TargetMuParams) -> float:
    """Surplus-down serving-μ hold.

    Relative slack ``Λ / (1 − θ_free)`` is not enough on a tiny leftover: M/M/1
    p99 wait is ``−ln(0.01) / (μ − Λ)`` (req/tick at tick_sec=1). At Λ=5 and
    θ_free=0.35 that is μ≈7.7, p99≈1.5 s, which misses a 1 s SLA even though
    utilization is only 62%. Floor leftover μ at:

    * one ``min_mu_step`` (a leftover replica is a real serving quantum), and
    * enough absolute headroom that M/M/1 p99 sojourn is at most ``T_slo / 2``.
    """
    load = max(0.0, float(obs.get("Lambda") or 0.0))
    q_tgt = min(max(1.0 - float(params.theta_free), EPS), 1.0)
    mu_util = load / q_tgt
    if load <= EPS:
        return mu_util
    mu_step = max(0.0, float(params.min_mu_step))
    tick = float(obs.get("tick_sec") or 1.0)
    sla = float(obs.get("sla_timeout_sec") or DEFAULT_SLA_TIMEOUT_SEC)
    mu_slo = 0.0
    if sla > EPS and tick > 0.0:
        mu_slo = load + _LN_P99 * tick / (0.5 * sla)
    return max(mu_util, mu_step, mu_slo)


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
