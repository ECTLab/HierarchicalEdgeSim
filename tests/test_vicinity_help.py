"""S4: VicinityLeaderSchedule lite — leftover after local BEH goes to neighbors."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.autoscaler.reactive_local.policy import build
from hierarchical_edge_sim.env.api import (
    Env,
    NeedVicinityHelpAction,
    SpawnAction,
    SpawnResultCode,
)
from hierarchical_edge_sim.env.loans import add_loan, has_loan
from hierarchical_edge_sim.env.models import ContainerTickRecord, LoanTier


VALID_TRACE = "time_unit,requests\n" + "\n".join(f"{i},50" for i in range(1, 11)) + "\n"


def _ms_block(
    ms_id: str,
    *,
    server_id: str,
    container_id: str,
    cpu_alloc: float,
    ram_alloc: float,
    cpu_max: float,
    ram_max: float,
    extra_containers: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    containers = [
        {
            "id": container_id,
            "server_id": server_id,
            "cpu_alloc_cores": cpu_alloc,
            "ram_alloc_mb": ram_alloc,
        }
    ]
    if extra_containers:
        containers.extend(extra_containers)
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


def _write_vicinity_world(
    tmp_path: Path,
    *,
    c1_cpu: float = 1.0,
    c1_ram: float = 2048.0,
    c2_cpu: float = 8.0,
    c2_ram: float = 4096.0,
    two_ms: bool = False,
    borrowed_replica: bool = False,
    vicinities: bool = True,
) -> Env:
    c1_servers = [{"id": "c1-w1", "cpu_cap_cores": c1_cpu, "ram_cap_mb": c1_ram}]
    if two_ms:
        c1_servers.append({"id": "c1-w2", "cpu_cap_cores": c1_cpu, "ram_cap_mb": c1_ram})
    topology: dict[str, Any] = {
        "clusters": [
            {"id": "c1", "servers": c1_servers},
            {
                "id": "c2",
                "servers": [{"id": "c2-w1", "cpu_cap_cores": c2_cpu, "ram_cap_mb": c2_ram}],
            },
        ]
    }
    if vicinities:
        topology["vicinities"] = [{"id": "v1", "members": ["c1", "c2"], "leader": "c1"}]

    extra_home: list[dict[str, Any]] | None = None
    if borrowed_replica:
        extra_home = [
            {
                "id": "c-api-2",
                "server_id": "c2-w1",
                "cpu_alloc_cores": 0.5,
                "ram_alloc_mb": 256,
            }
        ]
    apps = [
        {
            "id": "demo_app",
            "microservices": [
                _ms_block(
                    "api",
                    server_id="c1-w1",
                    container_id="c-api-1",
                    cpu_alloc=1.0 if not borrowed_replica else 0.5,
                    ram_alloc=2048.0 if not borrowed_replica else 256.0,
                    cpu_max=1.0 if not borrowed_replica else 4.0,
                    ram_max=2048.0 if not borrowed_replica else 4096.0,
                    extra_containers=extra_home,
                )
            ],
        }
    ]
    if two_ms:
        apps.append(
            {
                "id": "media_app",
                "microservices": [
                    _ms_block(
                        "ingest",
                        server_id="c1-w2",
                        container_id="c-ingest-1",
                        cpu_alloc=1.0,
                        ram_alloc=2048.0,
                        cpu_max=1.0,
                        ram_max=2048.0,
                    )
                ],
            }
        )

    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": topology,
        "apps": apps,
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    (tdir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")
    if two_ms:
        (tdir / "ingest.csv").write_text(VALID_TRACE, encoding="utf-8")
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def _push_drops(env: Env, tau: int, ms_id: str = "api", *, drop: float = 40.0) -> None:
    for cid in env.get_microservice(ms_id).container_ids:
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


def _push_slack(env: Env, tau: int, ms_id: str = "api") -> None:
    for cid in env.get_microservice(ms_id).container_ids:
        c = env.get_container(cid)
        c.append_history(
            ContainerTickRecord(
                tau=tau,
                lambda_in=1.0,
                lambda_served=1.0,
                lambda_dropped=0.0,
                cpu_usage_cores=c.cpu_alloc_cores * 0.1,
                ram_usage_mb=c.ram_alloc_mb * 0.1,
                cpu_alloc_cores=c.cpu_alloc_cores,
                ram_alloc_mb=c.ram_alloc_mb,
                q_cpu=0.1,
                q_ram=0.1,
            )
        )
    env.state.current_tau = tau


def _up_scaler():
    return build(
        {"x_up_streak": 1, "y_down_streak": 99, "cooldown_ticks": 0, "sustained_up_streak": 99}
    )


def test_home_saturated_spawns_on_neighbor_with_vicinity_loan(tmp_path):
    env = _write_vicinity_world(tmp_path)
    scaler = _up_scaler()
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert len(spawns) == 1
    spawn = spawns[0]
    assert spawn.server_id == "c2-w1"
    assert spawn.reason == "vicinity_spawn"
    assert spawn.loan_tier == "vicinity"
    assert spawn.actor_cluster_id == "c1"
    assert spawn.cpu_alloc_cores == 0.5
    assert not any(isinstance(a, NeedVicinityHelpAction) for a in actions)

    results = env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert results[0].ok
    assert has_loan(env.get_server("c2-w1"), "c1", "api")
    loan = env.get_server("c2-w1").loans[0]
    assert loan.tier == LoanTier.VICINITY
    assert env.get_container(results[0].container_id).server_id == "c2-w1"


def test_fcfs_one_neighbor_slot_second_ms_still_needs_help(tmp_path):
    env = _write_vicinity_world(tmp_path, two_ms=True, c2_cpu=0.5, c2_ram=256.0)
    scaler = _up_scaler()
    _push_drops(env, 1, "api")
    _push_drops(env, 1, "ingest")
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    helps = [a for a in actions if isinstance(a, NeedVicinityHelpAction)]
    assert len(spawns) == 1
    assert spawns[0].ms_id == "api"
    assert spawns[0].server_id == "c2-w1"
    assert len(helps) == 1
    assert helps[0].ms_id == "ingest"
    env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert has_loan(env.get_server("c2-w1"), "c1", "api")
    assert not has_loan(env.get_server("c2-w1"), "c1", "ingest")


def test_vicinity_full_logs_need_vicinity_help(tmp_path):
    env = _write_vicinity_world(tmp_path, c2_cpu=0.4, c2_ram=256.0)
    scaler = _up_scaler()
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)
    helps = [a for a in actions if isinstance(a, NeedVicinityHelpAction)]
    assert len(helps) == 1
    assert helps[0].cluster_id == "c1"
    env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert any(
        row.action_type == "need_vicinity_help" and row.result_code == "LOGGED"
        for row in env.action_log
    )
    assert env.get_server("c2-w1").loans == []


def test_scale_down_prefers_borrowed_replica(tmp_path):
    env = _write_vicinity_world(tmp_path, borrowed_replica=True, c1_cpu=8.0, c1_ram=4096.0)
    add_loan(
        env.get_server("c2-w1"),
        borrower_cluster_id="c1",
        ms_id="api",
        tier=LoanTier.VICINITY,
        ts=0,
    )
    scaler = build(
        {
            "x_up_streak": 99,
            "y_down_streak": 1,
            "cooldown_ticks": 0,
            "theta_free": 0.35,
            "sustained_up_streak": 99,
        }
    )
    _push_slack(env, 1)
    actions = scaler.on_tick_end(env, 1)
    terms = [a for a in actions if getattr(a, "type", "") == "terminate"]
    assert len(terms) == 1
    assert terms[0].container_id == "c-api-2"
    results = env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert results[0].ok
    assert not has_loan(env.get_server("c2-w1"), "c1", "api")
    assert "c-api-1" in env.get_microservice("api").container_ids
    assert "c-api-2" not in env.world.containers


def test_loan_grant_rolls_back_when_spawn_fails(tmp_path):
    env = _write_vicinity_world(tmp_path, c2_cpu=0.1, c2_ram=256.0)
    result = env.request_worker_owner_scale(
        actor_cluster_id="c1",
        act="spawn",
        ms_id="api",
        server_id="c2-w1",
        cpu_alloc_cores=0.5,
        ram_alloc_mb=256.0,
        loan_tier="vicinity",
        tau=1,
    )
    assert not result.ok
    assert result.code == SpawnResultCode.SERVER_CPU_EXCEEDED
    assert not has_loan(env.get_server("c2-w1"), "c1", "api")


def test_apply_actions_grants_loan_from_spawn_action(tmp_path):
    env = _write_vicinity_world(tmp_path)
    action = SpawnAction(
        type="spawn",
        ms_id="api",
        server_id="c2-w1",
        cpu_alloc_cores=0.5,
        ram_alloc_mb=256.0,
        reason="vicinity_spawn",
        tau=1,
        actor_cluster_id="c1",
        loan_tier="vicinity",
    )
    results = env.apply_actions([action], tau=1, autoscaler_name="scripted")
    assert results[0].ok
    assert has_loan(env.get_server("c2-w1"), "c1", "api")
