"""Request distribution across microservice containers."""

from __future__ import annotations

from typing import Any

from .config import EPS
from .models import Container


def effective_theta_route(sim_theta_route: float, autoscaler: Any | None) -> float:
    """Prefer-local util cap: reactive ``theta_high`` when a scaler is attached.

    Env-only runs keep ``sim.theta_route`` (default 1.0 = fill home to μ).
    ``proactive_auto_scaler`` has no top-level ``theta_high``, so it stays on
    ``sim.theta_route`` unless YAML set one.
    """
    if autoscaler is not None:
        params = getattr(autoscaler, "params", None)
        high = getattr(params, "theta_high", None) if params is not None else None
        if high is not None:
            return float(high)
    return float(sim_theta_route)


def distribute(
    offer_lambda: float,
    containers: list[Container],
    cpu_min_cores: float,
    *,
    home_ids: set[str] | None = None,
    mu: dict[str, float] | None = None,
    theta_route: float = 1.0,
) -> dict[str, float]:
    """Distribute incoming load across containers.

    Prefer-local (when ``home_ids`` is set and both home and remote replicas
    exist): fill home serving capacity up to ``theta_route · μ``, send leftover
    to non-home replicas, and only use the remaining home band if loans are
    already at full μ (so overflow still lands on home instead of extra drops).
    Within each pool, weights are μ when provided, else CPU serving headroom.
    If total headroom/μ in a pool is zero, equal share.

    ``theta_route=1`` is fill-home-to-μ (paper prefer-local). ``< 1`` keeps
    home below saturation while spare loan μ exists, which is what M/M/1
    delay needs.

    Without ``home_ids`` (single pool): CPU-headroom weighted, matching the
    Part A lock for same-cluster fleets.
    """
    if not containers:
        raise ValueError("containers list must not be empty")
    if not (0.0 < float(theta_route) <= 1.0):
        raise ValueError("theta_route must be in (0, 1]")

    offer = float(offer_lambda)
    if len(containers) == 1:
        return {containers[0].id: offer}

    if home_ids is None:
        return _split_weighted(offer, containers, cpu_min_cores, mu)

    home = [c for c in containers if c.id in home_ids]
    remote = [c for c in containers if c.id not in home_ids]
    if not home or not remote:
        return _split_weighted(offer, containers, cpu_min_cores, mu)

    mu_map = mu or {}
    home_cap = sum(max(0.0, float(mu_map.get(c.id, 0.0))) for c in home)
    remote_cap = sum(max(0.0, float(mu_map.get(c.id, 0.0))) for c in remote)

    if home_cap <= EPS and remote_cap <= EPS:
        return _split_weighted(offer, containers, cpu_min_cores, mu)

    home_offer, remote_offer = _prefer_local_offers(
        offer, home_cap, remote_cap, float(theta_route)
    )
    shares = {c.id: 0.0 for c in containers}
    if home_offer > EPS:
        shares.update(_split_weighted(home_offer, home, cpu_min_cores, mu))
    if remote_offer > EPS:
        shares.update(_split_weighted(remote_offer, remote, cpu_min_cores, mu))
    return shares


def _prefer_local_offers(
    offer: float,
    home_cap: float,
    remote_cap: float,
    theta_route: float,
) -> tuple[float, float]:
    """(home_offer, remote_offer) with a safe local cap, then full remote μ.

    1. Home up to ``theta_route · μ_home``.
    2. Remote up to full ``μ_remote`` (loans exist to take the spill).
    3. Remaining home band only if remotes are full — avoids dropping while
       home still has unused μ.
    4. Any leftover stays on remote (usage drops it) unless remote μ is 0,
       in which case it returns to home (μ=0 loans must not eat overflow).
    """
    remain = float(offer)
    home = 0.0
    remote = 0.0
    home_safe = max(0.0, float(home_cap)) * float(theta_route)

    take = min(remain, home_safe)
    home += take
    remain -= take

    if remote_cap > EPS:
        take = min(remain, remote_cap)
        remote += take
        remain -= take

    take = min(remain, max(0.0, home_cap - home))
    home += take
    remain -= take

    if remain > EPS:
        if remote_cap > EPS:
            remote += remain
        else:
            home += remain
    return home, remote


def _split_weighted(
    offer: float,
    containers: list[Container],
    cpu_min_cores: float,
    mu: dict[str, float] | None,
) -> dict[str, float]:
    if len(containers) == 1:
        return {containers[0].id: float(offer)}

    if mu is not None:
        weights = {c.id: max(0.0, float(mu.get(c.id, 0.0))) for c in containers}
        total = sum(weights.values())
        if total > EPS:
            return {cid: (w / total) * offer for cid, w in weights.items()}

    headrooms = {c.id: max(0.0, c.cpu_alloc_cores - cpu_min_cores) for c in containers}
    total_headroom = sum(headrooms.values())
    if total_headroom > EPS:
        return {cid: (h / total_headroom) * offer for cid, h in headrooms.items()}

    equal_share = offer / len(containers)
    return {c.id: equal_share for c in containers}
