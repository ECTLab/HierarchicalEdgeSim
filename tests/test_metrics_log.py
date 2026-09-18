from __future__ import annotations

import csv
import json
import math
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from hierarchical_edge_sim.env.config import load_yaml
from hierarchical_edge_sim.env.engine import run_ticks
from hierarchical_edge_sim.env.metrics_log import make_run_id, write_run_outputs
from hierarchical_edge_sim.env.traces import load_traces
from hierarchical_edge_sim.env.validate import validate_or_raise
from hierarchical_edge_sim.env.world import build_world


VALID_TRACE = "time_unit,requests\n1,0\n2,25\n3,80\n4,120\n5,50\n"


def _tiny_dict(results_dir: str = "results/") -> dict[str, Any]:
    return {
        "sim": {"tick_sec": 1.0, "results_dir": results_dir, "seed": 42},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [
                        {"id": "c1-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 16384},
                        {"id": "c1-w2", "cpu_cap_cores": 8.0, "ram_cap_mb": 16384},
                    ],
                }
            ]
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


def _write_tmp_config_tree(tmp_path: Path, config_data: dict[str, Any], traces: dict[str, str]) -> Path:
    root = tmp_path / "project"
    traces_dir = root / "traces" / "demo"
    traces_dir.mkdir(parents=True, exist_ok=True)
    for fname, content in traces.items():
        (traces_dir / fname).write_text(content, encoding="utf-8")

    config_dir = root / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "00-tiny.yaml"
    config_path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
    return config_path


def _run_and_write(tmp_path: Path) -> Path:
    cfg = deepcopy(_tiny_dict())
    config_path = _write_tmp_config_tree(tmp_path, cfg, {"api.csv": VALID_TRACE})
    raw = load_yaml(config_path)
    spec = validate_or_raise(raw)
    world = build_world(spec)
    traces = load_traces(spec)
    run_ticks(world=world, traces=traces, world_spec=spec)
    run_id = make_run_id(spec.sim.seed, now_utc=datetime(2026, 8, 6, 8, 15, 0, tzinfo=UTC))
    return write_run_outputs(world=world, world_spec=spec, traces=traces, run_id=run_id)


def test_results_tree_layout(tmp_path: Path):
    run_dir = _run_and_write(tmp_path)
    assert run_dir.name == "42_20260806T081500Z"
    assert (run_dir / "run_meta.yaml").is_file()
    assert (run_dir / "apps" / "demo_app" / "api" / "c-api-1.meta.json").is_file()
    assert (run_dir / "apps" / "demo_app" / "api" / "c-api-1.log.csv").is_file()


def test_log_csv_columns(tmp_path: Path):
    run_dir = _run_and_write(tmp_path)
    csv_path = run_dir / "apps" / "demo_app" / "api" / "c-api-1.log.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
    assert header == [
        "time_unit",
        "cpu_core_capacity",
        "ram_size_capacity_mb",
        "cpu_core_used",
        "ram_size_used_mb",
        "incoming_requests",
        "served_requests",
        "dropped_requests",
        "t_net_sec",
        "t_mean_offered_sec",
        "t_p95_offered_sec",
        "t_p99_offered_sec",
        "sla_miss_requests",
        "t_wait_sec",
    ]


def test_log_csv_golden_tick4(tmp_path: Path):
    run_dir = _run_and_write(tmp_path)
    csv_path = run_dir / "apps" / "demo_app" / "api" / "c-api-1.log.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    tick4 = rows[3]
    assert tick4["time_unit"] == "4"
    assert float(tick4["incoming_requests"]) == 120.0
    assert float(tick4["served_requests"]) == 50.0
    assert float(tick4["dropped_requests"]) == 70.0
    assert float(tick4["cpu_core_used"]) == 1.0
    assert float(tick4["t_p99_offered_sec"]) == pytest.approx(1.0, abs=1e-4)
    assert float(tick4["sla_miss_requests"]) == pytest.approx(70.0 + 50.0 * math.exp(-0.5))


def test_run_meta_includes_vicinities_list(tmp_path: Path):
    run_dir = _run_and_write(tmp_path)
    meta = yaml.safe_load((run_dir / "run_meta.yaml").read_text(encoding="utf-8"))
    assert meta["config"]["vicinities"] == []


def test_run_meta_serializes_vicinity_members(tmp_path: Path):
    cfg = deepcopy(_tiny_dict())
    cfg["topology"]["vicinities"] = [{"id": "v1", "members": ["c1"], "leader": "c1"}]
    config_path = _write_tmp_config_tree(tmp_path, cfg, {"api.csv": VALID_TRACE})
    raw = load_yaml(config_path)
    spec = validate_or_raise(raw)
    world = build_world(spec)
    traces = load_traces(spec)
    run_ticks(world=world, traces=traces, world_spec=spec)
    run_id = make_run_id(spec.sim.seed, now_utc=datetime(2026, 8, 6, 8, 20, 0, tzinfo=UTC))
    run_dir = write_run_outputs(world=world, world_spec=spec, traces=traces, run_id=run_id)
    meta = yaml.safe_load((run_dir / "run_meta.yaml").read_text(encoding="utf-8"))
    assert meta["config"]["vicinities"] == [{"id": "v1", "members": ["c1"], "leader": "c1"}]


def test_terminated_container_history_is_flushed(tmp_path: Path):
    from datetime import UTC, datetime

    from hierarchical_edge_sim.env.api import Env

    cfg = deepcopy(_tiny_dict(results_dir=str(tmp_path / "results")))
    config_path = _write_tmp_config_tree(tmp_path, cfg, {"api.csv": VALID_TRACE})
    env = Env.from_config(config_path)
    spawned = env.spawn(ms_id="api", server_id="c1-w2")
    assert spawned.ok
    env.run(max_ticks=2, now_utc=datetime(2026, 8, 6, 9, 0, 0, tzinfo=UTC))
    env.terminate(spawned.container_id)
    run_dir = write_run_outputs(
        world=env.world,
        world_spec=env.world_spec,
        traces=env.traces,
        run_id="retired_flush",
        retired_containers=env.retired_containers,
    )
    log_path = run_dir / "apps" / "demo_app" / "api" / f"{spawned.container_id}.log.csv"
    assert log_path.is_file()
    with log_path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["time_unit"] for r in rows] == ["1", "2"]
    assert spawned.container_id not in env.world.containers


def test_auto_respawn_keeps_retired_and_live_logs(tmp_path: Path):
    from datetime import UTC, datetime

    from hierarchical_edge_sim.env.api import Env

    cfg = deepcopy(_tiny_dict(results_dir=str(tmp_path / "results")))
    config_path = _write_tmp_config_tree(tmp_path, cfg, {"api.csv": VALID_TRACE})
    env = Env.from_config(config_path)
    first = env.spawn(ms_id="api", server_id="c1-w2")
    assert first.ok
    env.run(max_ticks=2, now_utc=datetime(2026, 8, 16, 8, 0, 0, tzinfo=UTC))
    env.terminate(first.container_id)
    second = env.spawn(ms_id="api", server_id="c1-w2")
    assert second.ok
    assert second.container_id != first.container_id
    run_dir = write_run_outputs(
        world=env.world,
        world_spec=env.world_spec,
        traces=env.traces,
        run_id="respawn_logs",
        retired_containers=env.retired_containers,
    )
    first_log = run_dir / "apps" / "demo_app" / "api" / f"{first.container_id}.log.csv"
    second_log = run_dir / "apps" / "demo_app" / "api" / f"{second.container_id}.log.csv"
    assert first_log.is_file()
    assert second_log.is_file()
    with first_log.open("r", encoding="utf-8", newline="") as f:
        assert [r["time_unit"] for r in csv.DictReader(f)] == ["1", "2"]


def test_meta_json_fields(tmp_path: Path):
    run_dir = _run_and_write(tmp_path)
    meta_path = run_dir / "apps" / "demo_app" / "api" / "c-api-1.meta.json"
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    for required in [
        "container_id",
        "app_id",
        "microservice_id",
        "server_id",
        "cluster_id",
        "cpu_min_cores",
        "cpu_max_cores",
        "ram_min_mb",
        "ram_max_mb",
        "cpu_per_request_cores",
        "ram_per_request_mb",
        "initial_cpu_alloc_cores",
        "initial_ram_alloc_mb",
    ]:
        assert required in payload
