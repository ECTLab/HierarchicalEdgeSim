"""Kubernetes HPA replica-count baseline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from hierarchical_edge_sim.autoscaler.common.load import load_autoscaler_from_yaml
from hierarchical_edge_sim.autoscaler.kubernetes_hpa.formula import (
    apply_scale_up_limit,
    desired_replicas,
)
from hierarchical_edge_sim.autoscaler.kubernetes_hpa.params import validate_params
from hierarchical_edge_sim.autoscaler.kubernetes_hpa.policy import build
from hierarchical_edge_sim.env.api import Env, UnmetDemandAction
from hierarchical_edge_sim.env.models import ContainerTickRecord


def test_desired_replicas_hpa_formula():
    assert desired_replicas(1, 1.0, target=0.80, tolerance=0.10, min_replicas=1, max_replicas=100) == 2
    assert desired_replicas(4, 1.0, target=0.80, tolerance=0.10, min_replicas=1, max_replicas=100) == 5
    # |0.85/0.80 - 1| = 0.0625 <= 0.10 → hold
    assert desired_replicas(4, 0.85, target=0.80, tolerance=0.10, min_replicas=1, max_replicas=100) == 4
    assert desired_replicas(5, 0.10, target=0.80, tolerance=0.10, min_replicas=1, max_replicas=100) == 1
    assert desired_replicas(0, 1.0, target=0.80, tolerance=0.10, min_replicas=1, max_replicas=100) == 1


def test_scale_up_limit_max_of_pods_and_percent():
    # 1 replica, formula wants 8 → cap at +4 pods (percent add is 1)
    assert apply_scale_up_limit(1, 8, scale_up_pods=4, scale_up_percent=100.0) == 5
    # 10 replicas, formula wants 25 → cap at +100% = 20
    assert apply_scale_up_limit(10, 25, scale_up_pods=4, scale_up_percent=100.0) == 20
    assert apply_scale_up_limit(4, 3, scale_up_pods=4, scale_up_percent=100.0) == 3


def test_params_reject_unknown_and_bounds():
    p = validate_params({})
    assert p.target_util == 0.80
    assert p.scale_down_window == 5
    with pytest.raises(ValueError, match="unknown kubernetes_hpa"):
        validate_params({"theta_high": 0.80})
    with pytest.raises(ValueError, match="target_util"):
        validate_params({"target_util": 0.0})


def _write_two_cluster_world(tmp_path: Path) -> Env:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [
                        {"id": "c1-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096},
                    ],
                },
                {
                    "id": "c2",
                    "servers": [
                        {"id": "c2-w1", "cpu_cap_cores": 32.0, "ram_cap_mb": 16384},
                    ],
                },
            ],
            "vicinities": [{"id": "v1", "members": ["c1", "c2"], "leader": "c1"}],
            "latency_ms": [{"from": "c1", "to": "c2", "ms": 5.0}],
        },
        "apps": [
            {
                "id": "demo_app",
                "microservices": [
                    {
                        "id": "api",
                        "cpu_min_cores": 0.5,
                        "cpu_max_cores": 4.0,
                        "ram_min_mb": 256,
                        "ram_max_mb": 2048,
                        "cpu_per_request_cores": 0.01,
                        "ram_per_request_mb": 0.5,
                        "trace_file": "api.csv",
                        "containers": [
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 2.0,
                                "ram_alloc_mb": 1024,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    rows = ["time_unit,requests"] + [f"{i},50" for i in range(1, 11)]
    (tdir / "api.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def _push_util(env: Env, tau: int, *, usage_frac: float, drop: float = 0.0) -> None:
    for cid in env.get_microservice("api").container_ids:
        c = env.get_container(cid)
        usage = c.cpu_alloc_cores * usage_frac
        served = 10.0
        c.append_history(
            ContainerTickRecord(
                tau=tau,
                lambda_in=served + drop,
                lambda_served=served,
                lambda_dropped=drop,
                cpu_usage_cores=usage,
                ram_usage_mb=c.ram_alloc_mb * usage_frac,
                cpu_alloc_cores=c.cpu_alloc_cores,
                ram_alloc_mb=c.ram_alloc_mb,
                q_cpu=usage_frac,
                q_ram=usage_frac,
            )
        )
    env.state.current_tau = tau


def test_saturated_spawns_on_home_not_neighbor(tmp_path):
    env = _write_two_cluster_world(tmp_path)
    scaler = build({"target_util": 0.80, "tolerance": 0.10, "scale_down_window": 1})
    _push_util(env, 1, usage_frac=1.0, drop=40.0)
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert len(spawns) == 1
    assert spawns[0].server_id == "c1-w1"
    assert spawns[0].cpu_alloc_cores == 2.0
    assert spawns[0].ram_alloc_mb == 1024.0
    assert spawns[0].reason == "horizontal_spawn"
    assert spawns[0].loan_tier == ""
    assert not any(getattr(a, "server_id", "") == "c2-w1" for a in actions)
    assert not any(getattr(a, "reason", "") == "vicinity_spawn" for a in actions)
    assert not any(getattr(a, "type", "") == "resize" for a in actions)


def test_full_home_logs_unmet_instead_of_vicinity(tmp_path):
    env = _write_two_cluster_world(tmp_path)
    # Fill the only home worker so a 2.0 template cannot land; c2 is fat.
    env.get_container("c-api-1").cpu_alloc_cores = 8.0
    env.get_container("c-api-1").ram_alloc_mb = 1024.0
    scaler = build({"target_util": 0.80, "scale_down_window": 1})
    _push_util(env, 1, usage_frac=1.0)
    actions = scaler.on_tick_end(env, 1)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)
    unmet = [a for a in actions if isinstance(a, UnmetDemandAction)]
    assert len(unmet) == 1
    assert unmet[0].cluster_id == "c1"


def test_scale_down_uses_window_max(tmp_path):
    env = _write_two_cluster_world(tmp_path)
    scaler = build({"target_util": 0.80, "tolerance": 0.10, "scale_down_window": 3, "min_replicas": 1})
    _push_util(env, 1, usage_frac=1.0)
    up = scaler.on_tick_end(env, 1)
    env.apply_actions(up, tau=1, autoscaler_name="kubernetes_hpa")
    assert len(env.get_microservice("api").container_ids) == 2

    _push_util(env, 2, usage_frac=0.05)
    hold = scaler.on_tick_end(env, 2)
    # Window is [2, 1]; max=2 → do not shrink yet.
    assert not any(getattr(a, "type", "") == "terminate" for a in hold)

    _push_util(env, 3, usage_frac=0.05)
    _push_util(env, 4, usage_frac=0.05)
    # After two more low ticks the window is all 1s (maxlen 3) once 2 has slid out.
    down = scaler.on_tick_end(env, 3)
    down2 = scaler.on_tick_end(env, 4)
    terms = [a for a in down + down2 if getattr(a, "type", "") == "terminate"]
    assert terms
    assert all(a.container_id != "c-api-1" for a in terms)
    assert all(a.reason == "horizontal_terminate" for a in terms)


def test_yaml_loads_campaign12_hpa(project_root: Path):
    path = project_root / "configs" / "35-demo_alibaba_2ms_vicinity_hpa.yaml"
    scaler = load_autoscaler_from_yaml(path)
    assert scaler is not None
    assert scaler.name == "kubernetes_hpa"
    assert scaler.params.target_util == pytest.approx(0.80)
    assert scaler.params.scale_down_window == 5
    cfg = yaml.safe_load(path.read_text())
    assert "12-alibaba-2ms-eval" in cfg["sim"]["results_dir"]


def test_campaign12_hpa_world_is_home_only_two_ms(project_root: Path):
    from hierarchical_edge_sim.env.api import Env

    env = Env.from_config(project_root / "configs" / "35-demo_alibaba_2ms_vicinity_hpa.yaml")
    assert sorted(env.list_microservices()) == ["ms150", "ms588"]
    assert env.get_app_owner_cluster_id("ms588") == "c1"
    assert env.vicinity_of("c1") == "v1"
    assert set(env.get_vicinity("v1").member_cluster_ids) == {"c1", "c2"}
