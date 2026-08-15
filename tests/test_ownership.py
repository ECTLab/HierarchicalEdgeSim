"""S3: app owner stamp, loan registry, RequestWorkerOwnerScale."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.env.api import (
    Env,
    ResizeAction,
    ResizeResultCode,
    SpawnAction,
    SpawnResultCode,
    TerminateAction,
    TerminateResultCode,
)
from hierarchical_edge_sim.env.loans import add_loan, drop_loan, get_loan, has_loan
from hierarchical_edge_sim.env.models import LoanTier


VALID_TRACE = "time_unit,requests\n1,10\n2,10\n3,10\n4,10\n5,10\n"


def _write_two_cluster(tmp_path: Path) -> Path:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 8192}],
                },
                {
                    "id": "c2",
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 8192}],
                },
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
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    (tdir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")
    path = tmp_path / "two.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_app_owner_inferred_from_first_replica(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    assert env.get_app("demo_app").owner_cluster_id == "c1"
    assert env.get_app_owner_cluster_id("api") == "c1"


def test_loan_registry_round_trip(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    server = env.get_server("c1-w2")
    assert server.loans == []
    rec = add_loan(
        server,
        borrower_cluster_id="cX",
        ms_id="api",
        tier=LoanTier.VICINITY,
        ts=3,
    )
    assert rec.borrower_cluster_id == "cX"
    assert rec.tier == LoanTier.VICINITY
    assert rec.ts == 3
    assert has_loan(server, "cX", "api")
    assert get_loan(server, "cX", "api") == rec
    assert add_loan(server, borrower_cluster_id="cX", ms_id="api", tier=LoanTier.GLOBAL, ts=9) is rec
    assert drop_loan(server, "cX", "api")
    assert not has_loan(server, "cX", "api")
    assert not drop_loan(server, "cX", "api")


def test_owner_can_mutate_own_servers(tmp_path):
    env = Env.from_config(_write_two_cluster(tmp_path))
    resized = env.request_worker_owner_scale(
        actor_cluster_id="c1",
        act="resize",
        container_id="c-api-1",
        cpu_alloc_cores=1.5,
    )
    assert resized.ok
    spawned = env.request_worker_owner_scale(
        actor_cluster_id="c1",
        act="spawn",
        ms_id="api",
        server_id="c1-w1",
        container_id="c-api-2",
    )
    assert spawned.ok
    terminated = env.request_worker_owner_scale(
        actor_cluster_id="c1",
        act="terminate",
        container_id="c-api-2",
        ms_id="api",
    )
    assert terminated.ok
    assert "c-api-2" not in env.world.containers


def test_non_owner_without_loan_rejected(tmp_path):
    env = Env.from_config(_write_two_cluster(tmp_path))
    spawn = env.request_worker_owner_scale(
        actor_cluster_id="c1",
        act="spawn",
        ms_id="api",
        server_id="c2-w1",
        container_id="c-borrowed",
    )
    assert not spawn.ok
    assert spawn.code == SpawnResultCode.NOT_AUTHORIZED
    assert "c-borrowed" not in env.world.containers

    # Worker-owner c2 may mutate its own node even if the app lives on c1.
    as_owner = env.request_worker_owner_scale(
        actor_cluster_id="c2",
        act="spawn",
        ms_id="api",
        server_id="c2-w1",
        container_id="c-local-c2",
    )
    assert as_owner.ok


def test_borrower_with_loan_can_mutate(tmp_path):
    env = Env.from_config(_write_two_cluster(tmp_path))
    add_loan(
        env.get_server("c2-w1"),
        borrower_cluster_id="c1",
        ms_id="api",
        tier=LoanTier.VICINITY,
        ts=1,
    )
    spawned = env.request_worker_owner_scale(
        actor_cluster_id="c1",
        act="spawn",
        ms_id="api",
        server_id="c2-w1",
        container_id="c-borrowed",
        cpu_alloc_cores=0.5,
        ram_alloc_mb=256.0,
    )
    assert spawned.ok
    resized = env.request_worker_owner_scale(
        actor_cluster_id="c1",
        act="resize",
        container_id="c-borrowed",
        cpu_alloc_cores=1.0,
    )
    assert resized.ok
    # Keep a local replica so terminate is not LAST_REPLICA.
    gone = env.request_worker_owner_scale(
        actor_cluster_id="c1",
        act="terminate",
        container_id="c-borrowed",
        ms_id="api",
    )
    assert gone.ok
    assert not has_loan(env.get_server("c2-w1"), "c1", "api")


def test_apply_actions_infers_app_owner_and_rejects_foreign(tmp_path):
    env = Env.from_config(_write_two_cluster(tmp_path))
    local = env.apply_actions(
        [
            SpawnAction(
                type="spawn",
                ms_id="api",
                server_id="c1-w1",
                container_id="c-local-2",
                cpu_alloc_cores=0.5,
                ram_alloc_mb=256.0,
            )
        ],
        tau=1,
    )
    assert local[0].ok
    foreign = env.apply_actions(
        [
            SpawnAction(
                type="spawn",
                ms_id="api",
                server_id="c2-w1",
                container_id="c-foreign",
                cpu_alloc_cores=0.5,
                ram_alloc_mb=256.0,
            )
        ],
        tau=1,
    )
    assert foreign[0].code == SpawnResultCode.NOT_AUTHORIZED
    # Explicit actor can be the worker owner.
    as_c2 = env.apply_actions(
        [
            ResizeAction(
                type="resize",
                ms_id="api",
                container_id="c-api-1",
                cpu_alloc_cores=1.2,
                actor_cluster_id="c2",
            )
        ],
        tau=1,
    )
    assert as_c2[0].code == ResizeResultCode.NOT_AUTHORIZED


def test_apply_actions_terminate_uses_owner_path(tmp_path):
    env = Env.from_config(_write_two_cluster(tmp_path))
    env.spawn(ms_id="api", server_id="c1-w1", container_id="c-extra", cpu_alloc_cores=0.5, ram_alloc_mb=256.0)
    results = env.apply_actions(
        [TerminateAction(type="terminate", ms_id="api", container_id="c-extra")],
        tau=1,
    )
    assert results[0].ok
    assert results[0].code == TerminateResultCode.OK
