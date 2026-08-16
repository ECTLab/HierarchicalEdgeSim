"""Ring buffer of real TTW request counts (history purity)."""

from __future__ import annotations

from collections import deque

from .ttw_rps import counts_to_rps


class RpsHistory:
    """Fixed-capacity buffer of observed TTW request counts (not forecasts)."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self._capacity = capacity
        self._buf: deque[float] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        return self._capacity

    def __len__(self) -> int:
        return len(self._buf)

    def append(self, count: float) -> None:
        self._buf.append(float(count))

    def as_list(self) -> list[float]:
        """Observed request counts in the window."""
        return list(self._buf)

    def as_rps(self, *, ttw_ticks: int, tick_sec: float) -> list[float]:
        return [counts_to_rps(n, ttw_ticks=ttw_ticks, tick_sec=tick_sec) for n in self._buf]

    def is_full(self) -> bool:
        return len(self._buf) >= self._capacity
