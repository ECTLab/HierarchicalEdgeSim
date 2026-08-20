"""S6: scale-down reclaim order and CheckCascadingMigration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.autoscaler.reactive_local.cascade import check_cascading_migration
from hierarchical_edge_sim.autoscaler.reactive_local.params import validate_params
from hierarchical_edge_sim.autoscaler.reactive_local.policy import build
from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.loans import add_loan, has_loan
from hierarchical_edge_sim.env.models import ContainerTickRecord, LoanTier


VALID_TRACE = "time_unit,requests\n" + "\n".join(f"{i},50" for i in range(1, 11)) + "\n"


def _ms(
    *,
    cpu_max: float,
    ram_max: float,
    containers: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "id": "api",
        "cpu_min_cores": 0.5,
        "cpu_max_cores": cpu_max,
        "ram_min_mb": 256,
        "ram_max_mb": ram_max,
        "cpu_per_request_cores": 0.01,
        "ram_per_request_mb": 0.5,
        "trace_file": "api.csv",
        "containers": containers,
    }


def _write_three_replica_world(
    tmp_path: Path,
    *,
    local_cpu: float = 0.5,
    local_ram: float = 256.0,
    c1_cpu: float = 16.0,
    c1_ram: float = 8192.0,
) -> Env:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": c1_cpu, "ram_cap_mb": c1_ram}],
                },
                {
                    "id": "c2",
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
                {
                    "id": "c3",
                    "servers": [{"id": "c3-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
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
                    _ms(
                        cpu_max=8.0,
                        ram_max=4096.0,
                        containers=[
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": local_cpu,
                                "ram_alloc_mb": local_ram,
                            },
                            {
                                "id": "c-api-2",
                                "server_id": "c2-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                            {
                                "id": "c-api-3",
                                "server_id": "c3-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                        ],
                    )
                ],
            }
        ],
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    (tdir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    env = Env.from_config(path)
    add_loan(
        env.get_server("c2-w1"),
        borrower_cluster_id="c1",
        ms_id="api",
        tier=LoanTier.VICINITY,
        ts=1,
    )
    add_loan(
        env.get_server("c3-w1"),
        borrower_cluster_id="c1",
        ms_id="api",
        tier=LoanTier.GLOBAL,
        ts=1,
    )
    return env


def _push_slack(env: Env, tau: int) -> None:
    for cid in env.get_microservice("api").container_ids:
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


def _down_scaler(**extra):
    params = {
        "x_up_streak": 99,
        "y_down_streak": 1,
        "cooldown_ticks": 0,
        "theta_free": 0.35,
        "sustained_up_streak": 99,
        "cascade_home": False,
    }
    params.update(extra)
    return build(params)


def test_cascade_home_param_default():
    assert validate_params({}).cascade_home is True
    assert validate_params({"cascade_home": False}).cascade_home is False


def test_down_terminates_global_before_vicinity_before_local(tmp_path):
    env = _write_three_replica_world(tmp_path)
    assert env.get_app_owner_cluster_id("api") == "c1"
    scaler = _down_scaler()
    _push_slack(env, 1)
    actions = scaler.on_tick_end(env, 1)
    terms = [a for a in actions if getattr(a, "type", "") == "terminate"]
    assert [a.container_id for a in terms] == ["c-api-3"]
    assert terms[0].reason == "beg_terminate"
    results = env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert results[0].ok
    assert not has_loan(env.get_server("c3-w1"), "c1", "api")
    assert has_loan(env.get_server("c2-w1"), "c1", "api")
    assert "c-api-1" in env.get_microservice("api").container_ids
    assert "c-api-2" in env.world.containers
    assert "c-api-3" not in env.world.containers


def test_cascade_pulls_global_home_when_local_minima_freed(tmp_path):
    env = _write_three_replica_world(tmp_path, local_cpu=4.0, local_ram=2048.0)
    spec = env.get_ms_spec("api")
    actions = check_cascading_migration(
        env,
        ms_id="api",
        owner_cluster_id="c1",
        spec=spec,
        freed_cpu=0.5,
        freed_ram=256.0,
        pending=[],
        tau=1,
    )
    terms = [a for a in actions if getattr(a, "type", "") == "terminate"]
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert [a.container_id for a in terms] == ["c-api-3"]
    assert terms[0].reason == "cascade_terminate"
    assert len(spawns) == 1
    assert spawns[0].reason == "cascade_spawn"
    assert spawns[0].server_id == "c1-w1"
    assert spawns[0].cpu_alloc_cores == 0.5
    results = env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert all(getattr(r, "ok", False) for r in results)
    assert "c-api-3" not in env.world.containers
    assert not has_loan(env.get_server("c3-w1"), "c1", "api")
    assert has_loan(env.get_server("c2-w1"), "c1", "api")
    home_ids = [
        cid
        for cid in env.get_microservice("api").container_ids
        if env.get_container(cid).server_id == "c1-w1"
    ]
    assert len(home_ids) == 2


def test_cascade_home_flag_off_does_not_migrate(tmp_path):
    env = _write_three_replica_world(tmp_path, local_cpu=4.0, local_ram=2048.0)
    scaler = _down_scaler(cascade_home=False, alpha_down=0.5)
    _push_slack(env, 1)
    actions = scaler.on_tick_end(env, 1)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)
    assert not any(getattr(a, "reason", "") == "cascade_terminate" for a in actions)
