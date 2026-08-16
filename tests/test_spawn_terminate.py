"""S1: Env.spawn / Env.terminate and apply_actions dispatch."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
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


VALID_TRACE = "time_unit,requests\n1,100\n2,100\n3,100\n4,100\n5,100\n"


def _write_two_server_config(tmp_path: Path) -> Path:
    """One MS with one container on c1-w1; free sibling server c1-w2."""
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 42},
        "traces_dir": str(tmp_path / "traces" / "demo"),
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [
                        {"id": "c1-w1", "cpu_cap_cores": 2.0, "ram_cap_mb": 2048},
                        {"id": "c1-w2", "cpu_cap_cores": 8.0, "ram_cap_mb": 8192},
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
                        "cpu_max_cores": 2.0,
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
                                "ram_alloc_mb": 512,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    trace_dir = tmp_path / "traces" / "demo"
    trace_dir.mkdir(parents=True)
    (trace_dir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")
    path = tmp_path / "two_servers.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


def test_spawn_defaults_to_ms_minima(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    free_before = env.get_server_free("c1-w2")
    result = env.spawn(ms_id="api", server_id="c1-w2")
    assert result.ok
    assert result.code == SpawnResultCode.OK
    assert result.cpu_alloc_cores == 0.5
    assert result.ram_alloc_mb == 256.0
    assert result.container_id in env.world.containers
    assert result.container_id in env.get_microservice("api").container_ids
    assert result.container_id in env.get_server("c1-w2").container_ids
    free_after = env.get_server_free("c1-w2")
    assert free_after[0] == free_before[0] - 0.5
    assert free_after[1] == free_before[1] - 256.0


def test_spawn_rejects_below_min_and_server_full(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    below = env.spawn(ms_id="api", server_id="c1-w2", cpu_alloc_cores=0.1, ram_alloc_mb=256.0)
    assert not below.ok
    assert below.code == SpawnResultCode.BELOW_MS_MIN

    env.world.servers["c1-w2"].cpu_cap_cores = 0.4
    packed = env.spawn(ms_id="api", server_id="c1-w2", cpu_alloc_cores=0.5, ram_alloc_mb=256.0)
    assert not packed.ok
    assert packed.code == SpawnResultCode.SERVER_CPU_EXCEEDED


def test_spawn_rejects_duplicate_id(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    result = env.spawn(
        ms_id="api",
        server_id="c1-w2",
        container_id="c-api-1",
        cpu_alloc_cores=0.5,
        ram_alloc_mb=256.0,
    )
    assert not result.ok
    assert result.code == SpawnResultCode.DUPLICATE_CONTAINER_ID


def test_spawn_affects_routing_next_tick(tiny_config_path, tmp_path):
    env = Env.from_config(tiny_config_path)
    env.world_spec = replace(
        env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / "results"))
    )
    # Equal headroom → equal share after spawn at same alloc as existing:
    # existing c-api-1 has alloc 1.0 (headroom 0.5); spawn at 1.0 on w2 (headroom 0.5).
    spawned = env.spawn(
        ms_id="api",
        server_id="c1-w2",
        cpu_alloc_cores=1.0,
        ram_alloc_mb=512.0,
        container_id="c-api-2",
    )
    assert spawned.ok
    # api.csv: τ=1 is 0 requests; τ=2 has 25 — assert routing on the first non-zero tick.
    env.run(max_ticks=2, now_utc=datetime(2026, 1, 1, tzinfo=UTC))
    h1 = env.get_container("c-api-1").history_at(2)
    h2 = env.get_container("c-api-2").history_at(2)
    assert h1.lambda_in > 0
    assert h2.lambda_in > 0
    assert abs(h1.lambda_in - h2.lambda_in) < 1e-9


def test_terminate_last_replica_rejected(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    result = env.terminate("c-api-1")
    assert not result.ok
    assert result.code == TerminateResultCode.LAST_REPLICA
    assert "c-api-1" in env.world.containers


def test_terminate_frees_capacity_for_respawn(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    env.spawn(
        ms_id="api",
        server_id="c1-w2",
        cpu_alloc_cores=0.5,
        ram_alloc_mb=256.0,
        container_id="c-api-2",
    )
    # Fill w2 so another spawn would fail, then terminate and respawn.
    env.world.servers["c1-w2"].cpu_cap_cores = 0.5
    blocked = env.spawn(ms_id="api", server_id="c1-w2", container_id="c-api-3")
    assert blocked.code == SpawnResultCode.SERVER_CPU_EXCEEDED

    gone = env.terminate("c-api-2")
    assert gone.ok
    assert gone.code == TerminateResultCode.OK
    assert "c-api-2" not in env.world.containers
    assert "c-api-2" not in env.get_microservice("api").container_ids

    again = env.spawn(ms_id="api", server_id="c1-w2", container_id="c-api-3")
    assert again.ok
    assert again.container_id == "c-api-3"


def test_auto_allocated_ids_are_not_reused_after_terminate(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    first = env.spawn(ms_id="api", server_id="c1-w2")
    assert first.ok
    gone = env.terminate(first.container_id)
    assert gone.ok
    second = env.spawn(ms_id="api", server_id="c1-w2")
    assert second.ok
    assert second.container_id != first.container_id
    assert first.container_id not in env.world.containers
    assert second.container_id in env.world.containers


def test_apply_actions_order_terminate_resize_spawn(tmp_path):
    env = Env.from_config(_write_two_server_config(tmp_path))
    # Start with two replicas so terminate is legal.
    env.spawn(
        ms_id="api",
        server_id="c1-w2",
        cpu_alloc_cores=0.5,
        ram_alloc_mb=256.0,
        container_id="c-api-2",
    )
    actions = [
        SpawnAction(
            type="spawn",
            ms_id="api",
            server_id="c1-w2",
            container_id="c-api-3",
            cpu_alloc_cores=0.5,
            ram_alloc_mb=256.0,
            reason="out",
        ),
        ResizeAction(
            type="resize",
            ms_id="api",
            container_id="c-api-1",
            cpu_alloc_cores=1.5,
            reason="up",
        ),
        TerminateAction(type="terminate", ms_id="api", container_id="c-api-2", reason="in"),
    ]
    results = env.apply_actions(actions, tau=1, autoscaler_name="scripted")
    assert [type(r).__name__ for r in results] == [
        "TerminateResult",
        "ResizeResult",
        "SpawnResult",
    ]
    assert results[0].ok and results[0].code == TerminateResultCode.OK
    assert results[1].ok and results[1].code == ResizeResultCode.OK
    assert results[2].ok and results[2].code == SpawnResultCode.OK
    assert env.get_container("c-api-1").cpu_alloc_cores == 1.5
    assert "c-api-2" not in env.world.containers
    assert "c-api-3" in env.world.containers
    assert [row.action_type for row in env.action_log] == ["terminate", "resize", "spawn"]


def test_apply_actions_spawn_duplicate_id_in_batch(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    actions = [
        SpawnAction(
            type="spawn",
            ms_id="api",
            server_id="c1-w2",
            container_id="c-new",
            cpu_alloc_cores=0.5,
            ram_alloc_mb=256.0,
        ),
        SpawnAction(
            type="spawn",
            ms_id="api",
            server_id="c1-w2",
            container_id="c-new",
            cpu_alloc_cores=0.5,
            ram_alloc_mb=256.0,
        ),
    ]
    results = env.apply_actions(actions, tau=1)
    assert results[0].ok
    assert results[1].code == SpawnResultCode.DUPLICATE_IN_BATCH
