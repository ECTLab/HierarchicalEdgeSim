"""Reduced ProScale clone: SMA count, fixed size, greedy home then neighbor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from hierarchical_edge_sim.autoscaler.common.load import load_autoscaler_from_yaml
from hierarchical_edge_sim.autoscaler.proscale.formula import desired_instances, moving_average
from hierarchical_edge_sim.autoscaler.proscale.params import validate_params
from hierarchical_edge_sim.autoscaler.proscale.policy import build
from hierarchical_edge_sim.env.api import Env, UnmetDemandAction
from hierarchical_edge_sim.env.models import ContainerTickRecord


def test_moving_average_uses_last_n_samples():
    assert moving_average([10.0], 2) == pytest.approx(10.0)
    assert moving_average([10.0, 30.0], 2) == pytest.approx(20.0)
    assert moving_average([10.0, 30.0, 50.0], 2) == pytest.approx(40.0)


def test_desired_instances_cover_forecast_at_replica_throughput():
    # 3750 req/min is one 2.0-core Alibaba replica: (2.0 - 0.5) / 0.0004
    assert desired_instances(3750.0, 3750.0, min_replicas=1, max_replicas=100) == 1
    assert desired_instances(3751.0, 3750.0, min_replicas=1, max_replicas=100) == 2
    assert desired_instances(0.0, 3750.0, min_replicas=1, max_replicas=100) == 1
    assert desired_instances(1.0e9, 3750.0, min_replicas=1, max_replicas=8) == 8


def test_params_reject_unknown_and_bounds():
    params = validate_params({})
    assert params.sma_window == 2
    with pytest.raises(ValueError, match="unknown proscale"):
        validate_params({"target_util": 0.8})
    with pytest.raises(ValueError, match="sma_window"):
        validate_params({"sma_window": 0})


def _write_world(tmp_path: Path, *, two_ms: bool = False, neighbor_cpu: float = 8.0) -> Env:
    microservices: list[dict[str, Any]] = [
        {
            "id": "ms_a",
            "cpu_min_cores": 0.5,
            "cpu_max_cores": 4.0,
            "ram_min_mb": 256,
            "ram_max_mb": 2048,
            "cpu_per_request_cores": 0.01,
            "ram_per_request_mb": 0.5,
            "trace_file": "ms_a.csv",
            "containers": [
                {
                    "id": "c-ms_a-1",
                    "server_id": "c1-w1",
                    "cpu_alloc_cores": 2.0,
                    "ram_alloc_mb": 1024,
                }
            ],
        }
    ]
    if two_ms:
        microservices.append(
            {
                "id": "ms_b",
                "cpu_min_cores": 0.5,
                "cpu_max_cores": 4.0,
                "ram_min_mb": 256,
                "ram_max_mb": 2048,
                "cpu_per_request_cores": 0.01,
                "ram_per_request_mb": 0.5,
                "trace_file": "ms_b.csv",
                "containers": [
                    {
                        "id": "c-ms_b-1",
                        "server_id": "c1-w1",
                        "cpu_alloc_cores": 2.0,
                        "ram_alloc_mb": 1024,
                    }
                ],
            }
        )
    home_cpu = 4.0 if two_ms else 8.0
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 60.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": home_cpu, "ram_cap_mb": 8192}],
                },
                {
                    "id": "c2",
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": neighbor_cpu, "ram_cap_mb": 8192}],
                },
            ],
            "vicinities": [{"id": "v1", "members": ["c1", "c2"], "leader": "c1"}],
            "latency_ms": [{"from": "c1", "to": "c2", "ms": 5.0}],
        },
        "apps": [{"id": "demo_app", "microservices": microservices}],
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    for name in ("ms_a", "ms_b"):
        rows = ["time_unit,requests"] + [f"{i},50" for i in range(1, 6)]
        (tdir / f"{name}.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def _push(env: Env, ms_id: str, tau: int, incoming: float) -> None:
    ids = list(env.get_microservice(ms_id).container_ids)
    share = incoming / len(ids)
    for cid in ids:
        container = env.get_container(cid)
        container.append_history(
            ContainerTickRecord(
                tau=tau,
                lambda_in=share,
                lambda_served=share,
                lambda_dropped=0.0,
                cpu_usage_cores=container.cpu_alloc_cores,
                ram_usage_mb=container.ram_alloc_mb,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
                q_cpu=1.0,
                q_ram=1.0,
            )
        )
    env.state.current_tau = tau


def test_high_forecast_spawns_fixed_size_on_home_then_neighbor(tmp_path: Path):
    env = _write_world(tmp_path)
    scaler = build({"sma_window": 2})
    # μ of a 2.0-core replica is (2.0-0.5)/0.01 = 150. 2000 → ceil(2000/150) = 14.
    _push(env, "ms_a", 1, 2000.0)
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert spawns
    assert all(a.cpu_alloc_cores == 2.0 and a.ram_alloc_mb == 1024.0 for a in spawns)
    assert not any(getattr(a, "type", "") == "resize" for a in actions)
    home = [a for a in spawns if a.server_id == "c1-w1"]
    neighbor = [a for a in spawns if a.server_id == "c2-w1"]
    # Seed already uses 2 of 8 cores, so three more 2.0 replicas fill home.
    assert len(home) == 3
    assert all(a.reason == "horizontal_spawn" and a.loan_tier == "" for a in home)
    assert neighbor
    assert all(a.reason == "vicinity_spawn" and a.loan_tier == "vicinity" for a in neighbor)


def test_scale_down_releases_neighbor_before_the_seed(tmp_path: Path):
    env = _write_world(tmp_path)
    scaler = build({"sma_window": 2, "min_replicas": 1})
    _push(env, "ms_a", 1, 2000.0)
    up = scaler.on_tick_end(env, 1)
    env.apply_actions(up, tau=1, autoscaler_name="proscale")
    assert any(
        env.get_server(env.get_container(cid).server_id).cluster_id == "c2"
        for cid in env.get_microservice("ms_a").container_ids
    )
    _push(env, "ms_a", 2, 10.0)
    scaler.on_tick_end(env, 2)
    _push(env, "ms_a", 3, 10.0)
    down = scaler.on_tick_end(env, 3)
    terms = [a for a in down if getattr(a, "type", "") == "terminate"]
    assert terms
    assert all(a.container_id != "c-ms_a-1" for a in terms)
    assert any(a.reason == "vicinity_terminate" for a in terms)
    env.apply_actions(down, tau=3, autoscaler_name="proscale")
    assert len(env.get_microservice("ms_a").container_ids) == 1


def test_earlier_ms_takes_raw_free_cores(tmp_path: Path):
    env = _write_world(tmp_path, two_ms=True, neighbor_cpu=2.0)
    scaler = build({"sma_window": 1, "max_replicas": 20})
    # Home is full (two seeds). One neighbor slot of 2.0 cores remains.
    _push(env, "ms_a", 1, 5000.0)
    _push(env, "ms_b", 1, 5000.0)
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert len(spawns) == 1
    assert spawns[0].ms_id == "ms_a"
    assert spawns[0].server_id == "c2-w1"
    unmet = [a for a in actions if isinstance(a, UnmetDemandAction)]
    assert {a.ms_id for a in unmet} == {"ms_a", "ms_b"}


def test_yaml_loads_campaign12_proscale(project_root: Path):
    path = project_root / "configs" / "36-demo_alibaba_2ms_vicinity_proscale.yaml"
    scaler = load_autoscaler_from_yaml(path)
    assert scaler is not None
    assert scaler.name == "proscale"
    assert scaler.params.sma_window == 2
    cfg = yaml.safe_load(path.read_text())
    assert "12-alibaba-2ms-eval" in cfg["sim"]["results_dir"]
    env = Env.from_config(path)
    assert sorted(env.list_microservices()) == ["ms150", "ms588"]
    assert env.vicinity_of("c1") == "v1"
