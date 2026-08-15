"""S5: BEG — leftover after vicinity places outside the home vicinity."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.autoscaler.reactive_local.beg import schedule_beg
from hierarchical_edge_sim.autoscaler.reactive_local.help import HelpRequest
from hierarchical_edge_sim.autoscaler.reactive_local.policy import build
from hierarchical_edge_sim.env.api import Env, NeedGlobalHelpAction, NeedVicinityHelpAction
from hierarchical_edge_sim.env.loans import has_loan
from hierarchical_edge_sim.env.models import ContainerTickRecord, LoanTier, Vicinity
from hierarchical_edge_sim.env.root import RootOrchestrator


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


def test_rank_beg_candidates_excludes_home_vicinity_and_sorts_by_free():
    root = RootOrchestrator.from_vicinities(
        [
            Vicinity(id="v1", member_cluster_ids=["c1", "c2"], leader_cluster_id="c1"),
            Vicinity(id="v2", member_cluster_ids=["c3"], leader_cluster_id="c3"),
            Vicinity(id="v3", member_cluster_ids=["c4"], leader_cluster_id="c4"),
        ]
    )
    ranked = root.rank_beg_candidates(
        "c1", {"c1": 0.0, "c2": 99.0, "c3": 4.0, "c4": 8.0}
    )
    assert ranked == ["c4", "c3"]


def test_vicinity_full_spawns_on_outside_cluster_with_global_loan(tmp_path):
    env = _write_three_cluster(tmp_path)
    scaler = _up_scaler()
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert len(spawns) == 1
    spawn = spawns[0]
    assert spawn.server_id == "c3-w1"
    assert spawn.reason == "beg_spawn"
    assert spawn.loan_tier == "global"
    assert spawn.actor_cluster_id == "c1"
    assert not any(isinstance(a, NeedVicinityHelpAction) for a in actions)
    assert not any(isinstance(a, NeedGlobalHelpAction) for a in actions)
    results = env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert results[0].ok
    assert has_loan(env.get_server("c3-w1"), "c1", "api")
    assert env.get_server("c3-w1").loans[0].tier == LoanTier.GLOBAL
    assert env.get_server("c2-w1").loans == []


def test_beg_skips_home_vicinity_even_when_neighbor_has_more_free(tmp_path):
    env = _write_three_cluster(tmp_path, c2_cpu=99.0, c2_ram=8192.0, c3_cpu=8.0)
    req = HelpRequest(
        seq=0,
        tau=1,
        ms_id="api",
        home_cluster_id="c1",
        remain_cpu=0.5,
        remain_ram=256.0,
        cpu_min=0.5,
        ram_min=256.0,
    )
    spawns, unresolved = schedule_beg(env, [req], pending=[], tau=1)
    assert unresolved == []
    assert len(spawns) == 1
    assert spawns[0].server_id == "c3-w1"
    assert spawns[0].loan_tier == "global"


def test_beg_exhausted_logs_need_global_help(tmp_path):
    env = _write_three_cluster(tmp_path, c3_cpu=0.4, c3_ram=256.0)
    scaler = _up_scaler()
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)
    helps = [a for a in actions if isinstance(a, NeedGlobalHelpAction)]
    assert len(helps) == 1
    env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert any(
        row.action_type == "need_global_help" and row.result_code == "LOGGED"
        for row in env.action_log
    )
