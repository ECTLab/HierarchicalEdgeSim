"""Unit tests for proactive PredictAndDecide (pure, no Env)."""

from __future__ import annotations

import pytest

from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.decide import Direction, predict_and_decide


def test_up_from_observed_util():
    d = predict_and_decide(
        r_t=90.0,
        r_hat=[50.0, 40.0, 30.0],
        A_cpu=1.0,
        A_ram=512.0,
        rho_cpu=0.01,
        rho_ram=0.5,
        tick_sec=1.0,
        u_meas=0.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=2,
    )
    assert d.direction is Direction.UP
    assert d.delta_cpu > 0
    assert d.delta_ram >= 0


def test_up_from_horizon_only():
    d = predict_and_decide(
        r_t=10.0,
        r_hat=[10.0, 100.0, 10.0],
        A_cpu=1.0,
        A_ram=512.0,
        rho_cpu=0.01,
        rho_ram=0.5,
        tick_sec=1.0,
        u_meas=0.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=2,
    )
    assert d.direction is Direction.UP
    assert d.r_star == 100.0


def test_down_when_obs_and_horizon_cold():
    d = predict_and_decide(
        r_t=5.0,
        r_hat=[5.0, 4.0, 3.0],
        A_cpu=4.0,
        A_ram=4096.0,
        rho_cpu=0.01,
        rho_ram=0.5,
        tick_sec=1.0,
        u_meas=0.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=2,
    )
    assert d.direction is Direction.DOWN
    assert d.delta_cpu < 0
    assert d.delta_ram < 0


def test_none_in_band():
    d = predict_and_decide(
        r_t=50.0,
        r_hat=[50.0, 55.0, 45.0],
        A_cpu=1.0,
        A_ram=512.0,
        rho_cpu=0.01,
        rho_ram=0.5,
        tick_sec=1.0,
        u_meas=0.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=2,
    )
    assert d.direction is Direction.NONE
    assert d.delta_cpu == 0.0


def test_residual_bridge_includes_deployment_floor():
    d = predict_and_decide(
        r_t=60.0,
        r_hat=[60.0],
        A_cpu=0.5,
        A_ram=256.0,
        rho_cpu=0.01,
        rho_ram=0.5,
        tick_sec=1.0,
        u_meas=1.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=1,
        cpu_min_cores=0.5,
        ram_min_mb=256.0,
    )
    assert d.direction is Direction.UP
    assert d.delta_cpu == pytest.approx(1.0)
    assert d.delta_ram == pytest.approx(50.0)


def test_zero_headroom_with_load_is_up_even_if_sum_alloc_looks_large():
    """Floors buy no μ. Many min-replicas + load must not look idle."""
    d = predict_and_decide(
        r_t=50.0,
        r_hat=[10.0, 10.0, 10.0],
        A_cpu=3.5,
        A_ram=1792.0,
        rho_cpu=0.0004,
        rho_ram=0.02,
        tick_sec=60.0,
        u_meas=0.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=99,
        cpu_min_cores=0.5,
        ram_min_mb=256.0,
        n_replicas=7,
        H_cpu=0.0,
        H_ram=0.0,
    )
    assert d.direction is Direction.UP
    assert d.delta_cpu > 0
    assert d.delta_ram > 0


def test_residual_uses_n_times_deployment_floor():
    d = predict_and_decide(
        r_t=60.0,
        r_hat=[60.0],
        A_cpu=1.5,
        A_ram=768.0,
        rho_cpu=0.01,
        rho_ram=0.5,
        tick_sec=1.0,
        u_meas=1.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=1,
        cpu_min_cores=0.5,
        ram_min_mb=256.0,
        n_replicas=3,
        H_cpu=0.0,
        H_ram=0.0,
    )
    assert d.direction is Direction.UP
    assert d.delta_cpu == pytest.approx(1.0)
    assert d.delta_ram == pytest.approx(50.0)


def test_sustained_flag():
    d = predict_and_decide(
        r_t=100.0,
        r_hat=[100.0, 100.0, 10.0],
        A_cpu=1.0,
        A_ram=512.0,
        rho_cpu=0.01,
        rho_ram=0.5,
        tick_sec=1.0,
        u_meas=0.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=2,
    )
    assert d.direction is Direction.UP
    assert d.sustained is True
