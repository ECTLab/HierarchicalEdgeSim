"""Ring buffer of real TTW-average RPS samples (history purity)."""

from __future__ import annotations

from collections import deque


class RpsHistory:
    """Fixed-capacity buffer of observed RPS values only."""

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

    def append(self, rps: float) -> None:
        self._buf.append(float(rps))

    def as_list(self) -> list[float]:
        return list(self._buf)

    def is_full(self) -> bool:
        return len(self._buf) >= self._capacity
