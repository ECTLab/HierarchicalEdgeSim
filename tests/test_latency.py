import math

import pytest

from hierarchical_edge_sim.env.latency import DelayPart, mix_offered_quantile, offered_delay


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
    wait = 1.0 / 25.0
    stats = offered_delay(
        lambda_in=25.0,
        mu=50.0,
        tick_sec=1.0,
        sla_timeout_sec=1.0,
        t_net_sec=0.0,
    )
    assert stats.t_p99_offered_sec == pytest.approx(-math.log(0.01) * wait, rel=1e-5)
    assert stats.t_p95_offered_sec == pytest.approx(-math.log(0.05) * wait, rel=1e-5)
    assert stats.t_mean_offered_sec == pytest.approx(wait * (1.0 - math.exp(-1.0 / wait)))
    assert stats.sla_miss_requests == pytest.approx(25.0 * math.exp(-1.0 / wait))


def test_over_capacity_drops_timeout_served_uses_rho_cap():
    wait = 1.0 / (50.0 * 0.01)
    tail = math.exp(-1.0 / wait)
    stats = offered_delay(
        lambda_in=120.0,
        mu=50.0,
        tick_sec=1.0,
        sla_timeout_sec=1.0,
        t_net_sec=0.04,
    )
    mean_served = wait * (1.0 - math.exp(-1.0 / wait))
    mean = 0.04 + (50.0 / 120.0) * mean_served + (70.0 / 120.0) * 1.0
    assert stats.t_p99_offered_sec == pytest.approx(1.04, abs=1e-4)
    assert stats.t_mean_offered_sec == pytest.approx(mean)
    assert stats.sla_miss_requests == pytest.approx(70.0 + 50.0 * tail)
    assert stats.t_wait_sec == pytest.approx(wait)


def test_full_replica_no_drop_is_not_all_timeout():
    wait = 1.0 / (50.0 * 0.01)
    stats = offered_delay(
        lambda_in=50.0,
        mu=50.0,
        tick_sec=1.0,
        sla_timeout_sec=1.0,
        t_net_sec=0.0,
    )
    assert stats.sla_miss_requests == pytest.approx(50.0 * math.exp(-1.0 / wait))
    assert stats.sla_miss_requests < 50.0
    assert stats.t_mean_offered_sec < 1.0


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


def test_mix_p99_is_timeout_when_more_than_one_percent_miss():
    fast = DelayPart(weight=98.0, t_net_sec=0.0, wait_sec=0.01, served_frac=1.0, sla_timeout_sec=1.0)
    slow = DelayPart(weight=2.0, t_net_sec=0.04, wait_sec=0.0, served_frac=0.0, sla_timeout_sec=1.0)
    p99 = mix_offered_quantile(0.99, [fast, slow])
    assert p99 == pytest.approx(1.04, abs=1e-3)


def test_mix_p99_stays_with_served_when_miss_is_tiny():
    wait = 0.04
    a = DelayPart(weight=50.0, t_net_sec=0.0, wait_sec=wait, served_frac=1.0, sla_timeout_sec=1.0)
    b = DelayPart(weight=50.0, t_net_sec=0.005, wait_sec=wait, served_frac=1.0, sla_timeout_sec=1.0)
    p99 = mix_offered_quantile(0.99, [a, b])
    assert p99 < 0.3
    assert p99 > -math.log(0.01) * wait
