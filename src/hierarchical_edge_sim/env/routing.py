"""Request distribution across microservice containers."""

from __future__ import annotations

from .config import EPS
from .models import Container


def distribute(offer_lambda: float, containers: list[Container], cpu_min_cores: float) -> dict[str, float]:
    """Distribute incoming load across containers using CPU headroom weights.

    Rules (Part A lock):
    - Single container gets all requests.
    - Multi-container weights are proportional to CPU serving headroom:
      h_i = max(0, cpu_alloc_cores_i - cpu_min_cores)
    - If total headroom is effectively zero (<= EPS), fall back to equal share.
    """
    if not containers:
        raise ValueError("containers list must not be empty")

    if len(containers) == 1:
        return {containers[0].id: float(offer_lambda)}

    headrooms = {
        c.id: max(0.0, c.cpu_alloc_cores - cpu_min_cores)
        for c in containers
    }
    total_headroom = sum(headrooms.values())

    if total_headroom > EPS:
        return {cid: (h / total_headroom) * offer_lambda for cid, h in headrooms.items()}

    equal_share = offer_lambda / len(containers)
    return {c.id: equal_share for c in containers}
