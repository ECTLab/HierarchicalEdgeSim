"""Lender Reserve_c / safe_j: leftover own ρ is not offered to the group."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.autoscaler.reactive_local.help import HelpRequest
from hierarchical_edge_sim.autoscaler.reactive_local.reserve import member_safe_ceilings
from hierarchical_edge_sim.autoscaler.reactive_local.vicinity import (
    collect_reports,
    schedule_vicinity_plan,
)
from hierarchical_edge_sim.env.api import Env


VALID_TRACE = "time_unit,requests\n" + "\n".join(f"{i},50" for i in range(1, 11)) + "\n"


def _write_world(tmp_path: Path) -> Env:
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
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 2.0, "ram_cap_mb": 2048}],
                },
            ],
            "vicinities": [{"id": "v1", "members": ["c1", "c2"], "leader": "c1"}],
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


def _rho(env: Env, home: str, cpu: float, ram: float, ms_id: str = "api") -> HelpRequest:
    spec = env.get_ms_spec(ms_id)
    return HelpRequest(
        seq=0,
        tau=1,
        ms_id=ms_id,
        home_cluster_id=home,
        remain_cpu=cpu,
        remain_ram=ram,
        cpu_min=spec.cpu_min_cores,
        ram_min=spec.ram_min_mb,
        min_head_cpu=0.25,
        min_head_ram=128.0,
        t_det=1,
    )


def test_empty_offer_safe_equals_post_local_free(tmp_path):
    env = _write_world(tmp_path)
    members = env.list_vicinity_members("v1")
    safe_cpu, safe_ram = member_safe_ceilings(env, members, pending=[], requests=[])
    assert safe_cpu["c1-w1"] == 0.0
    assert safe_cpu["c2-w1"] == 2.0
    assert safe_ram["c2-w1"] == 2048.0


def test_leftover_rho_zeros_safe_when_reserve_covers_free(tmp_path):
    env = _write_world(tmp_path)
    members = env.list_vicinity_members("v1")
    # c2 has 2.0 free; a leftover ρ of 2.0 is its own next-window demand.
    req = _rho(env, "c2", 2.0, 1024.0)
    safe_cpu, _safe_ram = member_safe_ceilings(env, members, pending=[], requests=[req])
    assert safe_cpu["c2-w1"] == 0.0
    assert safe_cpu["c1-w1"] == 0.0


def test_reserve_prorates_across_free(tmp_path):
    env = _write_world(tmp_path)
    members = env.list_vicinity_members("v1")
    req = _rho(env, "c2", 1.0, 0.0)
    safe_cpu, _safe_ram = member_safe_ceilings(env, members, pending=[], requests=[req])
    assert safe_cpu["c2-w1"] == 1.0


def test_leader_does_not_lend_reserved_capacity(tmp_path):
    env = _write_world(tmp_path)
    c1_need = _rho(env, "c1", 0.5, 256.0)
    c2_own = _rho(env, "c2", 2.0, 1024.0)
    reports = collect_reports(env, [c1_need, c2_own], [], 1)
    plan = schedule_vicinity_plan(env, "v1", reports, pending=[], tau=1)
    assert not any(e.act == "spawn" for e in plan.entries)
    assert any(u.ms_id == "api" and u.home_cluster_id == "c1" for u in plan.unmet)
