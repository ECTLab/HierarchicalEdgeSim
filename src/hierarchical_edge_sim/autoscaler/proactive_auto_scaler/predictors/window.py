"""Option A window helpers: counts ↔ normalized load + time feature."""

from __future__ import annotations

EPS = 1e-12


def normalize_load(count: float, load_min: float, load_max: float) -> float:
    span = max(float(load_max) - float(load_min), EPS)
    return (float(count) - float(load_min)) / span


def denormalize_load(norm: float, load_min: float, load_max: float) -> float:
    span = max(float(load_max) - float(load_min), EPS)
    return float(load_min) + float(norm) * span


def clip_unit(value: float, *, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, float(value)))


def rps_to_count(rps: float, *, tick_sec: float, ttw_ticks: int = 1) -> float:
    return float(rps) * float(ttw_ticks) * float(tick_sec)


def count_to_rps(count: float, *, tick_sec: float, ttw_ticks: int = 1) -> float:
    return float(count) / (float(ttw_ticks) * float(tick_sec))


def time_window(close_time_tick: int, lookback: int) -> list[int]:
    """Inclusive lookback ending at ``close_time_tick`` (Alibaba ``time_tick``)."""
    start = int(close_time_tick) - int(lookback) + 1
    return list(range(start, int(close_time_tick) + 1))


def build_option_a_window(
    counts: list[float],
    time_ticks: list[int],
    *,
    load_min: float,
    load_max: float,
    time_scale: float,
) -> list[list[float]]:
    if len(counts) != len(time_ticks):
        raise ValueError(f"counts ({len(counts)}) and time_ticks ({len(time_ticks)}) differ")
    if not counts:
        raise ValueError("feature window must be non-empty")
    scale = max(float(time_scale), EPS)
    return [
        [
            clip_unit(normalize_load(count, load_min, load_max)),
            float(tick) / scale,
        ]
        for count, tick in zip(counts, time_ticks)
    ]
