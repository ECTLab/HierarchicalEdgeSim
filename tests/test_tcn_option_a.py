"""Option A window math and TCN I/O (weights loaded only if torch is present)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.window import (
    build_option_a_window,
    count_to_rps,
    denormalize_load,
    normalize_load,
    rps_to_count,
    time_window,
)


def test_normalize_roundtrip():
    assert normalize_load(932.0, 932.0, 29778.0) == pytest.approx(0.0)
    assert normalize_load(29778.0, 932.0, 29778.0) == pytest.approx(1.0)
    mid = denormalize_load(0.5, 932.0, 29778.0)
    assert normalize_load(mid, 932.0, 29778.0) == pytest.approx(0.5)


def test_count_rps_roundtrip():
    assert rps_to_count(10.0, tick_sec=60.0) == pytest.approx(600.0)
    assert count_to_rps(600.0, tick_sec=60.0) == pytest.approx(10.0)


def test_time_window_and_option_a_shape():
    ticks = time_window(59, 60)
    assert ticks[0] == 0
    assert ticks[-1] == 59
    assert len(ticks) == 60
    counts = [1000.0 + i for i in ticks]
    window = build_option_a_window(
        counts, ticks, load_min=932.0, load_max=29778.0, time_scale=720.0
    )
    assert len(window) == 60
    assert window[0][1] == pytest.approx(0.0)
    assert window[-1][1] == pytest.approx(59.0 / 720.0)
    assert 0.0 <= window[-1][0] <= 1.0


def test_tcn_emits_five_rps(project_root: Path):
    torch = pytest.importorskip("torch")
    _ = torch
    from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.tcn import (
        TcnDeltaPredictor,
    )

    pred = TcnDeltaPredictor.from_model_dir(project_root / "models" / "tcn_delta_v1")
    counts = [2000.0] * 60
    ticks = time_window(59, 60)
    hats = pred.predict_horizon(
        [count_to_rps(n, tick_sec=60.0) for n in counts],
        time_ticks=ticks,
        counts=counts,
    )
    assert len(hats) == 5
    assert all(h >= 0.0 for h in hats)
