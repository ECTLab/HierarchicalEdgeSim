"""Option A window helpers: counts ↔ normalized load + time feature."""

from __future__ import annotations

import math

EPS = 1e-12


def normalize_load(count: float, load_min: float, load_max: float) -> float:
    span = max(float(load_max) - float(load_min), EPS)
    return (float(count) - float(load_min)) / span


def denormalize_load(norm: float, load_min: float, load_max: float) -> float:
    span = max(float(load_max) - float(load_min), EPS)
    return float(load_min) + float(norm) * span


def clip_unit(value: float, *, lo: float = 0.0, hi: float = 1.0) -> float:
    return min(hi, max(lo, float(value)))


def rps_to_count(rps: float, *, tick_sec: float, ticks_per_window: int = 1) -> float:
    return float(rps) * float(ticks_per_window) * float(tick_sec)


def count_to_rps(count: float, *, tick_sec: float, ticks_per_window: int = 1) -> float:
    return float(count) / (float(ticks_per_window) * float(tick_sec))


def time_window(close_time_tick: int, lookback: int) -> list[int]:
    """Inclusive lookback ending at ``close_time_tick`` (Alibaba ``time_tick``)."""
    start = int(close_time_tick) - int(lookback) + 1
    return list(range(start, int(close_time_tick) + 1))


def cyclic_minute_features(tick: int, period: int = 60) -> tuple[float, float]:
    """sin/cos of minute-of-hour so tick 0 and tick 60 are the same phase."""
    p = max(int(period), 1)
    angle = 2.0 * math.pi * (int(tick) % p) / float(p)
    return math.sin(angle), math.cos(angle)


def _rebound_rows(
    counts: list[float],
    load_min: float,
    load_max: float,
) -> list[list[float]]:
    span = max(float(load_max) - float(load_min), EPS)
    rows: list[list[float]] = []
    prev: float | None = None
    running_max = 0.0
    for count in counts:
        level = clip_unit((float(count) - float(load_min)) / span)
        if prev is None:
            velocity = 0.0
            running_max = level
        else:
            velocity = level - prev
            running_max = max(running_max, level)
        rows.append([level, velocity, running_max - level])
        prev = level
    return rows


def build_option_a_window(
    counts: list[float],
    time_ticks: list[int],
    *,
    load_min: float,
    load_max: float,
    time_scale: float,
    time_encoding: str = "linear",
    time_period: int | None = None,
) -> list[list[float]]:
    if len(counts) != len(time_ticks):
        raise ValueError(f"counts ({len(counts)}) and time_ticks ({len(time_ticks)}) differ")
    if not counts:
        raise ValueError("feature window must be non-empty")
    encoding = str(time_encoding or "linear")
    if encoding == "rebound":
        # MS_150: level, one-step change, and how far the latest count sits
        # under the max of this lookback. All three are functions of the
        # counts alone, so a drop already in the window can be read as a hole.
        return _rebound_rows(counts, load_min, load_max)
    if encoding == "cyclic_minute":
        period = int(time_period or time_scale or 60)
        rows: list[list[float]] = []
        for count, tick in zip(counts, time_ticks):
            sine, cosine = cyclic_minute_features(int(tick), period)
            rows.append(
                [
                    clip_unit(normalize_load(count, load_min, load_max)),
                    sine,
                    cosine,
                ]
            )
        return rows
    scale = max(float(time_scale), EPS)
    return [
        [
            clip_unit(normalize_load(count, load_min, load_max)),
            float(tick) / scale,
        ]
        for count, tick in zip(counts, time_ticks)
    ]
