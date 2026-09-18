"""Vicinity leader role: every member reports; only ℓ(V) computes Π."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.autoscaler.reactive_local.help import HelpRequest
from hierarchical_edge_sim.autoscaler.reactive_local.policy import build
from hierarchical_edge_sim.autoscaler.reactive_local.vicinity import (
    apply_vicinity_plan,
    collect_reports,
    schedule_vicinity_help,
    schedule_vicinity_plan,
)
from hierarchical_edge_sim.env.api import Env, SpawnAction
from hierarchical_edge_sim.env.models import ContainerTickRecord


VALID_TRACE = "time_unit,requests\n" + "\n".join(f"{i},50" for i in range(1, 11)) + "\n"


def _write_world(tmp_path: Path, *, leader: str = "c1") -> Env:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": 1.0, "ram_cap_mb": 2048}],
                },
                {
                    "id": "c2",
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
            ],
            "vicinities": [{"id": "v1", "members": ["c1", "c2"], "leader": leader}],
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


def _rho(env: Env) -> HelpRequest:
    spec = env.get_ms_spec("api")
    return HelpRequest(
        seq=0,
        tau=1,
        ms_id="api",
        home_cluster_id="c1",
        remain_cpu=0.5,
        remain_ram=256.0,
        cpu_min=spec.cpu_min_cores,
        ram_min=spec.ram_min_mb,
        min_mu_step=25.0,
        t_det=1,
    )


def _push_drops(env: Env, tau: int) -> None:
    for cid in env.get_microservice("api").container_ids:
        c = env.get_container(cid)
        c.append_history(
            ContainerTickRecord(
                tau=tau,
                lambda_in=80.0,
                lambda_served=50.0,
                lambda_dropped=30.0,
                cpu_usage_cores=c.cpu_alloc_cores,
                ram_usage_mb=c.ram_alloc_mb,
                cpu_alloc_cores=c.cpu_alloc_cores,
                ram_alloc_mb=c.ram_alloc_mb,
                q_cpu=1.0,
                q_ram=1.0,
            )
        )
    env.state.current_tau = tau


def test_collect_reports_includes_empty_member_offer(tmp_path):
    env = _write_world(tmp_path)
    reports = collect_reports(env, [_rho(env)], [], 1)
    assert [r.cluster_id for r in reports] == ["c1", "c2"]
    by_id = {r.cluster_id: r for r in reports}
    assert len(by_id["c1"].requests) == 1
    assert by_id["c2"].requests == []
    assert by_id["c2"].releases == []


def test_barrier_requires_every_member_before_leader_schedules(tmp_path):
    env = _write_world(tmp_path)
    reports = collect_reports(env, [_rho(env)], [], 1)
    members = set(env.list_vicinity_members("v1"))
    assert {r.cluster_id for r in reports} == members
    plan = schedule_vicinity_plan(env, "v1", reports, pending=[], tau=1)
    assert plan.leader_cluster_id == env.leader_of("v1")
    assert env.is_leader(plan.leader_cluster_id)
    assert not env.is_leader("c2")
    assert any(e.act == "spawn" for e in plan.entries)


def test_only_leader_cluster_computes_the_plan(tmp_path):
    env = _write_world(tmp_path, leader="c2")
    assert env.leader_of("v1") == "c2"
    assert env.is_leader("c2")
    assert not env.is_leader("c1")
    reports = collect_reports(env, [_rho(env)], [], 1)
    scheduled_as: list[str] = []
    members = env.list_vicinity_members("v1")
    for cluster_id in members:
        if not env.is_leader(cluster_id):
            continue
        scheduled_as.append(cluster_id)
        plan = schedule_vicinity_plan(env, "v1", reports, pending=[], tau=1)
        assert plan.leader_cluster_id == "c2"
        assert any(e.act == "spawn" and e.server_id == "c2-w1" for e in plan.entries)
    assert scheduled_as == ["c2"]


def test_apply_vicinity_plan_turns_entries_into_env_actions(tmp_path):
    env = _write_world(tmp_path)
    reports = collect_reports(env, [_rho(env)], [], 1)
    plan = schedule_vicinity_plan(env, "v1", reports, pending=[], tau=1)
    actions, unmet = apply_vicinity_plan(env, plan)
    assert unmet == []
    spawns = [a for a in actions if isinstance(a, SpawnAction)]
    assert len(spawns) == 1
    assert spawns[0].server_id == "c2-w1"
    assert spawns[0].reason == "vicinity_spawn"
    assert spawns[0].loan_tier == "vicinity"
    assert spawns[0].actor_cluster_id == "c2"


def test_neighbor_leader_places_packed_spawn_for_home_request(tmp_path):
    env = _write_world(tmp_path, leader="c2")
    scaler = build(
        {
            "x_up_streak": 1,
            "y_down_streak": 99,
            "cooldown_ticks": 0,
            "sustained_up_streak": 99,
        }
    )
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert spawns
    assert all(a.server_id == "c2-w1" for a in spawns)
    assert all(a.reason == "vicinity_spawn" for a in spawns)


def test_schedule_vicinity_help_goes_through_plan(tmp_path):
    env = _write_world(tmp_path)
    actions, unmet = schedule_vicinity_help(env, [_rho(env)], pending=[], tau=1)
    assert unmet == []
    assert any(getattr(a, "reason", "") == "vicinity_spawn" for a in actions)
