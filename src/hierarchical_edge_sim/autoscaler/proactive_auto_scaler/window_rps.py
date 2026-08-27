"""Decision-window request counts → average RPS.

A window is ``ticks_per_window`` sim ticks — the paper's ClusterManagerCycle
window t. When ``ticks_per_window=1``, one tick is one window (Alibaba).
"""

from __future__ import annotations


def counts_to_rps(n_requests: float, *, ticks_per_window: int, tick_sec: float) -> float:
    """Convert total request counts over a window into average RPS."""
    if ticks_per_window < 1:
        raise ValueError("ticks_per_window must be >= 1")
    if tick_sec <= 0:
        raise ValueError("tick_sec must be > 0")
    return float(n_requests) / (ticks_per_window * tick_sec)


def is_window_close(tau: int, ticks_per_window: int) -> bool:
    """True when tick tau closes a window (1-based tau, close when tau % L == 0)."""
    if ticks_per_window < 1:
        raise ValueError("ticks_per_window must be >= 1")
    return tau > 0 and tau % ticks_per_window == 0


def window_index(tau: int, ticks_per_window: int) -> int:
    """Paper window index t = tau // L for a closed window."""
    if not is_window_close(tau, ticks_per_window):
        raise ValueError(
            f"tau={tau} does not close a window of length {ticks_per_window}"
        )
    return tau // ticks_per_window
