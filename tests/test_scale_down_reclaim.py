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
                    "coords": [0.0, 0.0],
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": c1_cpu, "ram_cap_mb": c1_ram}],
                },
                {
                    "id": "c2",
                    "coords": [1.0, 0.0],
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
                {
                    "id": "c3",
                    "coords": [10.0, 0.0],
                    "servers": [{"id": "c3-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
            ],
            "vicinities": [
                {"id": "v1", "members": ["c1", "c2", "c3"], "leader": "c1"},
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
        ts=10,
    )
    add_loan(
        env.get_server("c3-w1"),
        borrower_cluster_id="c1",
        ms_id="api",
        tier=LoanTier.VICINITY,
        ts=1,
    )
    return env


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


def _push_busy(env: Env, tau: int, ms_id: str) -> None:
    for cid in env.get_microservice(ms_id).container_ids:
        c = env.get_container(cid)
        c.append_history(
            ContainerTickRecord(
                tau=tau,
                lambda_in=80.0,
                lambda_served=80.0,
                lambda_dropped=0.0,
                cpu_usage_cores=c.cpu_alloc_cores,
                ram_usage_mb=c.ram_alloc_mb,
                cpu_alloc_cores=c.cpu_alloc_cores,
                ram_alloc_mb=c.ram_alloc_mb,
                q_cpu=1.0,
                q_ram=1.0,
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


def test_down_releases_farthest_borrowed_before_local(tmp_path):
    env = _write_three_replica_world(tmp_path)
    assert env.get_app_owner_cluster_id("api") == "c1"
    assert env.distance("c1", "c3") > env.distance("c1", "c2")
    scaler = _down_scaler()
    _push_slack(env, 1)
    actions = scaler.on_tick_end(env, 1)
    terms = [a for a in actions if getattr(a, "type", "") == "terminate"]
    assert [a.container_id for a in terms] == ["c-api-3", "c-api-2"]
    assert {a.reason for a in terms} == {"vicinity_terminate"}
    local_terms = [a for a in terms if a.reason == "horizontal_terminate"]
    assert local_terms == []
    results = env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert all(r.ok for r in results)
    assert not has_loan(env.get_server("c3-w1"), "c1", "api")
    assert not has_loan(env.get_server("c2-w1"), "c1", "api")
    assert "c-api-1" in env.get_microservice("api").container_ids
    assert "c-api-2" not in env.world.containers
    assert "c-api-3" not in env.world.containers


def _write_cross_ms_world(tmp_path: Path) -> Env:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "coords": [0.0, 0.0],
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": 16.0, "ram_cap_mb": 8192}],
                },
                {
                    "id": "c3",
                    "coords": [10.0, 0.0],
                    "servers": [{"id": "c3-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
                },
            ],
            "vicinities": [{"id": "v1", "members": ["c1", "c3"], "leader": "c1"}],
        },
        "apps": [
            {
                "id": "demo_app",
                "microservices": [
                    {
                        "id": "api",
                        "cpu_min_cores": 0.5,
                        "cpu_max_cores": 8.0,
                        "ram_min_mb": 256,
                        "ram_max_mb": 4096,
                        "cpu_per_request_cores": 0.01,
                        "ram_per_request_mb": 0.5,
                        "trace_file": "api.csv",
                        "containers": [
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                            {
                                "id": "c-api-2",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                        ],
                    }
                ],
            },
            {
                "id": "media_app",
                "microservices": [
                    {
                        "id": "ingest",
                        "cpu_min_cores": 0.5,
                        "cpu_max_cores": 8.0,
                        "ram_min_mb": 256,
                        "ram_max_mb": 4096,
                        "cpu_per_request_cores": 0.01,
                        "ram_per_request_mb": 0.5,
                        "trace_file": "ingest.csv",
                        "containers": [
                            {
                                "id": "c-ingest-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                            {
                                "id": "c-ingest-2",
                                "server_id": "c3-w1",
                                "cpu_alloc_cores": 0.5,
                                "ram_alloc_mb": 256,
                            },
                        ],
                    }
                ],
            },
        ],
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")
    (tdir / "ingest.csv").write_text(VALID_TRACE, encoding="utf-8")
    path = tmp_path / "cross.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    env = Env.from_config(path)
    add_loan(
        env.get_server("c3-w1"),
        borrower_cluster_id="c1",
        ms_id="ingest",
        tier=LoanTier.VICINITY,
        ts=1,
    )
    return env


def test_cascade_pulls_other_ms_home_via_evict(tmp_path):
    env = _write_cross_ms_world(tmp_path)
    assert env.get_app_owner_cluster_id("api") == "c1"
    assert env.get_app_owner_cluster_id("ingest") == "c1"
    spawns, evict = check_cascading_migration(
        env,
        shrinking_ms_id="api",
        owner_cluster_id="c1",
        freed_cpu=0.5,
        freed_ram=256.0,
        pending=[],
        tau=1,
    )
    assert evict is not None
    assert evict.kind == "evict"
    assert evict.ms_id == "ingest"
    assert evict.evict_container_id == "c-ingest-2"
    assert len(spawns) == 1
    assert spawns[0].ms_id == "ingest"
    assert spawns[0].server_id == "c1-w1"
    assert spawns[0].reason == "cascade_spawn"
    assert spawns[0].cpu_alloc_cores is not None and spawns[0].cpu_alloc_cores > 0.5


def test_cascade_skips_ms_already_in_release_queue(tmp_path):
    env = _write_cross_ms_world(tmp_path)
    from hierarchical_edge_sim.autoscaler.reactive_local.help import ReleaseIntent

    queued = [
        ReleaseIntent(
            seq=0,
            tau=1,
            ms_id="ingest",
            home_cluster_id="c1",
            remain_cpu=0.5,
            remain_ram=256.0,
            t_det=1,
        )
    ]
    spawns, evict = check_cascading_migration(
        env,
        shrinking_ms_id="api",
        owner_cluster_id="c1",
        freed_cpu=0.5,
        freed_ram=256.0,
        pending=[],
        tau=1,
        queued_releases=queued,
    )
    assert spawns == []
    assert evict is None


def test_cascade_never_pulls_the_shrinking_ms(tmp_path):
    env = _write_three_replica_world(tmp_path, local_cpu=4.0, local_ram=2048.0)
    spawns, evict = check_cascading_migration(
        env,
        shrinking_ms_id="api",
        owner_cluster_id="c1",
        freed_cpu=0.5,
        freed_ram=256.0,
        pending=[],
        tau=1,
    )
    assert spawns == []
    assert evict is None


def test_end_to_end_api_down_evicts_ingest_loan(tmp_path):
    env = _write_cross_ms_world(tmp_path)
    scaler = _down_scaler(cascade_home=True)
    _push_slack(env, 1, ms_id="api")
    _push_busy(env, 1, ms_id="ingest")
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "reason", "") == "cascade_spawn"]
    terms = [a for a in actions if getattr(a, "reason", "") == "cascade_terminate"]
    assert len(spawns) == 1
    assert spawns[0].ms_id == "ingest"
    assert len(terms) == 1
    assert terms[0].container_id == "c-ingest-2"
    results = env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert all(getattr(r, "ok", False) for r in results)
    assert "c-ingest-2" not in env.world.containers
    assert not has_loan(env.get_server("c3-w1"), "c1", "ingest")
    home_ingest = [
        cid
        for cid in env.get_microservice("ingest").container_ids
        if env.get_container(cid).server_id == "c1-w1"
    ]
    assert len(home_ingest) == 2


def test_cascade_home_flag_off_does_not_migrate(tmp_path):
    env = _write_three_replica_world(tmp_path, local_cpu=4.0, local_ram=2048.0)
    scaler = _down_scaler(cascade_home=False)
    _push_slack(env, 1)
    actions = scaler.on_tick_end(env, 1)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)
    assert not any(getattr(a, "reason", "") == "cascade_terminate" for a in actions)
