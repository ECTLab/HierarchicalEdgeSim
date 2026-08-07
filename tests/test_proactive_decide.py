"""Unit tests for proactive PredictAndDecide (pure, no Env)."""

from __future__ import annotations

import pytest

from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.decide import Direction, predict_and_decide


def test_up_from_observed_util():
    # A=1 core, rho=0.01 → C_full = 100 req/s; r_t=90 → u=0.9 ≥ 0.8
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
    # RAM already above A_req for this demand → residual may be 0
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


def test_residual_unit_bridge_cpu():
    # r_star=60, theta=0.6, rho=0.01, tick=1, cpu_min=0 → A_req_cpu = 1.0; A=0.5 → delta=0.5
    d = predict_and_decide(
        r_t=60.0,
        r_hat=[60.0],
        A_cpu=0.5,
        A_ram=50.0,
        rho_cpu=0.01,
        rho_ram=0.5,
        tick_sec=1.0,
        u_meas=1.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=1,
        cpu_min_cores=0.0,
        ram_min_mb=0.0,
    )
    assert d.direction is Direction.UP
    assert d.delta_cpu == pytest.approx(0.5)
    # A_req_ram = 0 + 0.5*60/0.6 = 50; A_ram=50 → delta_ram=0
    assert d.delta_ram == pytest.approx(0.0)


def test_residual_bridge_includes_deployment_floor():
    # Deployment floor (min) buys zero throughput (env/usage.py headroom model), so the
    # required allocation must add it back on top of the throughput term, or a
    # RAM floor that dwarfs the throughput need (as here) silently stalls scale-up.
    # A_req_cpu = 0.5 + 0.01*60/0.6 = 1.5 → A_cpu=0.5 → delta_cpu=1.0
    # A_req_ram = 256 + 0.5*60/0.6 = 306 → A_ram=256 → delta_ram=50.0 (NOT 0/negative)
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


def test_a_zero_still_positive_up_residual():
    d = predict_and_decide(
        r_t=30.0,
        r_hat=[30.0, 30.0],
        A_cpu=0.0,
        A_ram=0.0,
        rho_cpu=0.01,
        rho_ram=0.5,
        tick_sec=1.0,
        u_meas=1.0,
        theta_up=0.80,
        theta_down=0.30,
        theta_target=0.60,
        sustained_tau=2,
    )
    assert d.direction is Direction.UP
    assert d.delta_cpu > 0
    assert d.delta_ram > 0


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
