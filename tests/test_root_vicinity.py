"""Tests for RootOrchestrator: YAML vicinities and Algorithm 1 partition."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.config import load_yaml
from hierarchical_edge_sim.env.root import RootOrchestrator
from hierarchical_edge_sim.env.validate import ConfigError, validate, validate_or_raise
from hierarchical_edge_sim.env.world import build_world


VALID_TRACE = "time_unit,requests\n1,0\n2,25\n3,80\n4,120\n5,50\n"


def _two_cluster_dict() -> dict[str, Any]:
    return {
        "sim": {"tick_sec": 1.0, "results_dir": "results/", "seed": 42},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 16384}],
                },
                {
                    "id": "c2",
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 4.0, "ram_cap_mb": 8192}],
                },
            ],
            "vicinities": [
                {"id": "v1", "members": ["c1", "c2"], "leader": "c1"},
            ],
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
                        "ram_max_mb": 4096,
                        "cpu_per_request_cores": 0.01,
                        "ram_per_request_mb": 0.5,
                        "trace_file": "api.csv",
                        "containers": [
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 512,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _write_config(tmp_path: Path, config_data: dict[str, Any]) -> Path:
    trace_dir = tmp_path / "traces" / "demo"
    trace_dir.mkdir(parents=True, exist_ok=True)
    (trace_dir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
    return config_path


def test_configs_without_vicinities_keep_root_none(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    assert env.root is None
    assert env.world.root is None
    assert env.get_cluster("c1").vicinity_id is None
    assert env.get_cluster("c1").is_vicinity_leader is False
    with pytest.raises(RuntimeError, match="World.root is None"):
        env.list_vicinities()


def test_valid_vicinities_build_root_and_mirrors(tmp_path):
    path = _write_config(tmp_path, _two_cluster_dict())
    env = Env.from_config(path)

    assert env.root is not None
    assert isinstance(env.root, RootOrchestrator)
    assert env.list_vicinities() == ["v1"]
    assert env.vicinity_of("c1") == "v1"
    assert env.vicinity_of("c2") == "v1"
    assert env.leader_of("v1") == "c1"
    assert env.is_leader("c1") is True
    assert env.is_leader("c2") is False
    assert env.list_vicinity_members("v1") == ["c1", "c2"]

    c1 = env.get_cluster("c1")
    c2 = env.get_cluster("c2")
    assert c1.vicinity_id == "v1"
    assert c1.is_vicinity_leader is True
    assert c2.vicinity_id == "v1"
    assert c2.is_vicinity_leader is False


def test_run_with_vicinities_does_not_touch_root(tmp_path):
    path = _write_config(tmp_path, _two_cluster_dict())
    env = Env.from_config(path)
    run_dir = env.run(max_ticks=3)
    assert env.get_time() == 3
    assert run_dir.exists()
    assert env.root is not None


@pytest.mark.parametrize(
    ("name", "mutate", "expected_substring"),
    [
        (
            "leader_not_in_members",
            lambda cfg: cfg["topology"]["vicinities"][0].update({"leader": "ghost"}),
            "must be listed in members",
        ),
        (
            "missing_cluster_cover",
            lambda cfg: cfg["topology"]["vicinities"][0].update({"members": ["c1"], "leader": "c1"}),
            "not assigned to any vicinity",
        ),
        (
            "cluster_in_two_vicinities",
            lambda cfg: cfg["topology"]["vicinities"].extend(
                [{"id": "v2", "members": ["c2", "c1"], "leader": "c2"}]
            ),
            "appears in more than one vicinity",
        ),
        (
            "unknown_member",
            lambda cfg: cfg["topology"]["vicinities"][0].update(
                {"members": ["c1", "c2", "ghost"], "leader": "c1"}
            ),
            "unknown cluster id",
        ),
        (
            "empty_members",
            lambda cfg: cfg["topology"]["vicinities"][0].update({"members": [], "leader": "c1"}),
            "must contain at least one member",
        ),
        (
            "duplicate_vicinity_id",
            lambda cfg: cfg["topology"]["vicinities"].append(
                {"id": "v1", "members": ["c2"], "leader": "c2"}
            ),
            "duplicate vicinity id",
        ),
    ],
)
def test_vicinity_reject_rules(name, mutate, expected_substring, tmp_path):
    cfg = deepcopy(_two_cluster_dict())
    mutate(cfg)
    path = _write_config(tmp_path / name, cfg)
    messages = [err.message for err in validate(load_yaml(path))]
    assert messages, f"expected validation errors for {name}"
    assert any(expected_substring in msg for msg in messages), (
        f"expected '{expected_substring}' in {messages}"
    )


def test_demo_60_two_clusters_has_vicinity(project_root: Path):
    path = project_root / "configs" / "04-demo_60_two_clusters.yaml"
    env = Env.from_config(path)
    assert env.root is not None
    assert env.root.vicinity_source == "algorithm"
    assert env.list_vicinities() == ["v1"]
    assert env.leader_of("v1") == "c1"
    assert set(env.list_vicinity_members("v1")) == {"c1", "c2"}


def test_validate_or_raise_rejects_bad_vicinity(tmp_path):
    cfg = deepcopy(_two_cluster_dict())
    cfg["topology"]["vicinities"][0]["leader"] = "c9"
    cfg["topology"]["vicinities"][0]["members"] = ["c1", "c2"]
    path = _write_config(tmp_path, cfg)
    with pytest.raises(ConfigError):
        validate_or_raise(load_yaml(path))


def test_world_without_vicinities_has_no_root(tiny_config_path):
    raw = load_yaml(tiny_config_path)
    spec = validate_or_raise(raw)
    world = build_world(spec)
    assert world.root is None
    assert spec.vicinities == []


def test_coords_run_algorithm_1_two_clusters(tmp_path):
    cfg = deepcopy(_two_cluster_dict())
    del cfg["topology"]["vicinities"]
    cfg["topology"]["clusters"][0]["coords"] = [0.0, 0.0]
    cfg["topology"]["clusters"][1]["coords"] = [1.0, 0.0]
    path = _write_config(tmp_path, cfg)
    env = Env.from_config(path)
    assert env.root is not None
    assert env.root.vicinity_source == "algorithm"
    assert env.list_vicinities() == ["v1"]
    assert set(env.list_vicinity_members("v1")) == {"c1", "c2"}
    assert env.leader_of("v1") == "c1"
    assert env.distance("c1", "c2") == pytest.approx(1.0)
    assert env.get_cluster("c1").is_vicinity_leader is True


def test_yaml_vicinities_override_coords(tmp_path):
    cfg = deepcopy(_two_cluster_dict())
    cfg["topology"]["clusters"][0]["coords"] = [0.0, 0.0]
    cfg["topology"]["clusters"][1]["coords"] = [1.0, 0.0]
    cfg["topology"]["vicinities"] = [
        {"id": "hand", "members": ["c1"], "leader": "c1"},
        {"id": "hand2", "members": ["c2"], "leader": "c2"},
    ]
    path = _write_config(tmp_path, cfg)
    env = Env.from_config(path)
    assert env.root is not None
    assert env.root.vicinity_source == "yaml"
    assert env.list_vicinities() == ["hand", "hand2"]
    assert env.leader_of("hand") == "c1"
    assert env.distance("c1", "c2") == pytest.approx(1.0)


def test_latency_ms_is_enough_without_coords(tmp_path):
    cfg = deepcopy(_two_cluster_dict())
    del cfg["topology"]["vicinities"]
    cfg["topology"]["latency_ms"] = [{"from": "c1", "to": "c2", "ms": 7.5}]
    path = _write_config(tmp_path, cfg)
    env = Env.from_config(path)
    assert env.root.vicinity_source == "algorithm"
    assert env.distance("c2", "c1") == pytest.approx(7.5)
    assert set(env.list_vicinity_members("v1")) == {"c1", "c2"}


def test_partition_knobs_without_geometry_rejected(tmp_path):
    cfg = deepcopy(_two_cluster_dict())
    del cfg["topology"]["vicinities"]
    cfg["topology"]["partition"] = {"k": 0.5}
    path = _write_config(tmp_path, cfg)
    messages = [err.message for err in validate(load_yaml(path))]
    assert any("VicinityPartitionAndLeaderElection" in msg for msg in messages)


def test_partial_coords_rejected(tmp_path):
    cfg = deepcopy(_two_cluster_dict())
    del cfg["topology"]["vicinities"]
    cfg["topology"]["clusters"][0]["coords"] = [0.0, 0.0]
    path = _write_config(tmp_path, cfg)
    messages = [err.message for err in validate(load_yaml(path))]
    assert any("every cluster must have coords" in msg for msg in messages)


def test_demo_partition_forms_two_pairs_and_an_isolate(project_root: Path):
    path = project_root / "configs" / "20-demo_partition.yaml"
    env = Env.from_config(path)
    assert env.root.vicinity_source == "algorithm"
    groups = {tuple(sorted(env.list_vicinity_members(vid))) for vid in env.list_vicinities()}
    assert groups == {
        ("west-a", "west-b"),
        ("east-a", "east-b"),
        ("isolated",),
    }
    west = env.vicinity_of("west-a")
    east = env.vicinity_of("east-a")
    assert env.leader_of(west) == "west-a"
    assert env.leader_of(east) == "east-a"
    assert env.leader_of(env.vicinity_of("isolated")) == "isolated"


def test_demo_partition_latency_uses_rtt_not_coords(project_root: Path):
    path = project_root / "configs" / "21-demo_partition_latency.yaml"
    env = Env.from_config(path)
    assert env.root.vicinity_source == "algorithm"
    assert all(c.coords is None for c in env.world_spec.clusters)
    assert env.distance("nyc-a", "nyc-b") == pytest.approx(2.0)
    assert env.distance("lon-a", "lon-b") == pytest.approx(2.0)
    assert env.distance("nyc-a", "lon-a") == pytest.approx(40.0)
    assert env.distance("remote", "nyc-b") == pytest.approx(200.0)
    groups = {tuple(sorted(env.list_vicinity_members(vid))) for vid in env.list_vicinities()}
    assert groups == {
        ("nyc-a", "nyc-b"),
        ("lon-a", "lon-b"),
        ("remote",),
    }
    assert env.leader_of(env.vicinity_of("nyc-a")) == "nyc-a"
    assert env.leader_of(env.vicinity_of("lon-a")) == "lon-a"
    assert env.leader_of(env.vicinity_of("remote")) == "remote"
