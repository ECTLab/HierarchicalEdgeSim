"""Tests for RootOrchestrator and static topology.vicinities."""

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
    with pytest.raises(RuntimeError, match="topology.vicinities"):
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
    run_dir = env.run()
    assert env.get_time() == env.traces.horizon
    assert run_dir.exists()
    assert env.root is not None


def test_beg_admit_not_implemented(tmp_path):
    path = _write_config(tmp_path, _two_cluster_dict())
    env = Env.from_config(path)
    assert env.root is not None
    with pytest.raises(NotImplementedError, match="beg_admit"):
        env.root.beg_admit()


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
    path = project_root / "configs" / "demo_60_two_clusters.yaml"
    env = Env.from_config(path)
    assert env.root is not None
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
