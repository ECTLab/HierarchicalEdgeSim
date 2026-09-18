import math

import pytest

from hierarchical_edge_sim.env.latency import offered_delay


def test_idle_tick_has_zero_offered_delay():
    stats = offered_delay(
        lambda_in=0.0,
        mu=50.0,
        tick_sec=1.0,
        sla_timeout_sec=1.0,
        t_net_sec=0.04,
    )
    assert stats.t_net_sec == pytest.approx(0.04)
    assert stats.t_mean_offered_sec == 0.0
    assert stats.t_p99_offered_sec == 0.0
    assert stats.sla_miss_requests == 0.0


def test_stable_mm1_p99_tiny_tick2():
    # μ=50, λ=25, tick_sec=1 → W=1/25; p99 = -ln(0.01) W
    wait = 1.0 / 25.0
    stats = offered_delay(
        lambda_in=25.0,
        mu=50.0,
        tick_sec=1.0,
        sla_timeout_sec=1.0,
        t_net_sec=0.0,
    )
    assert stats.t_p99_offered_sec == pytest.approx(-math.log(0.01) * wait)
    assert stats.t_p95_offered_sec == pytest.approx(-math.log(0.05) * wait)
    assert stats.t_mean_offered_sec == pytest.approx(wait * (1.0 - math.exp(-1.0 / wait)))
    assert stats.sla_miss_requests == pytest.approx(25.0 * math.exp(-1.0 / wait))


def test_saturated_counts_as_timeout_including_t_net():
    stats = offered_delay(
        lambda_in=120.0,
        mu=50.0,
        tick_sec=1.0,
        sla_timeout_sec=1.0,
        t_net_sec=0.04,
    )
    assert stats.t_mean_offered_sec == pytest.approx(1.04)
    assert stats.t_p99_offered_sec == pytest.approx(1.04)
    assert stats.sla_miss_requests == pytest.approx(120.0)


def test_zero_mu_is_timeout():
    stats = offered_delay(
        lambda_in=10.0,
        mu=0.0,
        tick_sec=1.0,
        sla_timeout_sec=0.2,
        t_net_sec=0.0,
    )
    assert stats.t_p99_offered_sec == pytest.approx(0.2)
    assert stats.sla_miss_requests == pytest.approx(10.0)
