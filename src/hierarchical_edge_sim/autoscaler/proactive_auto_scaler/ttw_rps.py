"""TTW request-count accumulation and RPS conversion."""

from __future__ import annotations


def counts_to_rps(n_requests: float, *, ttw_ticks: int, tick_sec: float) -> float:
    """Convert total request counts over a TTW into average RPS."""
    if ttw_ticks < 1:
        raise ValueError("ttw_ticks must be >= 1")
    if tick_sec <= 0:
        raise ValueError("tick_sec must be > 0")
    return float(n_requests) / (ttw_ticks * tick_sec)


def is_ttw_close(tau: int, ttw_ticks: int) -> bool:
    """True when tick tau closes a TTW (1-based tau, close when tau % L == 0)."""
    if ttw_ticks < 1:
        raise ValueError("ttw_ticks must be >= 1")
    return tau > 0 and tau % ttw_ticks == 0


def ttw_index(tau: int, ttw_ticks: int) -> int:
    """Origin TTW index t = tau // L for a closed TTW."""
    if not is_ttw_close(tau, ttw_ticks):
        raise ValueError(f"tau={tau} does not close a TTW of length {ttw_ticks}")
    return tau // ttw_ticks
