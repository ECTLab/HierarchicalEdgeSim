import pytest

from hierarchical_edge_sim.env.config import ContainerSpec, MicroserviceSpec
from hierarchical_edge_sim.env.models import Container
from hierarchical_edge_sim.env.routing import distribute
from hierarchical_edge_sim.env.usage import apply_tick


def _api_spec() -> MicroserviceSpec:
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
            ContainerSpec(id="c-api-a", server_id="c1-w1", cpu_alloc_cores=1.0, ram_alloc_mb=512.0),
            ContainerSpec(id="c-api-b", server_id="c1-w2", cpu_alloc_cores=3.0, ram_alloc_mb=1024.0),
        ],
    )


def _make_container(container_id: str, server_id: str, cpu: float, ram: float) -> Container:
    return Container(
        id=container_id,
        app_id="demo_app",
        server_id=server_id,
        microservice_id="api",
        cpu_alloc_cores=cpu,
        ram_alloc_mb=ram,
    )


def test_single_replica_gets_all_lambda():
    c = _make_container("c-api-1", "c1-w1", cpu=1.0, ram=512.0)
    shares = distribute(offer_lambda=120.0, containers=[c], cpu_min_cores=0.5)
    assert shares == {"c-api-1": 120.0}


def test_heterogeneous_split():
    a = _make_container("c-api-a", "c1-w1", cpu=1.0, ram=512.0)   # headroom = 0.5
    b = _make_container("c-api-b", "c1-w2", cpu=3.0, ram=1024.0)  # headroom = 2.5

    shares = distribute(offer_lambda=400.0, containers=[a, b], cpu_min_cores=0.5)
    assert shares["c-api-a"] == pytest.approx(66.6666666667, rel=1e-9)
    assert shares["c-api-b"] == pytest.approx(333.3333333333, rel=1e-9)
    assert sum(shares.values()) == pytest.approx(400.0)


def test_zero_headroom_equal_share():
    a = _make_container("c-api-a", "c1-w1", cpu=0.5, ram=256.0)
    b = _make_container("c-api-b", "c1-w2", cpu=0.5, ram=256.0)
    shares = distribute(offer_lambda=100.0, containers=[a, b], cpu_min_cores=0.5)
    assert shares["c-api-a"] == pytest.approx(50.0)
    assert shares["c-api-b"] == pytest.approx(50.0)


def test_routing_plus_usage_end_to_end():
    spec = _api_spec()
    a = _make_container("c-api-a", "c1-w1", cpu=1.0, ram=512.0)   # μ=50
    b = _make_container("c-api-b", "c1-w2", cpu=3.0, ram=1024.0)  # μ=250

    shares = distribute(offer_lambda=400.0, containers=[a, b], cpu_min_cores=spec.cpu_min_cores)
    rec_a = apply_tick(a, lambda_in=shares[a.id], spec=spec, tau=1)
    rec_b = apply_tick(b, lambda_in=shares[b.id], spec=spec, tau=1)

    assert rec_a.lambda_in == pytest.approx(66.6666666667, rel=1e-9)
    assert rec_a.lambda_served == pytest.approx(50.0)
    assert rec_a.lambda_dropped == pytest.approx(16.6666666667, rel=1e-9)

    assert rec_b.lambda_in == pytest.approx(333.3333333333, rel=1e-9)
    assert rec_b.lambda_served == pytest.approx(250.0)
    assert rec_b.lambda_dropped == pytest.approx(83.3333333333, rel=1e-9)


def test_prefer_local_fills_home_mu_then_overflow():
    a = _make_container("c-home", "c1-w1", cpu=1.0, ram=512.0)  # μ=50
    b = _make_container("c-loan", "c2-w1", cpu=3.0, ram=1024.0)  # μ=250
    shares = distribute(
        offer_lambda=400.0,
        containers=[a, b],
        cpu_min_cores=0.5,
        home_ids={"c-home"},
        mu={"c-home": 50.0, "c-loan": 250.0},
    )
    assert shares["c-home"] == pytest.approx(50.0)
    assert shares["c-loan"] == pytest.approx(350.0)
    assert sum(shares.values()) == pytest.approx(400.0)


def test_prefer_local_caps_home_at_theta_then_spills():
    a = _make_container("c-home", "c1-w1", cpu=1.0, ram=512.0)  # μ=50
    b = _make_container("c-loan", "c2-w1", cpu=3.0, ram=1024.0)  # μ=250
    shares = distribute(
        offer_lambda=51.0,
        containers=[a, b],
        cpu_min_cores=0.5,
        home_ids={"c-home"},
        mu={"c-home": 50.0, "c-loan": 250.0},
        theta_route=0.80,
    )
    assert shares["c-home"] == pytest.approx(40.0)
    assert shares["c-loan"] == pytest.approx(11.0)
    assert sum(shares.values()) == pytest.approx(51.0)


def test_prefer_local_spills_back_to_home_when_loans_are_full():
    a = _make_container("c-home", "c1-w1", cpu=1.0, ram=512.0)  # μ=50
    b = _make_container("c-loan", "c2-w1", cpu=1.0, ram=512.0)  # μ=50
    shares = distribute(
        offer_lambda=100.0,
        containers=[a, b],
        cpu_min_cores=0.5,
        home_ids={"c-home"},
        mu={"c-home": 50.0, "c-loan": 50.0},
        theta_route=0.80,
    )
    assert shares["c-home"] == pytest.approx(50.0)
    assert shares["c-loan"] == pytest.approx(50.0)


def test_prefer_local_keeps_home_at_theta_when_loans_have_room():
    a = _make_container("c-home", "c1-w1", cpu=1.0, ram=512.0)  # μ=50
    b = _make_container("c-loan", "c2-w1", cpu=3.0, ram=1024.0)  # μ=150 if we say so
    shares = distribute(
        offer_lambda=180.0,
        containers=[a, b],
        cpu_min_cores=0.5,
        home_ids={"c-home"},
        mu={"c-home": 50.0, "c-loan": 150.0},
        theta_route=0.80,
    )
    assert shares["c-home"] == pytest.approx(40.0)
    assert shares["c-loan"] == pytest.approx(140.0)


def test_prefer_local_rejects_bad_theta_route():
    a = _make_container("c-home", "c1-w1", cpu=1.0, ram=512.0)
    b = _make_container("c-loan", "c2-w1", cpu=1.0, ram=512.0)
    with pytest.raises(ValueError, match="theta_route"):
        distribute(
            offer_lambda=10.0,
            containers=[a, b],
            cpu_min_cores=0.5,
            home_ids={"c-home"},
            mu={"c-home": 50.0, "c-loan": 50.0},
            theta_route=0.0,
        )


def test_effective_theta_route_uses_scaler_theta_high():
    from hierarchical_edge_sim.env.routing import effective_theta_route

    class _Params:
        theta_high = 0.80

    class _Scaler:
        params = _Params()

    assert effective_theta_route(1.0, _Scaler()) == pytest.approx(0.80)
    assert effective_theta_route(0.70, None) == pytest.approx(0.70)
    assert effective_theta_route(1.0, object()) == pytest.approx(1.0)


def test_prefer_local_all_home_keeps_headroom_split():
    a = _make_container("c-api-a", "c1-w1", cpu=1.0, ram=512.0)
    b = _make_container("c-api-b", "c1-w2", cpu=3.0, ram=1024.0)
    shares = distribute(
        offer_lambda=400.0,
        containers=[a, b],
        cpu_min_cores=0.5,
        home_ids={"c-api-a", "c-api-b"},
        mu={"c-api-a": 50.0, "c-api-b": 250.0},
    )
    assert shares["c-api-a"] == pytest.approx(66.6666666667, rel=1e-9)
    assert shares["c-api-b"] == pytest.approx(333.3333333333, rel=1e-9)

