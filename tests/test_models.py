import pytest

from hierarchical_edge_sim.env.models import Container, ContainerTickRecord


def _make_record(tau: int, lambda_in: float) -> ContainerTickRecord:
    return ContainerTickRecord(
        tau=tau,
        lambda_in=lambda_in,
        lambda_served=min(lambda_in, 10.0),
        lambda_dropped=max(0.0, lambda_in - 10.0),
        cpu_usage_cores=0.5 + min(lambda_in, 10.0) * 0.01,
        ram_usage_mb=256.0 + min(lambda_in, 10.0) * 0.5,
        cpu_alloc_cores=1.0,
        ram_alloc_mb=512.0,
        q_cpu=0.2,
        q_ram=0.3,
    )


def test_container_tick_record_fields():
    r = _make_record(tau=3, lambda_in=12.0)
    assert r.tau == 3
    assert r.lambda_in == 12.0
    assert r.lambda_served == 10.0
    assert r.lambda_dropped == 2.0
    assert r.cpu_alloc_cores == 1.0
    assert r.ram_alloc_mb == 512.0
    assert r.q_cpu == 0.2
    assert r.q_ram == 0.3


def test_container_history_append_and_at():
    c = Container(
        id="c-api-1",
        app_id="demo_app",
        server_id="c1-w1",
        microservice_id="api",
        cpu_alloc_cores=1.0,
        ram_alloc_mb=512.0,
    )
    c.append_history(_make_record(tau=1, lambda_in=0.0))
    c.append_history(_make_record(tau=2, lambda_in=5.0))
    c.append_history(_make_record(tau=3, lambda_in=20.0))

    assert len(c.history) == 3
    tick2 = c.history_at(2)
    assert tick2.tau == 2
    assert tick2.lambda_in == 5.0

    with pytest.raises(KeyError):
        c.history_at(99)
