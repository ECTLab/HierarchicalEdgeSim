from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.env.api import Env


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


def _write_project(root: Path) -> Path:
    traces_dir = root / "traces" / "demo"
    traces_dir.mkdir(parents=True, exist_ok=True)
    (traces_dir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")

    config_dir = root / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "00-tiny.yaml"
    cfg = deepcopy(_tiny_dict())
    config_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return config_path


def test_two_runs_identical_logs(tmp_path: Path):
    fixed_now = datetime(2026, 8, 6, 8, 15, 0, tzinfo=UTC)

    config_path_1 = _write_project(tmp_path / "run_a")
    env1 = Env.from_config(config_path_1)
    out1 = env1.run(now_utc=fixed_now)
    log1 = (out1 / "apps" / "demo_app" / "api" / "c-api-1.log.csv").read_text(encoding="utf-8")

    config_path_2 = _write_project(tmp_path / "run_b")
    env2 = Env.from_config(config_path_2)
    out2 = env2.run(now_utc=fixed_now)
    log2 = (out2 / "apps" / "demo_app" / "api" / "c-api-1.log.csv").read_text(encoding="utf-8")

    assert out1.name == "42_20260806T081500Z"
    assert out2.name == "42_20260806T081500Z"
    assert log1 == log2
