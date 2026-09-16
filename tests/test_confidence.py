"""Unit tests for Eq. confidence κ = 1/(1+MAPE)."""

from __future__ import annotations

from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.confidence import (
    CountConfidence,
    kappa_from_mape,
    mape_on_counts,
)
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.decide import Direction, predict_and_decide


def test_kappa_zero_during_cold_start():
    tracker = CountConfidence(window=3)
    assert tracker.observe(10.0, 10.0) == 0.0
    assert tracker.observe(10.0, 10.0) == 0.0
    kappa = tracker.observe(10.0, 10.0)
    assert kappa == 1.0


def test_kappa_from_mape():
    assert kappa_from_mape(0.0) == 1.0
    assert kappa_from_mape(1.0) == 0.5
    assert mape_on_counts(20.0, 10.0) == 1.0


def test_bad_forecasts_drop_kappa_below_half():
    tracker = CountConfidence(window=2)
    tracker.observe(10.0, 100.0)
    tracker.observe(10.0, 100.0)
    kappa = tracker.observe(10.0, 100.0)
    assert kappa < 0.5


def test_untrusted_forecast_ignores_horizon_spike():
    trusted = predict_and_decide(
        observed_rps=10.0,
        forecast_rps=[10.0, 100.0, 10.0],
        A_cpu=1.0,
        A_ram=512.0,
        cpu_per_request=0.01,
        ram_per_request=0.5,
        tick_sec=1.0,
        u_meas=0.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_steps=2,
        trust_forecast=True,
    )
    ignored = predict_and_decide(
        observed_rps=10.0,
        forecast_rps=[10.0, 100.0, 10.0],
        A_cpu=1.0,
        A_ram=512.0,
        cpu_per_request=0.01,
        ram_per_request=0.5,
        tick_sec=1.0,
        u_meas=0.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_steps=2,
        trust_forecast=False,
    )
    assert trusted.direction is Direction.UP
    assert ignored.direction is not Direction.UP
    assert ignored.peak_rps == 10.0
