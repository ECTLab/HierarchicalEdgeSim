"""Tests for apply_actions and after-tick hook (Step 2)."""

from __future__ import annotations

import csv
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.env.api import Env, ResizeAction, ResizeResultCode
from hierarchical_edge_sim.env.config import load_yaml
from hierarchical_edge_sim.env.validate import validate_or_raise
from hierarchical_edge_sim.env.world import build_world


VALID_TRACE = "time_unit,requests\n1,10\n2,10\n3,10\n4,10\n5,10\n"


def _write_shared_server_config(tmp_path: Path) -> Path:
    """Two containers on the same server (for packing / duplicate tests)."""
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 42},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": 3.0, "ram_cap_mb": 4096}],
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
                                "id": "c-a",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 512,
                            },
                            {
                                "id": "c-b",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 512,
                            },
                        ],
                    }
                ],
            }
        ],
    }
    trace_dir = tmp_path / "traces" / "demo"
    trace_dir.mkdir(parents=True)
    (trace_dir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")
    path = tmp_path / "shared.yaml"
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return path


class FakeScaler:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.seen_times: list[int] = []
        self.applied: list = []
        self._actions_by_tau: dict[int, list] = {}

    def set_actions(self, tau: int, actions: list) -> None:
        self._actions_by_tau[tau] = actions

    def on_tick_end(self, env: Env, tau: int) -> list:
        self.calls.append(tau)
        self.seen_times.append(env.get_time())
        _ = env.get_container(env.list_containers()[0]).history_at(tau)
        return list(self._actions_by_tau.get(tau, []))

    def on_actions_applied(self, results) -> None:
        self.applied.append(list(results))


def test_hook_none_matches_part_a(tiny_config_path, tmp_path):
    env_a = Env.from_config(tiny_config_path)
    env_a.world_spec = replace(
        env_a.world_spec, sim=replace(env_a.world_spec.sim, results_dir=str(tmp_path / "a"))
    )
    env_b = Env.from_config(tiny_config_path)
    env_b.world_spec = replace(
        env_b.world_spec, sim=replace(env_b.world_spec.sim, results_dir=str(tmp_path / "b"))
    )
    env_a.run(now_utc=datetime(2026, 1, 1, tzinfo=UTC))
    env_b.run(now_utc=datetime(2026, 1, 2, tzinfo=UTC), autoscaler=None)
    hist_a = [r.lambda_dropped for r in env_a.get_container("c-api-1").history]
    hist_b = [r.lambda_dropped for r in env_b.get_container("c-api-1").history]
    assert hist_a == hist_b


def test_hook_called_once_per_tick(tiny_config_path, tmp_path):
    env = Env.from_config(tiny_config_path)
    env.world_spec = replace(
        env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / "results"))
    )
    fake = FakeScaler()
    env.run(now_utc=datetime(2026, 1, 1, tzinfo=UTC), autoscaler=fake)
    assert fake.calls == list(range(1, env.traces.horizon + 1))


def test_hook_sees_correct_tau(tiny_config_path, tmp_path):
    env = Env.from_config(tiny_config_path)
    env.world_spec = replace(
        env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / "results"))
    )
    fake = FakeScaler()
    env.run(now_utc=datetime(2026, 1, 1, tzinfo=UTC), autoscaler=fake)
    assert fake.seen_times == list(range(1, env.traces.horizon + 1))


def test_apply_actions_sequential_packing(tmp_path):
    env = Env.from_config(_write_shared_server_config(tmp_path))
    # Cap 3.0, both at 1.0. First resize c-a to 1.8, second try c-b to 1.8 → 1.8+1.8=3.6 > 3.0
    actions = [
        ResizeAction(type="resize", ms_id="api", container_id="c-a", cpu_alloc_cores=1.8, reason="up"),
        ResizeAction(type="resize", ms_id="api", container_id="c-b", cpu_alloc_cores=1.8, reason="up"),
    ]
    results = env.apply_actions(actions, tau=1, autoscaler_name="fake")
    assert results[0].ok
    assert results[0].code == ResizeResultCode.OK
    assert not results[1].ok
    assert results[1].code == ResizeResultCode.SERVER_CPU_EXCEEDED
    assert env.get_container("c-a").cpu_alloc_cores == 1.8
    assert env.get_container("c-b").cpu_alloc_cores == 1.0


def test_apply_actions_duplicate_container_rejected(tmp_path):
    env = Env.from_config(_write_shared_server_config(tmp_path))
    actions = [
        ResizeAction(type="resize", ms_id="api", container_id="c-a", cpu_alloc_cores=1.2, reason="a"),
        ResizeAction(type="resize", ms_id="api", container_id="c-a", cpu_alloc_cores=1.4, reason="b"),
    ]
    results = env.apply_actions(actions, tau=1)
    assert results[0].ok
    assert results[1].code == ResizeResultCode.DUPLICATE_IN_BATCH
    assert env.get_container("c-a").cpu_alloc_cores == 1.2


def test_resize_effective_next_tick(tiny_config_path, tmp_path):
    env = Env.from_config(tiny_config_path)
    env.world_spec = replace(
        env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / "results"))
    )
    fake = FakeScaler()
    fake.set_actions(
        1,
        [ResizeAction(type="resize", ms_id="api", container_id="c-api-1", cpu_alloc_cores=2.0, reason="up")],
    )
    env.run(now_utc=datetime(2026, 1, 1, tzinfo=UTC), autoscaler=fake)
    assert env.get_container("c-api-1").history_at(1).cpu_alloc_cores == 1.0
    assert env.get_container("c-api-1").history_at(2).cpu_alloc_cores == 2.0


def test_on_actions_applied_called_with_results(tiny_config_path, tmp_path):
    env = Env.from_config(tiny_config_path)
    env.world_spec = replace(
        env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / "results"))
    )
    fake = FakeScaler()
    fake.set_actions(
        1,
        [ResizeAction(type="resize", ms_id="api", container_id="c-api-1", cpu_alloc_cores=1.5, reason="up")],
    )
    env.run(now_utc=datetime(2026, 1, 1, tzinfo=UTC), autoscaler=fake)
    # Action was only set for tau=1; every other tick applies an empty batch.
    assert len(fake.applied) == env.traces.horizon
    assert fake.applied[0][0].code == ResizeResultCode.OK
    assert all(applied == [] for applied in fake.applied[1:])


def test_actions_csv_written(tiny_config_path, tmp_path):
    env = Env.from_config(tiny_config_path)
    env.world_spec = replace(
        env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / "results"))
    )
    fake = FakeScaler()
    fake.set_actions(
        1,
        [ResizeAction(type="resize", ms_id="api", container_id="c-api-1", cpu_alloc_cores=1.5, reason="up")],
    )
    run_dir = env.run(now_utc=datetime(2026, 1, 1, tzinfo=UTC), autoscaler=fake)
    rows = list(csv.DictReader((run_dir / "actions.csv").open(encoding="utf-8")))
    assert len(rows) == 1
    assert rows[0]["action_type"] == "resize"
    assert rows[0]["result_code"] == "OK"


def test_actions_csv_header_only_when_empty(tiny_config_path, tmp_path):
    env = Env.from_config(tiny_config_path)
    env.world_spec = replace(
        env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / "results"))
    )
    run_dir = env.run(now_utc=datetime(2026, 1, 1, tzinfo=UTC))
    path = run_dir / "actions.csv"
    assert path.is_file()
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows == []
