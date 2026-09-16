"""ScheduleReleases: farthest lenders first, then shrink leftover L."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.autoscaler.reactive_local.help import ReleaseIntent
from hierarchical_edge_sim.autoscaler.reactive_local.release import (
    schedule_releases,
    split_borrowed_share,
)
from hierarchical_edge_sim.env.api import Env, TerminateAction
from hierarchical_edge_sim.env.loans import add_loan
from hierarchical_edge_sim.env.models import LoanTier


VALID_TRACE = "time_unit,requests\n" + "\n".join(f"{i},50" for i in range(1, 11)) + "\n"


def test_split_borrowed_share_remote_covers_reduction():
    l_cpu, l_ram, local_cpu, local_ram = split_borrowed_share(0.4, 100.0, 0.5, 256.0)
    assert (l_cpu, l_ram) == (0.4, 100.0)
    assert (local_cpu, local_ram) == (0.0, 0.0)


def test_split_borrowed_share_local_gets_remainder():
    l_cpu, l_ram, local_cpu, local_ram = split_borrowed_share(2.0, 800.0, 0.5, 256.0)
    assert (l_cpu, l_ram) == (0.5, 256.0)
    assert (local_cpu, local_ram) == (1.5, 544.0)


def test_split_borrowed_share_independent_wallets():
    l_cpu, l_ram, local_cpu, local_ram = split_borrowed_share(0.2, 800.0, 0.5, 256.0)
    assert (l_cpu, l_ram) == (0.2, 256.0)
    assert (local_cpu, local_ram) == (0.0, 544.0)


def _write_world(
    tmp_path: Path,
    *,
    borrowed_cpu: float,
    borrowed_ram: float,
    two_lenders: bool = False,
) -> Env:
    containers: list[dict[str, Any]] = [
        {
            "id": "c-api-1",
            "server_id": "c1-w1",
            "cpu_alloc_cores": 1.0,
            "ram_alloc_mb": 512.0,
        },
        {
            "id": "c-api-2",
            "server_id": "c2-w1",
            "cpu_alloc_cores": borrowed_cpu,
            "ram_alloc_mb": borrowed_ram,
        },
    ]
    clusters: list[dict[str, Any]] = [
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
    ]
    members = ["c1", "c2"]
    if two_lenders:
        containers.append(
            {
                "id": "c-api-3",
                "server_id": "c3-w1",
                "cpu_alloc_cores": 0.5,
                "ram_alloc_mb": 256.0,
            }
        )
        clusters.append(
            {
                "id": "c3",
                "coords": [10.0, 0.0],
                "servers": [{"id": "c3-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096}],
            }
        )
        members.append("c3")
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": clusters,
            "vicinities": [{"id": "v1", "members": members, "leader": "c1"}],
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
                        "containers": containers,
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
    env = Env.from_config(path)
    add_loan(env.get_server("c2-w1"), borrower_cluster_id="c1", ms_id="api", tier=LoanTier.VICINITY, ts=5)
    if two_lenders:
        add_loan(
            env.get_server("c3-w1"),
            borrower_cluster_id="c1",
            ms_id="api",
            tier=LoanTier.VICINITY,
            ts=1,
        )
    return env


def _xi(env: Env, cpu: float, ram: float, mu_tgt: float | None = None) -> ReleaseIntent:
    return ReleaseIntent(
        seq=0,
        tau=1,
        ms_id="api",
        home_cluster_id=env.get_app_owner_cluster_id("api"),
        remain_cpu=cpu,
        remain_ram=ram,
        t_det=1,
        mu_tgt=mu_tgt,
    )


def test_schedule_releases_terminates_farthest_lender_first(tmp_path):
    env = _write_world(tmp_path, borrowed_cpu=0.5, borrowed_ram=256.0, two_lenders=True)
    actions = schedule_releases(env, [_xi(env, 0.25, 128.0)], pending=[], tau=1)
    terms = [a for a in actions if getattr(a, "type", "") == "terminate"]
    assert [a.container_id for a in terms] == ["c-api-3"]
    assert terms[0].reason == "vicinity_terminate"


def test_schedule_releases_shrinks_leftover_too_small_for_instance(tmp_path):
    env = _write_world(tmp_path, borrowed_cpu=2.0, borrowed_ram=1024.0)
    actions = schedule_releases(env, [_xi(env, 0.3, 128.0, mu_tgt=1.0)], pending=[], tau=1)
    terms = [a for a in actions if getattr(a, "type", "") == "terminate"]
    downs = [a for a in actions if getattr(a, "reason", "") == "vicinity_down"]
    assert terms == []
    assert len(downs) == 1
    assert downs[0].container_id == "c-api-2"
    assert downs[0].cpu_alloc_cores == 1.7
    assert downs[0].ram_alloc_mb == 896.0


def test_schedule_releases_never_kills_last_replica(tmp_path):
    env = _write_world(tmp_path, borrowed_cpu=0.5, borrowed_ram=256.0)
    env.apply_actions(
        [
            TerminateAction(
                type="terminate",
                ms_id="api",
                container_id="c-api-1",
                reason="scripted",
                tau=1,
            )
        ],
        tau=1,
        autoscaler_name="scripted",
    )
    actions = schedule_releases(env, [_xi(env, 8.0, 2048.0)], pending=[], tau=1)
    assert actions == []
    assert "c-api-2" in env.world.containers
