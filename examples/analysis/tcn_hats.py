"""Replay Option A TCN hats on an observed incoming series (analysis only)."""

from __future__ import annotations


def compute_tcn_hats(
    meta: dict,
    tau: list[int],
    incoming: list[float],
) -> tuple[list[float], list[float]] | None:
    """Return ``(t+1, t+5)`` count series, or ``None`` if this run is not TCN."""
    scaler = meta.get("autoscaler") or {}
    params = scaler.get("params") or {}
    if scaler.get("name") != "proactive_auto_scaler":
        return None
    if params.get("predictor") != "tcn_delta":
        return None
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
    offset = int(params.get("time_tick_offset") or 0)
    step1 = [float("nan")] * len(incoming)
    step_h = [float("nan")] * len(incoming)
    for i in range(lookback - 1, len(incoming)):
        window = incoming[i - lookback + 1 : i + 1]
        close_tick = (tau[i] - 1) + offset
        ticks = time_window(close_tick, lookback)
        hats = predictor.predict_horizon(
            [count_to_rps(n, tick_sec=predictor.tick_sec) for n in window],
            time_ticks=ticks,
            counts=list(window),
        )
        if i + 1 < len(incoming):
            step1[i + 1] = rps_to_count(hats[0], tick_sec=predictor.tick_sec)
        if i + len(hats) < len(incoming):
            step_h[i + len(hats)] = rps_to_count(hats[-1], tick_sec=predictor.tick_sec)
        elif i + 1 < len(incoming):
            step_h[i + 1] = rps_to_count(hats[-1], tick_sec=predictor.tick_sec)
    return step1, step_h
