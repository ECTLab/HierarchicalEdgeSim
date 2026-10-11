"""Edge-first horizontal scaling onto an optional cloud cluster."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.autoscaler.cloud_spill.policy import build
from hierarchical_edge_sim.env.api import Env, UnmetDemandAction
from hierarchical_edge_sim.env.models import ContainerTickRecord


def _world(tmp_path: Path, *, edge_cores: float, cloud: bool) -> Env:
    clusters: list[dict[str, Any]] = [
        {
            "id": "edge",
            "servers": [
                {"id": "edge-w1", "cpu_cap_cores": edge_cores, "ram_cap_mb": 4096},
            ],
        }
    ]
    topology: dict[str, Any] = {"clusters": clusters}
    if cloud:
        clusters.append(
            {
                "id": "cloud",
                "servers": [
                    {"id": "cloud-w1", "cpu_cap_cores": 32.0, "ram_cap_mb": 32768},
                ],
            }
        )
        topology["vicinities"] = [
            {"id": "edge-site", "members": ["edge"], "leader": "edge"},
            {"id": "cloud-site", "members": ["cloud"], "leader": "cloud"},
        ]
        topology["latency_ms"] = [{"from": "edge", "to": "cloud", "ms": 50.0}]
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 60.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": topology,
        "apps": [
            {
                "id": "demo_app",
                "microservices": [
                    {
                        "id": "api",
                        "cpu_min_cores": 0.5,
                        "cpu_max_cores": 4.0,
                        "ram_min_mb": 256,
                        "ram_max_mb": 4096,
                        "cpu_per_request_cores": 0.0004,
                        "ram_per_request_mb": 0.02,
                        "trace_file": "api.csv",
                        "containers": [
                            {
                                "id": "c-api-1",
                                "server_id": "edge-w1",
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


def _push_util(env: Env, tau: int, *, usage_frac: float) -> None:
    for cid in env.get_microservice("api").container_ids:
        container = env.get_container(cid)
        usage = container.cpu_alloc_cores * usage_frac
        container.append_history(
            ContainerTickRecord(
                tau=tau,
                lambda_in=10.0,
                lambda_served=10.0,
                lambda_dropped=0.0,
                cpu_usage_cores=usage,
                ram_usage_mb=container.ram_alloc_mb * usage_frac,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
                q_cpu=usage_frac,
                q_ram=usage_frac,
            )
        )
    env.state.current_tau = tau


def test_full_edge_spawns_on_cloud(tmp_path: Path):
    env = _world(tmp_path, edge_cores=2.0, cloud=True)
    scaler = build({"cloud_cluster_id": "cloud", "scale_down_window": 1})
    _push_util(env, 1, usage_frac=1.0)
    actions = scaler.on_tick_end(env, 1)
    spawns = [action for action in actions if getattr(action, "type", "") == "spawn"]
    assert len(spawns) == 1
    assert spawns[0].server_id == "cloud-w1"
    assert spawns[0].reason == "cloud_spawn"
    assert spawns[0].cpu_alloc_cores == 2.0
    results = env.apply_actions(actions, tau=1, autoscaler_name="cloud_spill")
    assert results[0].ok
    assert env.get_server("cloud-w1").cluster_id == "cloud"
    assert len(env.get_microservice("api").container_ids) == 2


def test_edge_room_stays_on_edge(tmp_path: Path):
    env = _world(tmp_path, edge_cores=8.0, cloud=True)
    scaler = build({"cloud_cluster_id": "cloud", "scale_down_window": 1})
    _push_util(env, 1, usage_frac=1.0)
    actions = scaler.on_tick_end(env, 1)
    spawns = [action for action in actions if getattr(action, "type", "") == "spawn"]
    assert len(spawns) == 1
    assert spawns[0].server_id == "edge-w1"
    assert spawns[0].reason == "edge_spawn"


def test_full_edge_without_cloud_is_unmet(tmp_path: Path):
    env = _world(tmp_path, edge_cores=2.0, cloud=False)
    scaler = build({"scale_down_window": 1})
    _push_util(env, 1, usage_frac=1.0)
    actions = scaler.on_tick_end(env, 1)
    assert not any(getattr(action, "type", "") == "spawn" for action in actions)
    unmet = [action for action in actions if isinstance(action, UnmetDemandAction)]
    assert len(unmet) == 1
    assert unmet[0].cluster_id == "edge"


def test_scale_down_reclaims_cloud_before_edge(tmp_path: Path):
    env = _world(tmp_path, edge_cores=2.0, cloud=True)
    scaler = build(
        {
            "cloud_cluster_id": "cloud",
            "scale_down_window": 1,
            "tolerance": 0.10,
            "target_util": 0.80,
        }
    )
    _push_util(env, 1, usage_frac=1.0)
    env.apply_actions(scaler.on_tick_end(env, 1), tau=1, autoscaler_name="cloud_spill")
    assert len(env.get_microservice("api").container_ids) == 2
    _push_util(env, 2, usage_frac=0.05)
    actions = scaler.on_tick_end(env, 2)
    terms = [action for action in actions if getattr(action, "type", "") == "terminate"]
    assert len(terms) == 1
    assert terms[0].container_id != "c-api-1"
    assert terms[0].reason == "cloud_terminate"
