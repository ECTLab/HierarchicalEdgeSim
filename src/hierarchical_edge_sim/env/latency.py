"""Per-replica user delay: FCFS fluid queue vs a wall-clock SLO.

Traces and scaling still move in ticks (``tick_sec`` seconds of physical time,
usually one minute). Request wait is *not* that tick. A replica serves at
``μ / tick_sec`` requests per second. Leftover work is a real backlog whose
drain time is ``Q / rate`` seconds. A request times out only if its sojourn
would exceed ``sla_timeout_sec`` (default 1 s), not because the next trace
row is a minute later.

``d(c,c')`` is milliseconds (Algorithm 1). ``T = T_net + T_svc + T_queue``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .config import EPS
from .partition import lookup_distance
from .world import World

MS_PER_SEC = 1000.0
_MAX_SEGMENTS = 8


@dataclass(frozen=True, slots=True)
class DelayStats:
    t_net_sec: float
    t_mean_offered_sec: float
    t_p95_offered_sec: float
    t_p99_offered_sec: float
    sla_miss_requests: float
    t_wait_sec: float = 0.0
    t_svc_sec: float = 0.0
    wait_lo_sec: float = 0.0
    wait_hi_sec: float = 0.0
    queue_len: float = 0.0
    served: float = 0.0
    timeout: float = 0.0


@dataclass(frozen=True, slots=True)
class DelayPart:
    """Completed-request sojourn: T_net + T_svc + uniform queue wait [lo, hi]."""

    weight: float
    t_net_sec: float
    t_svc_sec: float
    wait_lo_sec: float
    wait_hi_sec: float


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


def serve_fluid(
    *,
    arrivals: float,
    mu: float,
    tick_sec: float,
    sla_timeout_sec: float,
    t_net_sec: float,
    queue: float,
) -> DelayStats:
    """One tick of FCFS fluid service. ``queue`` is leftover requests (not ticks)."""
    t_net = max(0.0, float(t_net_sec))
    sla = max(0.0, float(sla_timeout_sec))
    offer = max(0.0, float(arrivals))
    q0 = max(0.0, float(queue))
    tick = float(tick_sec)
    if tick <= 0:
        raise ValueError("tick_sec must be > 0")
    mu_tick = max(0.0, float(mu))

    if offer <= EPS and q0 <= EPS:
        return DelayStats(t_net, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    if mu_tick <= EPS:
        timeout = offer + q0
        cap = t_net + sla
        return DelayStats(
            t_net_sec=t_net,
            t_mean_offered_sec=cap,
            t_p95_offered_sec=cap,
            t_p99_offered_sec=cap,
            sla_miss_requests=timeout,
            t_wait_sec=0.0,
            t_svc_sec=0.0,
            wait_lo_sec=0.0,
            wait_hi_sec=0.0,
            queue_len=0.0,
            served=0.0,
            timeout=timeout,
        )

    mu_rate = mu_tick / tick
    lam = offer / tick
    t_svc = 1.0 / mu_rate
    t_q_max = max(0.0, sla - t_net - t_svc)
    k_max = mu_rate * t_q_max

    t = 0.0
    q = min(q0, k_max)
    timeout = max(0.0, q0 - q)
    served = 0.0
    parts: list[DelayPart] = []

    def _wait(level: float) -> float:
        return max(0.0, level) / mu_rate

    def _add_served(mass: float, wait_a: float, wait_b: float) -> None:
        nonlocal served
        if mass <= EPS:
            return
        lo, hi = (wait_a, wait_b) if wait_a <= wait_b else (wait_b, wait_a)
        parts.append(DelayPart(mass, t_net, t_svc, lo, hi))
        served += mass

    for _ in range(_MAX_SEGMENTS):
        remaining = tick - t
        if remaining <= EPS:
            break
        wait_now = _wait(q)

        if q <= EPS and lam <= mu_rate + EPS:
            _add_served(lam * remaining, 0.0, 0.0)
            q = 0.0
            t = tick
            break

        if k_max <= EPS:
            take = min(mu_rate, lam) * remaining
            _add_served(take, 0.0, 0.0)
            timeout += max(0.0, lam - mu_rate) * remaining
            q = 0.0
            t = tick
            break

        if q >= k_max - EPS and lam + EPS >= mu_rate:
            _add_served(mu_rate * remaining, wait_now, wait_now)
            timeout += max(0.0, lam - mu_rate) * remaining
            q = k_max
            t = tick
            break

        if lam > mu_rate + EPS:
            gap = max(0.0, k_max - q)
            dt = remaining if gap <= EPS else min(remaining, gap / (lam - mu_rate))
            q_end = min(k_max, q + (lam - mu_rate) * dt)
            _add_served(mu_rate * dt, wait_now, _wait(q_end))
            q = q_end
            t += dt
            continue

        dt_empty = q / (mu_rate - lam) if (mu_rate - lam) > EPS else remaining
        dt = min(remaining, dt_empty)
        q_end = max(0.0, q + (lam - mu_rate) * dt)
        _add_served(mu_rate * dt, _wait(q_end), wait_now)
        q = q_end
        t += dt

    wait_end = _wait(q)
    # Cap keeps queued sojourns ≤ SLO. Bare service can still miss (T_svc + T_net > T_slo).
    completed_miss = served if (t_net + t_svc > sla + EPS) else 0.0
    miss = timeout + completed_miss
    if not parts:
        return DelayStats(
            t_net_sec=t_net,
            t_mean_offered_sec=0.0,
            t_p95_offered_sec=0.0,
            t_p99_offered_sec=0.0,
            sla_miss_requests=miss,
            t_wait_sec=wait_end,
            t_svc_sec=t_svc,
            wait_lo_sec=0.0,
            wait_hi_sec=0.0,
            queue_len=q,
            served=served,
            timeout=timeout,
        )

    return DelayStats(
        t_net_sec=t_net,
        t_mean_offered_sec=_completed_mean(parts),
        t_p95_offered_sec=mix_offered_quantile(0.95, parts),
        t_p99_offered_sec=mix_offered_quantile(0.99, parts),
        sla_miss_requests=miss,
        t_wait_sec=wait_end,
        t_svc_sec=t_svc,
        wait_lo_sec=min(p.wait_lo_sec for p in parts),
        wait_hi_sec=max(p.wait_hi_sec for p in parts),
        queue_len=q,
        served=served,
        timeout=timeout,
    )


def offered_delay(
    *,
    lambda_in: float,
    mu: float,
    tick_sec: float,
    sla_timeout_sec: float,
    t_net_sec: float,
    queue: float = 0.0,
) -> DelayStats:
    """Delay over one tick, optionally starting from a leftover backlog."""
    return serve_fluid(
        arrivals=lambda_in,
        mu=mu,
        tick_sec=tick_sec,
        sla_timeout_sec=sla_timeout_sec,
        t_net_sec=t_net_sec,
        queue=queue,
    )


def mix_offered_quantile(q: float, parts: list[DelayPart]) -> float:
    """q-quantile of completed sojourns (timeouts are not mixed in)."""
    live = [p for p in parts if p.weight > EPS]
    total = sum(p.weight for p in live)
    if total <= EPS or not live:
        return 0.0
    hi = max(_part_hi(p) for p in live)
    lo = min(_part_lo(p) for p in live)
    if hi <= lo + EPS:
        return hi
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        cdf = sum(p.weight * _part_cdf(mid, p) for p in live) / total
        if cdf < q:
            lo = mid
        else:
            hi = mid
    return hi


def _part_lo(part: DelayPart) -> float:
    return part.t_net_sec + part.t_svc_sec + min(part.wait_lo_sec, part.wait_hi_sec)


def _part_hi(part: DelayPart) -> float:
    return part.t_net_sec + part.t_svc_sec + max(part.wait_lo_sec, part.wait_hi_sec)


def _part_cdf(t: float, part: DelayPart) -> float:
    lo = _part_lo(part)
    hi = _part_hi(part)
    if t < lo:
        return 0.0
    if t >= hi or hi <= lo + EPS:
        return 1.0 if t >= lo else 0.0
    return (t - lo) / (hi - lo)


def _completed_mean(parts: list[DelayPart]) -> float:
    live = [p for p in parts if p.weight > EPS]
    total = sum(p.weight for p in live)
    if total <= EPS:
        return 0.0
    acc = 0.0
    for p in live:
        acc += p.weight * (p.t_net_sec + p.t_svc_sec + 0.5 * (p.wait_lo_sec + p.wait_hi_sec))
    return acc / total
