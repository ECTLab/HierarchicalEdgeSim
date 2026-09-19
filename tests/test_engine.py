from pathlib import Path

import pytest

from hierarchical_edge_sim.env.config import (
    AppSpec,
    ClusterSpec,
    ContainerSpec,
    LatencyEdge,
    MicroserviceSpec,
    ServerSpec,
    SimConfig,
    VicinitySpec,
    WorldSpec,
    load_yaml,
)
from hierarchical_edge_sim.env.engine import EngineState, run_ticks
from hierarchical_edge_sim.env.traces import TraceStore, load_traces
from hierarchical_edge_sim.env.validate import validate_or_raise
from hierarchical_edge_sim.env.world import build_world


def _build_runtime(tiny_config_path):
    raw = load_yaml(tiny_config_path)
    spec = validate_or_raise(raw)
    world = build_world(spec)
    traces = load_traces(spec)
    return world, traces, spec


def test_engine_tiny_five_ticks(tiny_config_path):
    world, traces, spec = _build_runtime(tiny_config_path)
    state = EngineState()
    ticks = run_ticks(world=world, traces=traces, world_spec=spec, state=state)

    c = world.containers["c-api-1"]
    assert ticks == 5
    assert state.current_tau == 5
    assert len(c.history) == 5


def test_engine_golden_table(tiny_config_path):
    world, traces, spec = _build_runtime(tiny_config_path)
    run_ticks(world=world, traces=traces, world_spec=spec)

    c = world.containers["c-api-1"]
    assert [r.lambda_in for r in c.history] == pytest.approx([0.0, 25.0, 80.0, 120.0, 50.0])
    assert c.history_at(1).lambda_served == pytest.approx(0.0)
    assert c.history_at(2).lambda_served == pytest.approx(25.0)
    assert c.history_at(2).cpu_usage_cores == pytest.approx(0.75)

    rec3 = c.history_at(3)
    assert rec3.lambda_served == pytest.approx(50.0)
    assert rec3.lambda_dropped == pytest.approx(0.0)
    assert rec3.queue_len == pytest.approx(30.0)
    assert rec3.t_wait_sec == pytest.approx(0.6)
    assert rec3.t_p99_offered_sec < 1.0
    assert rec3.cpu_usage_cores == pytest.approx(1.0)

    prev_q = 0.0
    for rec in c.history:
        assert rec.lambda_served + rec.lambda_dropped + rec.queue_len == pytest.approx(
            rec.lambda_in + prev_q
        )
        prev_q = rec.queue_len


def test_engine_prefer_local_and_remote_t_net():
    spec = WorldSpec(
        sim=SimConfig(tick_sec=1.0, results_dir="results/", seed=1, sla_timeout_sec=1.0),
        traces_dir="unused/",
        clusters=[
            ClusterSpec(
                id="c1",
                servers=[ServerSpec(id="c1-w1", cpu_cap_cores=8.0, ram_cap_mb=16384.0)],
                coords=(0.0, 0.0),
            ),
            ClusterSpec(
                id="c2",
                servers=[ServerSpec(id="c2-w1", cpu_cap_cores=8.0, ram_cap_mb=16384.0)],
                coords=(0.0, 0.0),
            ),
        ],
        apps=[
            AppSpec(
                id="demo_app",
                microservices=[
                    MicroserviceSpec(
                        id="api",
                        cpu_min_cores=0.5,
                        cpu_max_cores=4.0,
                        ram_min_mb=256.0,
                        ram_max_mb=4096.0,
                        cpu_per_request_cores=0.01,
                        ram_per_request_mb=0.5,
                        trace_file="unused.csv",
                        containers=[
                            ContainerSpec(
                                id="c-home",
                                server_id="c1-w1",
                                cpu_alloc_cores=1.0,
                                ram_alloc_mb=512.0,
                            ),
                            ContainerSpec(
                                id="c-loan",
                                server_id="c2-w1",
                                cpu_alloc_cores=3.0,
                                ram_alloc_mb=1024.0,
                            ),
                        ],
                    )
                ],
            )
        ],
        source_path=Path("unused/config.yaml"),
        vicinities=[VicinitySpec(id="v1", members=["c1", "c2"], leader="c1")],
        latency_ms=[LatencyEdge(a="c1", b="c2", ms=40.0)],
    )
    world = build_world(spec)
    traces = TraceStore(_data={"api": [400.0]})
    run_ticks(world=world, traces=traces, world_spec=spec)

    home = world.containers["c-home"].history_at(1)
    loan = world.containers["c-loan"].history_at(1)
    assert home.lambda_in == pytest.approx(50.0)
    assert home.lambda_dropped == pytest.approx(0.0)
    assert home.t_net_sec == pytest.approx(0.0)
    assert home.queue_len == pytest.approx(0.0)
    assert home.t_p99_offered_sec == pytest.approx(home.t_svc_sec)
    assert home.sla_miss_requests == pytest.approx(0.0)
    assert loan.lambda_in == pytest.approx(350.0)
    assert loan.lambda_served == pytest.approx(250.0)
    assert loan.lambda_dropped == pytest.approx(0.0)
    assert loan.queue_len == pytest.approx(100.0)
    assert loan.t_net_sec == pytest.approx(0.04)
    assert loan.t_wait_sec == pytest.approx(100.0 / 250.0)
    assert loan.t_p99_offered_sec < 1.04



def test_ms_processing_order_deterministic(tiny_config_path):
    world1, traces1, spec1 = _build_runtime(tiny_config_path)
    world2, traces2, spec2 = _build_runtime(tiny_config_path)

    run_ticks(world=world1, traces=traces1, world_spec=spec1)
    run_ticks(world=world2, traces=traces2, world_spec=spec2)

    h1 = world1.containers["c-api-1"].history
    h2 = world2.containers["c-api-1"].history
    assert len(h1) == len(h2)
    for r1, r2 in zip(h1, h2):
        assert r1 == r2


def _two_microservice_world_spec() -> WorldSpec:
    # Declared out of id order ("svc-b" before "svc-a") to exercise the
    # engine's `sorted(..., key=lambda m: m.id)` requirement (§2.1/§16.4):
    # per-MS results must not depend on declaration/dict order.
    return WorldSpec(
        sim=SimConfig(tick_sec=1.0, results_dir="results/", seed=1),
        traces_dir="unused/",
        clusters=[
            ClusterSpec(
                id="c1",
                servers=[ServerSpec(id="s1", cpu_cap_cores=100.0, ram_cap_mb=100000.0)],
            )
        ],
        apps=[
            AppSpec(
                id="app1",
                microservices=[
                    MicroserviceSpec(
                        id="svc-b",
                        cpu_min_cores=1.0,
                        cpu_max_cores=8.0,
                        ram_min_mb=1.0,
                        ram_max_mb=1000.0,
                        cpu_per_request_cores=0.02,
                        ram_per_request_mb=0.0,
                        trace_file="unused-b.csv",
                        containers=[
                            ContainerSpec(id="c-b", server_id="s1", cpu_alloc_cores=3.0, ram_alloc_mb=1.0)
                        ],
                    ),
                    MicroserviceSpec(
                        id="svc-a",
                        cpu_min_cores=0.5,
                        cpu_max_cores=4.0,
                        ram_min_mb=1.0,
                        ram_max_mb=1000.0,
                        cpu_per_request_cores=0.01,
                        ram_per_request_mb=0.0,
                        trace_file="unused-a.csv",
                        containers=[
                            ContainerSpec(id="c-a", server_id="s1", cpu_alloc_cores=1.0, ram_alloc_mb=1.0)
                        ],
                    ),
                ],
            )
        ],
        source_path=Path("unused/config.yaml"),
    )


def test_engine_multi_microservice_tick_independence():
    """Regression guard for Step 8's untested multi-MS code path.

    Prior tests only ever ran the tick loop against `00-tiny.yaml`'s single
    microservice / single container, so `sorted(world.microservices...)`
    plus the `ms_specs[ms.id]` lookup across *multiple* microservices was
    never actually exercised end-to-end through `run_ticks`.
    """
    spec = _two_microservice_world_spec()
    world = build_world(spec)
    traces = TraceStore(_data={"svc-a": [40.0, 100.0], "svc-b": [30.0, 150.0]})

    ticks = run_ticks(world=world, traces=traces, world_spec=spec)
    assert ticks == 2

    # svc-a: headroom = 1.0 - 0.5 = 0.5 -> mu = 0.5 / 0.01 = 50
    rec_a1 = world.containers["c-a"].history_at(1)
    rec_a2 = world.containers["c-a"].history_at(2)
    assert rec_a1.lambda_served == pytest.approx(40.0)
    assert rec_a1.lambda_dropped == pytest.approx(0.0)
    assert rec_a2.lambda_served == pytest.approx(50.0)
    assert rec_a2.lambda_dropped + rec_a2.queue_len == pytest.approx(50.0)

    # svc-b: headroom = 3.0 - 1.0 = 2.0 -> mu = 2.0 / 0.02 = 100
    rec_b1 = world.containers["c-b"].history_at(1)
    rec_b2 = world.containers["c-b"].history_at(2)
    assert rec_b1.lambda_served == pytest.approx(30.0)
    assert rec_b1.lambda_dropped == pytest.approx(0.0)
    assert rec_b2.lambda_served == pytest.approx(100.0)
    assert rec_b2.lambda_dropped + rec_b2.queue_len == pytest.approx(50.0)
