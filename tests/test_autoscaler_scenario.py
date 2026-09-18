"""Integration + final scenario tests (Steps 5–6)."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path

import yaml

from hierarchical_edge_sim.autoscaler.common.load import load_autoscaler_from_yaml
from hierarchical_edge_sim.env.api import Env


def _sum_drops(run_dir: Path) -> float:
    total = 0.0
    for log in run_dir.glob("apps/**/*.log.csv"):
        with log.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                total += float(row["dropped_requests"])
    return total


def _sum_drops_window(run_dir: Path, t0: int, t1: int) -> float:
    total = 0.0
    for log in run_dir.glob("apps/**/*.log.csv"):
        with log.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                tau = int(row["time_unit"])
                if t0 <= tau <= t1:
                    total += float(row["dropped_requests"])
    return total


def test_phased_trace_length(project_root: Path):
    path = project_root / "traces" / "demo" / "api_300_phased.csv"
    rows = path.read_text(encoding="utf-8").strip().splitlines()
    assert rows[0] == "time_unit,requests"
    data = rows[1:]
    assert len(data) == 300
    for i, line in enumerate(data, start=1):
        tu, _ = line.split(",")
        assert int(tu) == i


def test_demo_config_loads_scaler(project_root: Path):
    for name in (
        "06-demo_300_two_containers_reactive.yaml",
        "07-demo_300_two_containers_reactive_local.yaml",
        "03-demo_60_two_containers_reactive.yaml",
        "08-demo_60_reactive_local.yaml",
        "11-demo_60_proactive.yaml",
        "16-demo_400_triangle.yaml",
        "17-demo_400_triangle_horizontal.yaml",
        "18-demo_400_triangle_vicinity.yaml",
        "19-demo_400_triangle_skip_neighbor.yaml",
    ):
        scaler = load_autoscaler_from_yaml(project_root / "configs" / name)
        assert scaler is not None
        assert scaler.name in {"reactive_vertical", "reactive_local", "proactive_auto_scaler"}


def test_integration_up_then_alloc_rises(tmp_path, project_root: Path):
    # Short engineered overload using tiny world + fake high load via real run on 60 reactive
    cfg = project_root / "configs" / "03-demo_60_two_containers_reactive.yaml"
    env = Env.from_config(cfg)
    # redirect results
    from dataclasses import replace

    env.world_spec = replace(
        env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / "r"))
    )
    scaler = load_autoscaler_from_yaml(cfg)
    initial = {cid: env.get_container(cid).cpu_alloc_cores for cid in env.list_containers()}
    env.run(autoscaler=scaler, now_utc=datetime(2026, 2, 1, tzinfo=UTC))
    assert any(env.get_container(cid).cpu_alloc_cores > initial[cid] for cid in initial)
    assert any(row.action_type == "resize" and "up" in row.reason for row in env.action_log)


def test_final_scenario_long_drops_and_actions(tmp_path, project_root: Path):
    from dataclasses import replace

    static_cfg = project_root / "configs" / "05-demo_300_two_containers.yaml"
    reactive_cfg = project_root / "configs" / "06-demo_300_two_containers_reactive.yaml"

    env_s = Env.from_config(static_cfg)
    env_s.world_spec = replace(
        env_s.world_spec, sim=replace(env_s.world_spec.sim, results_dir=str(tmp_path / "static"))
    )
    run_s = env_s.run(now_utc=datetime(2026, 3, 1, tzinfo=UTC))

    env_r = Env.from_config(reactive_cfg)
    env_r.world_spec = replace(
        env_r.world_spec, sim=replace(env_r.world_spec.sim, results_dir=str(tmp_path / "reactive"))
    )
    scaler = load_autoscaler_from_yaml(reactive_cfg)
    run_r = env_r.run(autoscaler=scaler, now_utc=datetime(2026, 3, 2, tzinfo=UTC))

    plateau_s = _sum_drops_window(run_s, 71, 180)
    plateau_r = _sum_drops_window(run_r, 71, 180)
    assert plateau_r < plateau_s, f"plateau drops reactive={plateau_r} static={plateau_s}"

    ups = [r for r in env_r.action_log if r.action_type == "resize" and "up" in r.reason and r.result_code == "OK"]
    downs = [r for r in env_r.action_log if r.action_type == "resize" and "down" in r.reason and r.result_code == "OK"]
    assert ups, "expected at least one UP during overload"
    assert downs, "expected at least one DOWN"
    # Ups may begin on the ramp into overload (Λ already > μ before τ=71).
    assert any(41 <= r.tau <= 180 for r in ups)
    assert any(r.tau >= 211 for r in downs)

    meta = yaml.safe_load((run_r / "run_meta.yaml").read_text(encoding="utf-8"))
    assert meta["autoscaler"]["name"] == "reactive_vertical"


def test_final_scenario_long_determinism(tmp_path, project_root: Path):
    from dataclasses import replace

    cfg = project_root / "configs" / "06-demo_300_two_containers_reactive.yaml"
    scaler1 = load_autoscaler_from_yaml(cfg)
    scaler2 = load_autoscaler_from_yaml(cfg)

    env1 = Env.from_config(cfg)
    env1.world_spec = replace(
        env1.world_spec, sim=replace(env1.world_spec.sim, results_dir=str(tmp_path / "d1"))
    )
    run1 = env1.run(autoscaler=scaler1, now_utc=datetime(2026, 4, 1, tzinfo=UTC))

    env2 = Env.from_config(cfg)
    env2.world_spec = replace(
        env2.world_spec, sim=replace(env2.world_spec.sim, results_dir=str(tmp_path / "d2"))
    )
    run2 = env2.run(autoscaler=scaler2, now_utc=datetime(2026, 4, 2, tzinfo=UTC))

    a1 = (run1 / "actions.csv").read_text(encoding="utf-8")
    a2 = (run2 / "actions.csv").read_text(encoding="utf-8")
    assert a1 == a2
    for log_name in sorted(p.name for p in (run1 / "apps").rglob("*.log.csv")):
        p1 = next((run1 / "apps").rglob(log_name))
        p2 = next((run2 / "apps").rglob(log_name))
        assert p1.read_text(encoding="utf-8") == p2.read_text(encoding="utf-8")


def test_triangle_trace_matches_yaml_hold(project_root: Path):
    path = project_root / "traces" / "demo" / "api_400_triangle.csv"
    rows = path.read_text(encoding="utf-8").strip().splitlines()
    assert rows[0] == "time_unit,requests"
    data = rows[1:]
    assert len(data) == 400
    vals = []
    for i, line in enumerate(data, start=1):
        tu, req = line.split(",")
        assert int(tu) == i
        vals.append(int(req))
    assert vals[0] == 40
    assert vals[199] == 180
    assert vals[319] == 5
    assert all(v == 5 for v in vals[320:])
    assert all(vals[i] <= vals[i + 1] for i in range(199))
    assert all(vals[i] >= vals[i + 1] for i in range(200, 319))


def test_triangle_reclaims_to_one_local_without_chatter(tmp_path, project_root: Path):
    env = _run_triangle(project_root, tmp_path, "16-demo_400_triangle.yaml", "triangle")
    _assert_triangle_hold(env)
    reasons = {row.reason for row in env.action_log if row.result_code == "OK"}
    assert "vicinity_spawn" in reasons
    assert "vicinity_terminate" in reasons
    assert "horizontal_terminate" not in reasons
    remote_spawns = [
        r
        for r in env.action_log
        if r.result_code == "OK" and r.reason == "vicinity_spawn"
    ]
    assert remote_spawns
    assert all(r.cpu_new is not None and r.cpu_new > 0.5 for r in remote_spawns)
    assert not any("c3-w1" in (r.container_id or "") for r in remote_spawns)
    assert any(row.action_type == "unmet_demand" for row in env.action_log)


def _run_triangle(project_root: Path, tmp_path: Path, name: str, stamp: str) -> Env:
    from dataclasses import replace

    cfg = project_root / "configs" / name
    env = Env.from_config(cfg)
    env.world_spec = replace(
        env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / stamp))
    )
    scaler = load_autoscaler_from_yaml(cfg)
    env.run(autoscaler=scaler, now_utc=datetime(2026, 8, 20, tzinfo=UTC))
    return env


def _assert_triangle_hold(env: Env, *, expect_seed: bool = True) -> None:
    live = env.list_containers()
    assert len(live) == 1
    cid = live[0]
    leftover = env.get_container(cid)
    assert env.get_server(leftover.server_id).cluster_id == "c1"
    assert leftover.cpu_alloc_cores > 0.5
    if expect_seed:
        assert cid == "c-api-0"
        assert leftover.server_id == "c1-w1"
    ram_dust = [
        r
        for r in env.action_log
        if r.result_code == "OK"
        and r.action_type == "resize"
        and "down" in r.reason
        and r.cpu_old is not None
        and r.cpu_new is not None
        and r.cpu_old == r.cpu_new
        and r.ram_old is not None
        and r.ram_new is not None
        and abs(r.ram_old - r.ram_new) < 1.0
    ]
    assert ram_dust == [], "vertical down must not chatter sub-MB RAM dust"
    mu = max(0.0, leftover.cpu_alloc_cores - 0.5) / 0.01
    matched_ram = 256.0 + mu * 0.5
    assert abs(leftover.ram_alloc_mb - matched_ram) < 2.0, "leftover RAM must match serving μ, not ram_max"
    terms = [
        r
        for r in env.action_log
        if r.result_code == "OK"
        and r.reason in {"horizontal_terminate", "vicinity_terminate"}
    ]
    assert terms, "surplus reclaim must terminate extras before the hold"
    last_term = max(r.tau for r in terms)
    later_up = [
        r
        for r in env.action_log
        if r.result_code == "OK"
        and r.tau > last_term
        and r.action_type == "resize"
        and "up" in r.reason
    ]
    assert later_up == [], "last replica must not bounce UP after extras are gone"
    later_floor = [
        r
        for r in env.action_log
        if r.result_code == "OK"
        and r.tau > last_term
        and r.action_type == "resize"
        and "down" in r.reason
        and r.container_id == cid
        and r.cpu_new is not None
        and r.cpu_new <= 0.5
    ]
    assert later_floor == [], "surplus must not walk the last replica onto μ=0"


def test_triangle_horizontal_stays_in_cluster(tmp_path, project_root: Path):
    env = _run_triangle(project_root, tmp_path, "17-demo_400_triangle_horizontal.yaml", "horizontal")
    _assert_triangle_hold(env, expect_seed=False)
    leftover = env.get_container(env.list_containers()[0])
    assert leftover.server_id == "c1-w2"
    reasons = {row.reason for row in env.action_log if row.result_code == "OK"}
    assert "horizontal_spawn" in reasons
    assert "horizontal_terminate" in reasons
    assert "vicinity_spawn" not in reasons
    assert "vicinity_terminate" not in reasons
    extras = [r for r in env.action_log if r.reason == "horizontal_spawn" and r.result_code == "OK"]
    assert extras
    assert all(r.cpu_new is not None and r.cpu_new > 0.5 for r in extras)
    assert all("c1-w2" in (r.container_id or "") for r in extras)


def test_triangle_vicinity_never_leaves_group(tmp_path, project_root: Path):
    env = _run_triangle(project_root, tmp_path, "18-demo_400_triangle_vicinity.yaml", "vic")
    _assert_triangle_hold(env)
    reasons = {row.reason for row in env.action_log if row.result_code == "OK"}
    assert "vicinity_spawn" in reasons
    assert "vicinity_terminate" in reasons
    assert "horizontal_spawn" not in reasons
    assert "horizontal_terminate" not in reasons
    spawns = [r for r in env.action_log if r.reason == "vicinity_spawn" and r.result_code == "OK"]
    assert all(r.cpu_new is not None and r.cpu_new > 0.5 for r in spawns)
    assert all("c2-w1" in (r.container_id or "") for r in spawns)


def test_triangle_floor_neighbor_logs_unmet_not_outside_spawn(tmp_path, project_root: Path):
    env = _run_triangle(project_root, tmp_path, "19-demo_400_triangle_skip_neighbor.yaml", "skip")
    live = env.list_containers()
    assert len(live) == 1
    leftover = env.get_container(live[0])
    assert env.get_server(leftover.server_id).cluster_id == "c1"
    assert leftover.cpu_alloc_cores > 0.5
    reasons = {row.reason for row in env.action_log if row.result_code == "OK"}
    assert "vicinity_spawn" not in reasons
    assert "horizontal_spawn" not in reasons
    assert not any("c3-w1" in (r.container_id or "") for r in env.action_log if r.result_code == "OK")
    assert any(
        r.action_type == "unmet_demand" and r.result_code == "LOGGED" for r in env.action_log
    )
