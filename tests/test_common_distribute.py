"""Tests for common snapshot + paired distribute."""

from __future__ import annotations

from pathlib import Path

import yaml

from hierarchical_edge_sim.autoscaler.common.distribute import (
    DistributeParams,
    distribute_down,
    distribute_up,
    validate_distribute_params,
)
from hierarchical_edge_sim.autoscaler.common.snapshot import snapshot_ms
from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.models import ContainerTickRecord


def _env(tmp_path: Path, *, same_server: bool = False) -> Env:
    s2 = "c1-w1" if same_server else "c1-w2"
    cfg = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [
                        {"id": "c1-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 16384},
                        {"id": "c1-w2", "cpu_cap_cores": 8.0, "ram_cap_mb": 16384},
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
                        "cpu_max_cores": 4.0,
                        "ram_min_mb": 256,
                        "ram_max_mb": 4096,
                        "cpu_per_request_cores": 0.01,
                        "ram_per_request_mb": 0.5,
                        "trace_file": "api.csv",
                        "containers": [
                            {"id": "c-a", "server_id": "c1-w1", "cpu_alloc_cores": 1.0, "ram_alloc_mb": 512},
                            {"id": "c-b", "server_id": s2, "cpu_alloc_cores": 1.0, "ram_alloc_mb": 512},
                        ],
                    }
                ],
            }
        ],
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    (tdir / "api.csv").write_text(
        "time_unit,requests\n" + "\n".join(f"{i},10" for i in range(1, 6)) + "\n",
        encoding="utf-8",
    )
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def _hist(env: Env, tau: int = 1, *, drop_a: float = 0.0, drop_b: float = 0.0, q: float = 0.5):
    for cid, drop in (("c-a", drop_a), ("c-b", drop_b)):
        c = env.get_container(cid)
        c.append_history(
            ContainerTickRecord(
                tau=tau,
                lambda_in=50.0 + drop,
                lambda_served=50.0,
                lambda_dropped=drop,
                cpu_usage_cores=c.cpu_alloc_cores,
                ram_usage_mb=c.ram_alloc_mb,
                cpu_alloc_cores=c.cpu_alloc_cores,
                ram_alloc_mb=c.ram_alloc_mb,
                q_cpu=q,
                q_ram=q,
            )
        )
    env.state.current_tau = tau


def test_validate_distribute_params_defaults():
    p = validate_distribute_params({})
    assert p.prefer_consolidate_down is True
    assert p.grow_weights[0] == 0.5


def test_snapshot_room_up_respects_ms_max(tmp_path):
    env = _env(tmp_path)
    env.resize("c-a", cpu_alloc_cores=4.0, ram_alloc_mb=4096)
    _hist(env)
    snap = snapshot_ms(env, "api", 1)
    a = next(r for r in snap.replicas if r.container_id == "c-a")
    assert a.room_up_cpu == 0.0
    assert a.room_up_ram == 0.0
    assert snap.u_meas == 0.5


def test_snapshot_room_up_respects_server_free(tmp_path):
    env = _env(tmp_path)
    # Fill server almost completely with c-a so little free remains
    env.resize("c-a", cpu_alloc_cores=3.9, ram_alloc_mb=4000)
    _hist(env)
    snap = snapshot_ms(env, "api", 1)
    a = next(r for r in snap.replicas if r.container_id == "c-a")
    # MS max still allows 0.1 CPU, but check room is small / non-negative
    assert a.room_up_cpu <= 0.1 + 1e-9
    assert a.room_up_cpu >= 0.0


def test_distribute_up_paired_allows_cpu_when_ram_at_bound(tmp_path):
    env = _env(tmp_path)
    _hist(env, drop_a=20.0)
    snap = snapshot_ms(env, "api", 1)
    from dataclasses import replace

    reps = []
    for r in snap.replicas:
        if r.container_id == "c-a":
            reps.append(replace(r, room_up_ram=0.0, room_up_cpu=2.0, drop=20.0))
        else:
            reps.append(replace(r, drop=0.0, room_up_cpu=0.0, room_up_ram=0.0))
    actions = distribute_up(
        env=env,
        ms_id="api",
        spec=snap.spec,
        params=DistributeParams(),
        replicas=reps,
        delta_cpu=1.0,
        delta_ram=256.0,
        tau=1,
        reason="proactive_up",
    )
    resizes = [a for a in actions if getattr(a, "type", "") == "resize"]
    assert len(resizes) == 1
    assert resizes[0].cpu_alloc_cores > 1.0
    assert resizes[0].ram_alloc_mb == 512.0  # unchanged — RAM at bound


def test_distribute_up_pairs_both_dims(tmp_path):
    env = _env(tmp_path)
    _hist(env, drop_a=20.0)
    snap = snapshot_ms(env, "api", 1)
    actions = distribute_up(
        env=env,
        ms_id="api",
        spec=snap.spec,
        params=DistributeParams(),
        replicas=snap.replicas,
        delta_cpu=0.5,
        delta_ram=128.0,
        tau=1,
        reason="proactive_up",
    )
    resizes = [a for a in actions if getattr(a, "type", "") == "resize"]
    assert resizes
    a = resizes[0]
    assert a.cpu_alloc_cores > 1.0
    assert a.ram_alloc_mb > 512.0
    assert a.reason == "proactive_up"


def test_distribute_down_consolidate_one(tmp_path):
    env = _env(tmp_path)
    env.resize("c-a", cpu_alloc_cores=2.0, ram_alloc_mb=1024)
    env.resize("c-b", cpu_alloc_cores=2.0, ram_alloc_mb=1024)
    _hist(env, q=0.1)
    snap = snapshot_ms(env, "api", 1)
    actions = distribute_down(
        env=env,
        ms_id="api",
        spec=snap.spec,
        params=DistributeParams(prefer_consolidate_down=True),
        replicas=snap.replicas,
        delta_cpu=0.5,
        delta_ram=128.0,
        tau=1,
        reason="proactive_down",
    )
    assert len(actions) == 1
    assert actions[0].cpu_alloc_cores < 2.0
    assert actions[0].ram_alloc_mb < 1024.0
