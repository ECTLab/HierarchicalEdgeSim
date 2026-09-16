"""Leftover after VicinityRound is LogUnmetDemand; no out-of-vicinity spawn."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.autoscaler.reactive_local.policy import build
from hierarchical_edge_sim.env.api import Env, NeedVicinityHelpAction, UnmetDemandAction
from hierarchical_edge_sim.env.models import ContainerTickRecord


VALID_TRACE = "time_unit,requests\n" + "\n".join(f"{i},50" for i in range(1, 11)) + "\n"


def _write_three_cluster(
    tmp_path: Path,
    *,
    c1_cpu: float = 1.0,
    c2_cpu: float = 0.4,
    c3_cpu: float = 8.0,
    c2_ram: float = 256.0,
    c3_ram: float = 4096.0,
) -> Env:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": c1_cpu, "ram_cap_mb": 2048}],
                },
                {
                    "id": "c2",
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": c2_cpu, "ram_cap_mb": c2_ram}],
                },
                {
                    "id": "c3",
                    "servers": [{"id": "c3-w1", "cpu_cap_cores": c3_cpu, "ram_cap_mb": c3_ram}],
                },
            ],
            "vicinities": [
                {"id": "v1", "members": ["c1", "c2"], "leader": "c1"},
                {"id": "v2", "members": ["c3"], "leader": "c3"},
            ],
        },
        "apps": [
            {
                "id": "demo_app",
                "microservices": [
                    {
                        "id": "api",
                        "cpu_min_cores": 0.5,
                        "cpu_max_cores": 1.0,
                        "ram_min_mb": 256,
                        "ram_max_mb": 2048,
                        "cpu_per_request_cores": 0.01,
                        "ram_per_request_mb": 0.5,
                        "trace_file": "api.csv",
                        "containers": [
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 2048,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    (tdir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def _push_drops(env: Env, tau: int, *, drop: float = 40.0) -> None:
    for cid in env.get_microservice("api").container_ids:
        c = env.get_container(cid)
        served = 10.0
        c.append_history(
            ContainerTickRecord(
                tau=tau,
                lambda_in=served + drop,
                lambda_served=served,
                lambda_dropped=drop,
                cpu_usage_cores=c.cpu_alloc_cores,
                ram_usage_mb=c.ram_alloc_mb,
                cpu_alloc_cores=c.cpu_alloc_cores,
                ram_alloc_mb=c.ram_alloc_mb,
                q_cpu=1.0,
                q_ram=1.0,
            )
        )
    env.state.current_tau = tau


def _up_scaler():
    return build(
        {"x_up_streak": 1, "y_down_streak": 99, "cooldown_ticks": 0, "sustained_up_streak": 99}
    )


def test_vicinity_exhausted_logs_unmet_demand_not_outside_spawn(tmp_path):
    env = _write_three_cluster(tmp_path)
    scaler = _up_scaler()
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)
    helps = [a for a in actions if isinstance(a, UnmetDemandAction)]
    assert len(helps) == 1
    assert helps[0].cluster_id == "c1"
    assert not any(isinstance(a, NeedVicinityHelpAction) for a in actions)
    env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert any(
        row.action_type == "unmet_demand" and row.result_code == "LOGGED"
        for row in env.action_log
    )
    assert env.get_server("c3-w1").loans == []
    assert env.get_server("c2-w1").loans == []


def test_fat_outside_cluster_is_not_a_placement_candidate(tmp_path):
    env = _write_three_cluster(tmp_path, c2_cpu=99.0, c2_ram=8192.0, c3_cpu=8.0)
    scaler = _up_scaler()
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert len(spawns) == 1
    assert spawns[0].server_id == "c2-w1"
    assert spawns[0].reason == "vicinity_spawn"
    assert spawns[0].loan_tier == "vicinity"
    assert not any(a.server_id == "c3-w1" for a in spawns)
    assert not any(isinstance(a, UnmetDemandAction) for a in actions)
