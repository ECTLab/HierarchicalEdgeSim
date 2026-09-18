"""Analytic per-replica user delay (M/M/1 sojourn + topology T_net).

Overflow is still drop-only (no cross-tick backlog). Dropped load and any
replica with λ ≥ μ count as an SLA timeout ``T_slo``. Stable replicas use an
intra-tick M/M/1 sojourn at the observed window rate. ``d(c,c')`` is read as
milliseconds (the same matrix as Algorithm 1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import EPS
from .partition import lookup_distance
from .world import World

MS_PER_SEC = 1000.0


@dataclass(frozen=True, slots=True)
class DelayStats:
    t_net_sec: float
    t_mean_offered_sec: float
    t_p95_offered_sec: float
    t_p99_offered_sec: float
    sla_miss_requests: float


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
        return DelayStats(t_net, 0.0, 0.0, 0.0, 0.0)

    cap = t_net + sla
    tick = float(tick_sec)
    if tick <= 0:
        raise ValueError("tick_sec must be > 0")

    mu_f = float(mu)
    saturated = mu_f <= EPS or offer + EPS >= mu_f
    if saturated:
        return DelayStats(t_net, cap, cap, cap, offer)

    mu_rate = mu_f / tick
    lam_rate = offer / tick
    wait = 1.0 / (mu_rate - lam_rate)
    miss_frac = math.exp(-sla / wait) if wait > 0.0 else 0.0
    mean_sojourn = wait * (1.0 - math.exp(-sla / wait))
    return DelayStats(
        t_net_sec=t_net,
        t_mean_offered_sec=t_net + mean_sojourn,
        t_p95_offered_sec=_clipped_exp_quantile(0.95, wait, sla, t_net),
        t_p99_offered_sec=_clipped_exp_quantile(0.99, wait, sla, t_net),
        sla_miss_requests=offer * miss_frac,
    )


def _clipped_exp_quantile(q: float, wait: float, sla: float, t_net: float) -> float:
    """q-quantile of T_net + min(Exp(mean=wait), T_slo)."""
    x = -wait * math.log(1.0 - q)
    if x >= sla:
        return t_net + sla
    return t_net + x
