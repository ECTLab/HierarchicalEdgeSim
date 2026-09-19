"""FCFS fluid queue: wait is wall-clock seconds, not ticks."""

import pytest

from hierarchical_edge_sim.env.latency import serve_fluid


def test_empty_tick_is_zero():
    out = serve_fluid(
        arrivals=0.0, mu=50.0, tick_sec=1.0, sla_timeout_sec=1.0, t_net_sec=0.0, queue=0.0
    )
    assert out.served == pytest.approx(0.0)
    assert out.timeout == pytest.approx(0.0)
    assert out.t_p99_offered_sec == pytest.approx(0.0)
    assert out.t_wait_sec == pytest.approx(0.0)


def test_under_capacity_is_service_plus_net_not_utilization():
    out = serve_fluid(
        arrivals=45.0, mu=50.0, tick_sec=1.0, sla_timeout_sec=1.0, t_net_sec=0.005, queue=0.0
    )
    assert out.timeout == pytest.approx(0.0)
    assert out.served == pytest.approx(45.0)
    assert out.queue_len == pytest.approx(0.0)
    assert out.t_wait_sec == pytest.approx(0.0)
    assert out.t_p99_offered_sec == pytest.approx(0.005 + 1.0 / 50.0)
    assert out.sla_miss_requests == pytest.approx(0.0)


def test_one_second_overflow_queues_0_6s_without_timeout():
    """80 arrivals, μ=50/s: leftover 30 drains in 0.6 s, under a 1 s SLO."""
    out = serve_fluid(
        arrivals=80.0, mu=50.0, tick_sec=1.0, sla_timeout_sec=1.0, t_net_sec=0.0, queue=0.0
    )
    assert out.served == pytest.approx(50.0)
    assert out.timeout == pytest.approx(0.0)
    assert out.queue_len == pytest.approx(30.0)
    assert out.t_wait_sec == pytest.approx(0.6)
    assert out.t_p99_offered_sec < 1.0
    assert out.sla_miss_requests == pytest.approx(0.0)


def test_minute_tick_drains_0_6s_leftover_inside_slo():
    """Trace row is a minute; leftover 30 at 50 req/s is 0.6 s of work, not a timeout."""
    out = serve_fluid(
        arrivals=0.0, mu=3000.0, tick_sec=60.0, sla_timeout_sec=1.0, t_net_sec=0.0, queue=30.0
    )
    assert out.served == pytest.approx(30.0)
    assert out.timeout == pytest.approx(0.0)
    assert out.queue_len == pytest.approx(0.0)
    assert out.t_wait_sec == pytest.approx(0.0)
    assert out.wait_hi_sec == pytest.approx(0.6)
    assert out.t_p99_offered_sec < 1.0
    assert out.sla_miss_requests == pytest.approx(0.0)


def test_conservation_arrivals_plus_queue():
    q0 = 10.0
    arrivals = 80.0
    out = serve_fluid(
        arrivals=arrivals, mu=50.0, tick_sec=1.0, sla_timeout_sec=1.0, t_net_sec=0.0, queue=q0
    )
    assert out.served + out.timeout + out.queue_len == pytest.approx(arrivals + q0)
