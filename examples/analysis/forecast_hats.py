"""Replay predictor hats on an observed incoming series (analysis only)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ForecastSeries:
    step1: list[float]
    step_h: list[float]
    predictor: str
    horizon: int
    lookback: int


def compute_forecast_hats(
    meta: dict,
    tau: list[int],
    incoming: list[float],
) -> ForecastSeries | None:
    """Return hats aligned to the ticks they forecast, or ``None``.

    ``step1[t]`` is the t+1 hat issued at t-1; ``step_h[t]`` is the last
    horizon step issued at t-H. Cold-start ticks stay NaN. Assumes
    ``ticks_per_window=1`` (every current demo).
    """
    scaler = meta.get("autoscaler") or {}
    params = scaler.get("params") or {}
    if scaler.get("name") != "proactive_auto_scaler":
        return None
    predictor = str(params.get("predictor") or "persistence")
    if predictor == "tcn_delta":
        return _tcn_hats(meta, params, tau, incoming)
    if predictor == "persistence":
        return _persistence_hats(meta, params, tau, incoming)
    return None


def compute_tcn_hats(
    meta: dict,
    tau: list[int],
    incoming: list[float],
) -> tuple[list[float], list[float]] | None:
    """Return ``(t+1, t+H)`` count series, or ``None`` if this run is not TCN."""
    hats = compute_forecast_hats(meta, tau, incoming)
    if hats is None or hats.predictor != "tcn_delta":
        return None
    return hats.step1, hats.step_h


def _sim_tick_sec(meta: dict) -> float:
    sim = (meta.get("config") or {}).get("sim") or {}
    return float(sim.get("tick_sec") or 1.0)


def _place_hats(
    step1: list[float],
    step_h: list[float],
    i: int,
    hat_counts: list[float],
) -> None:
    n = len(step1)
    if not hat_counts:
        return
    if i + 1 < n:
        step1[i + 1] = hat_counts[0]
    if i + len(hat_counts) < n:
        step_h[i + len(hat_counts)] = hat_counts[-1]
    elif i + 1 < n:
        step_h[i + 1] = hat_counts[-1]


def _persistence_hats(
    meta: dict,
    params: dict,
    tau: list[int],
    incoming: list[float],
) -> ForecastSeries | None:
    from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.persistence import (
        PersistencePredictor,
    )
    from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.window import (
        count_to_rps,
        rps_to_count,
    )

    lookback = int(params.get("feature_window") or 10)
    horizon = int(params.get("forecast_horizon") or 3)
    if lookback < 1 or horizon < 1 or len(incoming) < lookback:
        return None
    tick_sec = _sim_tick_sec(meta)
    pred = PersistencePredictor(forecast_horizon=horizon)
    nan = float("nan")
    step1 = [nan] * len(incoming)
    step_h = [nan] * len(incoming)
    for i in range(lookback - 1, len(incoming)):
        window = incoming[i - lookback + 1 : i + 1]
        hats = pred.predict_horizon(
            [count_to_rps(n, tick_sec=tick_sec) for n in window]
        )
        _place_hats(
            step1,
            step_h,
            i,
            [rps_to_count(h, tick_sec=tick_sec) for h in hats],
        )
    return ForecastSeries(
        step1=step1,
        step_h=step_h,
        predictor="persistence",
        horizon=horizon,
        lookback=lookback,
    )


def _tcn_hats(
    meta: dict,
    params: dict,
    tau: list[int],
    incoming: list[float],
) -> ForecastSeries | None:
    try:
        from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.tcn import (
            TcnDeltaPredictor,
        )
        from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.window import (
            count_to_rps,
            rps_to_count,
            time_window,
        )
    except ImportError:
        return None

    model_dir = params.get("model_dir") or "models/tcn_delta_v1"
    try:
        predictor = TcnDeltaPredictor.from_model_dir(model_dir)
    except Exception:
        return None

    lookback = predictor.lookback
    horizon = int(predictor.forecast_horizon)
    offset = int(params.get("time_tick_offset") or 0)
    nan = float("nan")
    step1 = [nan] * len(incoming)
    step_h = [nan] * len(incoming)
    for i in range(lookback - 1, len(incoming)):
        window = incoming[i - lookback + 1 : i + 1]
        close_tick = (tau[i] - 1) + offset
        ticks = time_window(close_tick, lookback)
        hats = predictor.predict_horizon(
            [count_to_rps(n, tick_sec=predictor.tick_sec) for n in window],
            time_ticks=ticks,
            counts=list(window),
        )
        _place_hats(
            step1,
            step_h,
            i,
            [rps_to_count(h, tick_sec=predictor.tick_sec) for h in hats],
        )
    return ForecastSeries(
        step1=step1,
        step_h=step_h,
        predictor="tcn_delta",
        horizon=horizon,
        lookback=lookback,
    )
