"""Request distribution across microservice containers."""

from __future__ import annotations

from .config import EPS
from .models import Container


def distribute(
    offer_lambda: float,
    containers: list[Container],
    cpu_min_cores: float,
    *,
    home_ids: set[str] | None = None,
    mu: dict[str, float] | None = None,
) -> dict[str, float]:
    """Distribute incoming load across containers.

    Prefer-local (when ``home_ids`` is set and both home and remote replicas
    exist): fill home-cluster serving capacity μ first, send leftover to
    non-home replicas. Within each pool, weights are μ when provided, else
    CPU serving headroom. If total headroom/μ in a pool is zero, equal share.

    Without ``home_ids`` (single pool): CPU-headroom weighted, matching the
    Part A lock for same-cluster fleets.
    """
    if not containers:
        raise ValueError("containers list must not be empty")

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

    if home_cap > EPS:
        home_offer = min(offer, home_cap)
        leftover = offer - home_offer
    else:
        home_offer = 0.0
        leftover = offer

    if leftover > EPS and remote_cap <= EPS:
        home_offer += leftover
        leftover = 0.0

    shares = {c.id: 0.0 for c in containers}
    if home_offer > EPS:
        shares.update(_split_weighted(home_offer, home, cpu_min_cores, mu))
    if leftover > EPS:
        shares.update(_split_weighted(leftover, remote, cpu_min_cores, mu))
    return shares


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
