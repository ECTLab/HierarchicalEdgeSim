"""Analytic per-replica user delay (M/M/1 sojourn + topology T_net).

Overflow is still drop-only (no cross-tick backlog). Dropped load is an SLA
timeout ``T_slo``. A replica that is full but still serving is modeled at
``RHO_CAP`` (not infinite wait). ``d(c,c')`` is milliseconds (Algorithm 1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import EPS
from .partition import lookup_distance
from .world import World

MS_PER_SEC = 1000.0
RHO_CAP = 0.99


@dataclass(frozen=True, slots=True)
class DelayStats:
    t_net_sec: float
    t_mean_offered_sec: float
    t_p95_offered_sec: float
    t_p99_offered_sec: float
    sla_miss_requests: float
    t_wait_sec: float = 0.0


@dataclass(frozen=True, slots=True)
class DelayPart:
    """One replica's offered-load mix: served Exp(wait) plus drops at T_slo."""

    weight: float
    t_net_sec: float
    wait_sec: float
    served_frac: float
    sla_timeout_sec: float


def network_delay_sec(distance_ms: float | None) -> float:
    """Convert topology distance (milliseconds) to seconds."""
    if distance_ms is None:
        return 0.0
    return max(0.0, float(distance_ms)) / MS_PER_SEC


def origin_to_replica_delay_sec(
    world: World,
    origin_cluster_id: str | None,
    replica_cluster_id: str,
) -> float:
    """T_net for clients at the app home cluster. Zero if no distance matrix."""
    if not origin_cluster_id or origin_cluster_id == replica_cluster_id:
        return 0.0
    root = world.root
    if root is None or root.distances is None:
        return 0.0
    return network_delay_sec(lookup_distance(root.distances, origin_cluster_id, replica_cluster_id))


def offered_delay(
    *,
    lambda_in: float,
    mu: float,
    tick_sec: float,
    sla_timeout_sec: float,
    t_net_sec: float,
) -> DelayStats:
    """Delay stats over offered load (timeouts included; not survivor-only)."""
    t_net = max(0.0, float(t_net_sec))
    sla = max(0.0, float(sla_timeout_sec))
    offer = float(lambda_in)
    if offer <= EPS:
        return DelayStats(t_net, 0.0, 0.0, 0.0, 0.0, 0.0)

    cap = t_net + sla
    tick = float(tick_sec)
    if tick <= 0:
        raise ValueError("tick_sec must be > 0")

    mu_f = float(mu)
    if mu_f <= EPS:
        return DelayStats(t_net, cap, cap, cap, offer, 0.0)

    served = min(offer, mu_f)
    dropped = offer - served
    served_frac = served / offer
    rho = min(served / mu_f, RHO_CAP)
    mu_rate = mu_f / tick
    wait = 1.0 / (mu_rate * (1.0 - rho))
    part = DelayPart(offer, t_net, wait, served_frac, sla)
    mean_served = wait * (1.0 - math.exp(-sla / wait))
    mean = t_net + served_frac * mean_served + (1.0 - served_frac) * sla
    tail = math.exp(-sla / wait)
    return DelayStats(
        t_net_sec=t_net,
        t_mean_offered_sec=mean,
        t_p95_offered_sec=mix_offered_quantile(0.95, [part]),
        t_p99_offered_sec=mix_offered_quantile(0.99, [part]),
        sla_miss_requests=dropped + served * tail,
        t_wait_sec=wait,
    )


def mix_offered_quantile(q: float, parts: list[DelayPart]) -> float:
    """q-quantile of the offered-load mix across replicas (timeouts included)."""
    live = [p for p in parts if p.weight > EPS]
    total = sum(p.weight for p in live)
    if total <= EPS or not live:
        return 0.0
    hi = max(p.t_net_sec + p.sla_timeout_sec for p in live)
    lo = 0.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        cdf = sum(p.weight * _part_cdf(mid, p) for p in live) / total
        if cdf < q:
            lo = mid
        else:
            hi = mid
    return hi


def _part_cdf(t: float, part: DelayPart) -> float:
    cap = part.t_net_sec + part.sla_timeout_sec
    if t >= cap:
        return 1.0
    if t < part.t_net_sec:
        return 0.0
    if part.served_frac <= EPS or part.wait_sec <= EPS:
        return 0.0
    x = t - part.t_net_sec
    return part.served_frac * (1.0 - math.exp(-x / part.wait_sec))
