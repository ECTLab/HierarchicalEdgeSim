import pytest

from hierarchical_edge_sim.env.config import ContainerSpec, MicroserviceSpec
from hierarchical_edge_sim.env.models import Container
from hierarchical_edge_sim.env.usage import apply_tick, serving_capacity


def _tiny_spec() -> MicroserviceSpec:
    return MicroserviceSpec(
        id="api",
        cpu_min_cores=0.5,
        cpu_max_cores=4.0,
        ram_min_mb=256.0,
        ram_max_mb=4096.0,
        cpu_per_request_cores=0.01,
        ram_per_request_mb=0.5,
        trace_file="api.csv",
        containers=[
            ContainerSpec(
                id="c-api-1",
                server_id="c1-w1",
                cpu_alloc_cores=1.0,
                ram_alloc_mb=512.0,
            )
        ],
    )


def _container(cpu_alloc_cores: float = 1.0, ram_alloc_mb: float = 512.0) -> Container:
    return Container(
        id="c-api-1",
        app_id="demo_app",
        server_id="c1-w1",
        microservice_id="api",
        cpu_alloc_cores=cpu_alloc_cores,
        ram_alloc_mb=ram_alloc_mb,
    )


def test_serving_capacity_tiny_container():
    spec = _tiny_spec()
    c = _container()
    assert serving_capacity(c, spec) == pytest.approx(50.0)


def test_apply_tick_golden_rows():
    spec = _tiny_spec()
    c = _container()

    incoming = [0.0, 25.0, 80.0, 120.0, 50.0]
    expected = [
        (0.0, 0.0, 0.5),
        (25.0, 0.0, 0.75),
        (50.0, 30.0, 1.0),
        (50.0, 70.0, 1.0),
        (50.0, 0.0, 1.0),
    ]

    for tau, lamb in enumerate(incoming, start=1):
        rec = apply_tick(c, lambda_in=lamb, spec=spec, tau=tau)
        exp_served, exp_dropped, exp_cpu_used = expected[tau - 1]
        assert rec.lambda_served == pytest.approx(exp_served)
        assert rec.lambda_dropped == pytest.approx(exp_dropped)
        assert rec.cpu_usage_cores == pytest.approx(exp_cpu_used)

    assert len(c.history) == 5
    assert c.history_at(4).lambda_dropped == pytest.approx(70.0)


def test_ram_per_request_zero_not_binding():
    spec = _tiny_spec()
    spec = MicroserviceSpec(
        id=spec.id,
        cpu_min_cores=spec.cpu_min_cores,
        cpu_max_cores=spec.cpu_max_cores,
        ram_min_mb=spec.ram_min_mb,
        ram_max_mb=spec.ram_max_mb,
        cpu_per_request_cores=spec.cpu_per_request_cores,
        ram_per_request_mb=0.0,
        trace_file=spec.trace_file,
        containers=spec.containers,
    )
    c = _container()
    rec = apply_tick(c, lambda_in=120.0, spec=spec, tau=1)
    assert rec.lambda_served == pytest.approx(50.0)
    assert rec.lambda_dropped == pytest.approx(70.0)
    assert rec.ram_usage_mb == pytest.approx(spec.ram_min_mb)
    assert rec.q_ram == pytest.approx(0.0)


def test_zero_headroom_serves_nothing():
    spec = _tiny_spec()
    c = _container(cpu_alloc_cores=spec.cpu_min_cores, ram_alloc_mb=spec.ram_min_mb)
    rec = apply_tick(c, lambda_in=100.0, spec=spec, tau=1)
    assert rec.lambda_served == pytest.approx(0.0)
    assert rec.lambda_dropped == pytest.approx(100.0)
    assert rec.cpu_usage_cores == pytest.approx(spec.cpu_min_cores)
    assert rec.ram_usage_mb == pytest.approx(spec.ram_min_mb)
    assert rec.q_cpu == pytest.approx(0.0)
    assert rec.q_ram == pytest.approx(0.0)
