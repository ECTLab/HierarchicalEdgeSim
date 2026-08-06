from __future__ import annotations

import csv
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    config_path = config_dir / "tiny.yaml"
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
