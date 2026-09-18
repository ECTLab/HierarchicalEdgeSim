"""SchedulePlacements: grow existing, distance order, recycle onto home."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.autoscaler.reactive_local.help import HelpRequest, ReleaseIntent
from hierarchical_edge_sim.autoscaler.reactive_local.place import (
    grow_existing_instances,
    rank_placement_servers,
    snapshot_free,
    subtract_pending,
)
from hierarchical_edge_sim.autoscaler.reactive_local.vicinity import (
    apply_vicinity_plan,
    collect_reports,
    schedule_vicinity_plan,
)
from hierarchical_edge_sim.env.api import Env, ResizeAction, SpawnAction
from hierarchical_edge_sim.env.loans import add_loan, has_loan
from hierarchical_edge_sim.env.models import LoanTier


VALID_TRACE = "time_unit,requests\n" + "\n".join(f"{i},50" for i in range(1, 11)) + "\n"


def _ms(
    ms_id: str,
    *,
    containers: list[dict[str, Any]],
    cpu_max: float = 4.0,
    ram_max: float = 4096.0,
) -> dict[str, Any]:
    return {
        "id": ms_id,
        "cpu_min_cores": 0.5,
        "cpu_max_cores": cpu_max,
        "ram_min_mb": 256,
        "ram_max_mb": ram_max,
        "cpu_per_request_cores": 0.01,
        "ram_per_request_mb": 0.5,
        "trace_file": f"{ms_id}.csv",
        "containers": containers,
    }


def _write_env(tmp_path: Path, cfg: dict[str, Any], traces: list[str]) -> Env:
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    for name in traces:
        (tdir / f"{name}.csv").write_text(VALID_TRACE, encoding="utf-8")
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def _grow_world(tmp_path: Path) -> Env:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "coords": [0.0, 0.0],
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": 1.0, "ram_cap_mb": 2048}],
                },
                {
                    "id": "c2",
                    "coords": [1.0, 0.0],
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
            ],
            "vicinities": [{"id": "v1", "members": ["c1", "c2"], "leader": "c1"}],
        },
        "apps": [
            {
                "id": "demo_app",
                "microservices": [
                    _ms(
                        "api",
                        cpu_max=4.0,
                        containers=[
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 2048,
                            },
                            {
                                "id": "c-api-2",
                                "server_id": "c2-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                        ],
                    )
                ],
            }
        ],
    }
    env = _write_env(tmp_path, cfg, ["api"])
    add_loan(env.get_server("c2-w1"), borrower_cluster_id="c1", ms_id="api", tier=LoanTier.VICINITY, ts=0)
    return env


def _local_before_remote_world(tmp_path: Path) -> Env:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "coords": [0.0, 0.0],
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
                {
                    "id": "c2",
                    "coords": [1.0, 0.0],
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
            ],
            "vicinities": [{"id": "v1", "members": ["c1", "c2"], "leader": "c1"}],
        },
        "apps": [
            {
                "id": "demo_app",
                "microservices": [
                    _ms(
                        "api",
                        containers=[
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                            {
                                "id": "c-api-2",
                                "server_id": "c2-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                        ],
                    )
                ],
            }
        ],
    }
    env = _write_env(tmp_path, cfg, ["api"])
    add_loan(env.get_server("c2-w1"), borrower_cluster_id="c1", ms_id="api", tier=LoanTier.VICINITY, ts=0)
    return env


def _distance_world(tmp_path: Path) -> Env:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "coords": [0.0, 0.0],
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": 1.0, "ram_cap_mb": 2048}],
                },
                {
                    "id": "c3",
                    "coords": [10.0, 0.0],
                    "servers": [{"id": "c3-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
                {
                    "id": "c2",
                    "coords": [1.0, 0.0],
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 4.0, "ram_cap_mb": 2048}],
                },
            ],
            "vicinities": [{"id": "v1", "members": ["c1", "c3", "c2"], "leader": "c1"}],
        },
        "apps": [
            {
                "id": "demo_app",
                "microservices": [
                    _ms(
                        "api",
                        cpu_max=1.0,
                        ram_max=2048.0,
                        containers=[
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 2048,
                            }
                        ],
                    )
                ],
            }
        ],
    }
    return _write_env(tmp_path, cfg, ["api"])


def _recycle_world(tmp_path: Path) -> Env:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "coords": [0.0, 0.0],
                    "servers": [
                        {"id": "c1-w1", "cpu_cap_cores": 1.0, "ram_cap_mb": 2048},
                        {"id": "c1-w2", "cpu_cap_cores": 1.0, "ram_cap_mb": 2048},
                    ],
                },
                {
                    "id": "c2",
                    "coords": [1.0, 0.0],
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
            ],
            "vicinities": [{"id": "v1", "members": ["c1", "c2"], "leader": "c1"}],
        },
        "apps": [
            {
                "id": "demo_app",
                "microservices": [
                    _ms(
                        "api",
                        cpu_max=1.0,
                        ram_max=2048.0,
                        containers=[
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 2048,
                            }
                        ],
                    )
                ],
            },
            {
                "id": "media_app",
                "microservices": [
                    _ms(
                        "ingest",
                        cpu_max=1.0,
                        ram_max=2048.0,
                        containers=[
                            {
                                "id": "c-ingest-1",
                                "server_id": "c2-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                            {
                                "id": "c-ingest-2",
                                "server_id": "c1-w2",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 2048,
                            },
                        ],
                    )
                ],
            },
        ],
    }
    env = _write_env(tmp_path, cfg, ["api", "ingest"])
    add_loan(
        env.get_server("c1-w2"),
        borrower_cluster_id="c2",
        ms_id="ingest",
        tier=LoanTier.VICINITY,
        ts=0,
    )
    return env


def _rho(env: Env, ms_id: str = "api", cpu: float = 0.5, ram: float = 256.0) -> HelpRequest:
    spec = env.get_ms_spec(ms_id)
    return HelpRequest(
        seq=0,
        tau=1,
        ms_id=ms_id,
        home_cluster_id=env.get_app_owner_cluster_id(ms_id),
        remain_cpu=cpu,
        remain_ram=ram,
        cpu_min=spec.cpu_min_cores,
        ram_min=spec.ram_min_mb,
        min_mu_step=25.0,
        t_det=1,
    )


def test_grow_existing_before_spawn(tmp_path):
    env = _grow_world(tmp_path)
    reports = collect_reports(env, [_rho(env)], [], 1)
    plan = schedule_vicinity_plan(env, "v1", reports, pending=[], tau=1)
    grows = [e for e in plan.entries if e.act == "grow"]
    spawns = [e for e in plan.entries if e.act == "spawn"]
    assert len(grows) == 1
    assert grows[0].container_id == "c-api-2"
    assert grows[0].reason == "vicinity_up"
    assert grows[0].cpu_alloc_cores is not None and grows[0].cpu_alloc_cores > 0.5
    assert not spawns
    assert plan.unmet == []


def test_grow_local_hosts_before_remote_loans(tmp_path):
    env = _local_before_remote_world(tmp_path)
    members = env.list_vicinity_members("v1")
    free_cpu, free_ram = snapshot_free(env, members)
    actions, remain_cpu, remain_ram = grow_existing_instances(
        env,
        _rho(env),
        members=members,
        pending=[],
        free_cpu=free_cpu,
        free_ram=free_ram,
        tau=1,
    )
    assert len(actions) == 1
    assert actions[0].container_id == "c-api-1"
    assert actions[0].reason == "vicinity_up"
    assert remain_cpu <= 1e-9
    assert remain_ram <= 1e-9


def test_distance_beats_yaml_member_order_and_fatter_far_cluster(tmp_path):
    env = _distance_world(tmp_path)
    members = env.list_vicinity_members("v1")
    assert members == ["c1", "c3", "c2"]
    free_cpu, free_ram = snapshot_free(env, members)
    ranked = rank_placement_servers(env, members, "c1", "api", free_cpu, free_ram, [])
    remote = [sid for sid in ranked if env.get_server(sid).cluster_id != "c1"]
    assert remote[0] == "c2-w1"
    reports = collect_reports(env, [_rho(env)], [], 1)
    plan = schedule_vicinity_plan(env, "v1", reports, pending=[], tau=1)
    spawns = [e for e in plan.entries if e.act == "spawn"]
    assert len(spawns) == 1
    assert spawns[0].server_id == "c2-w1"
    assert spawns[0].reason == "vicinity_spawn"
    assert spawns[0].loan_tier == "vicinity"


def test_home_recycle_after_phase1_release(tmp_path):
    env = _recycle_world(tmp_path)
    assert env.get_app_owner_cluster_id("api") == "c1"
    assert env.get_app_owner_cluster_id("ingest") == "c2"
    reports = collect_reports(
        env,
        [_rho(env, "api")],
        [
            ReleaseIntent(
                seq=0,
                tau=1,
                ms_id="ingest",
                home_cluster_id="c2",
                remain_cpu=1.0,
                remain_ram=2048.0,
                t_det=1,
            )
        ],
        1,
    )
    plan = schedule_vicinity_plan(env, "v1", reports, pending=[], tau=1)
    terms = [e for e in plan.entries if e.act == "terminate"]
    spawns = [e for e in plan.entries if e.act == "spawn"]
    assert any(e.container_id == "c-ingest-2" for e in terms)
    assert len(spawns) == 1
    assert spawns[0].server_id == "c1-w2"
    assert spawns[0].ms_id == "api"
    assert spawns[0].reason == "horizontal_spawn"
    assert spawns[0].loan_tier == ""
    actions, unmet = apply_vicinity_plan(env, plan)
    assert unmet == []
    results = env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert all(r.ok for r in results)
    assert "c-ingest-2" not in env.world.containers
    assert not has_loan(env.get_server("c1-w2"), "c2", "ingest")
    api_servers = {env.get_container(cid).server_id for cid in env.get_microservice("api").container_ids}
    assert "c1-w2" in api_servers
    assert not has_loan(env.get_server("c1-w2"), "c1", "api")
    assert not any(isinstance(a, ResizeAction) and a.reason == "vicinity_up" for a in actions)
    assert any(isinstance(a, SpawnAction) and a.server_id == "c1-w2" for a in actions)
