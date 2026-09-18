"""Reactive local: VerticalScaling then in-cluster HorizontalScaling."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from hierarchical_edge_sim.autoscaler.common.load import load_autoscaler_from_yaml
from hierarchical_edge_sim.autoscaler.reactive_local.allocate import down_delta, up_delta
from hierarchical_edge_sim.autoscaler.reactive_local.params import ReactiveLocalParams, validate_params
from hierarchical_edge_sim.autoscaler.reactive_local.policy import build
from hierarchical_edge_sim.env.api import Env, NeedVicinityHelpAction
from hierarchical_edge_sim.env.models import ContainerTickRecord


def test_params_defaults_and_unknown_key():
    p = validate_params({})
    assert p.sustained_up_streak == 6
    assert p.cascade_home is True
    assert p.min_mu_step == 25.0
    with pytest.raises(ValueError, match="unknown reactive_local"):
        validate_params({"not_a_param": 1})
    with pytest.raises(ValueError, match="alpha_up/alpha_down were removed"):
        validate_params({"alpha_up": 0.20})
    with pytest.raises(ValueError, match="min_mu_step"):
        validate_params({"delta_cpu_min_cores": 0.25})


def _write_world(
    tmp_path: Path,
    *,
    w1_cpu: float = 8.0,
    w2_cpu: float = 8.0,
    cpu_max: float = 4.0,
    cpu_alloc: float = 1.0,
    ram_alloc: float = 512.0,
    ram_max: float = 2048.0,
    two_replicas: bool = False,
) -> Env:
    containers: list[dict[str, Any]] = [
        {
            "id": "c-api-1",
            "server_id": "c1-w1",
            "cpu_alloc_cores": cpu_alloc,
            "ram_alloc_mb": ram_alloc,
        }
    ]
    if two_replicas:
        containers.append(
            {
                "id": "c-api-2",
                "server_id": "c1-w2",
                "cpu_alloc_cores": cpu_alloc,
                "ram_alloc_mb": ram_alloc,
            }
        )
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [
                        {"id": "c1-w1", "cpu_cap_cores": w1_cpu, "ram_cap_mb": 4096},
                        {"id": "c1-w2", "cpu_cap_cores": w2_cpu, "ram_cap_mb": 4096},
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
                        "cpu_max_cores": cpu_max,
                        "ram_min_mb": 256,
                        "ram_max_mb": ram_max,
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
    rows = ["time_unit,requests"] + [f"{i},50" for i in range(1, 11)]
    (tdir / "api.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def _push_drops(env: Env, tau: int, *, drop: float = 40.0, q: float = 1.0) -> None:
    for cid in env.get_microservice("api").container_ids:
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
                q_cpu=q,
                q_ram=q,
            )
        )
    env.state.current_tau = tau


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


def test_ms_max_spawns_on_same_worker_when_server_has_room(tmp_path):
    env = _write_world(
        tmp_path, cpu_max=1.0, cpu_alloc=1.0, ram_alloc=2048.0, ram_max=2048.0, w1_cpu=8.0, w2_cpu=8.0
    )
    scaler = build(
        {"x_up_streak": 1, "y_down_streak": 99, "cooldown_ticks": 0, "sustained_up_streak": 99}
    )
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert spawns
    assert spawns[0].server_id == "c1-w1"
    assert spawns[0].cpu_alloc_cores == 0.9
    assert spawns[0].ram_alloc_mb == 276.0
    assert not any(getattr(a, "type", "") == "resize" for a in actions)


def test_worker_full_spawns_on_sibling(tmp_path):
    env = _write_world(
        tmp_path, cpu_max=1.0, cpu_alloc=1.0, ram_alloc=2048.0, ram_max=2048.0, w1_cpu=1.0, w2_cpu=8.0
    )
    scaler = build(
        {"x_up_streak": 1, "y_down_streak": 99, "cooldown_ticks": 0, "sustained_up_streak": 99}
    )
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    spawns = [a for a in actions if getattr(a, "type", "") == "spawn"]
    assert len(spawns) == 1
    assert spawns[0].server_id == "c1-w2"


def test_cluster_full_logs_need_vicinity_help(tmp_path):
    env = _write_world(
        tmp_path, cpu_max=1.0, cpu_alloc=1.0, ram_alloc=2048.0, ram_max=2048.0, w1_cpu=1.0, w2_cpu=0.4
    )
    scaler = build(
        {"x_up_streak": 1, "y_down_streak": 99, "cooldown_ticks": 0, "sustained_up_streak": 99}
    )
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)
    helps = [a for a in actions if isinstance(a, NeedVicinityHelpAction)]
    assert len(helps) == 1
    assert helps[0].cluster_id == "c1"
    env.apply_actions(actions, tau=1, autoscaler_name="reactive_local")
    assert any(row.action_type == "need_vicinity_help" and row.result_code == "LOGGED" for row in env.action_log)


def test_sustained_skips_bev(tmp_path):
    env = _write_world(tmp_path, cpu_max=4.0, cpu_alloc=1.0, w1_cpu=8.0)
    scaler = build(
        {"x_up_streak": 1, "y_down_streak": 99, "cooldown_ticks": 0, "sustained_up_streak": 1}
    )
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    assert any(getattr(a, "type", "") == "spawn" for a in actions)
    assert not any(getattr(a, "type", "") == "resize" for a in actions)


def test_non_sustained_uses_vertical_when_room(tmp_path):
    env = _write_world(tmp_path, cpu_max=4.0, cpu_alloc=1.0, w1_cpu=8.0)
    scaler = build(
        {"x_up_streak": 1, "y_down_streak": 99, "cooldown_ticks": 0, "sustained_up_streak": 99}
    )
    _push_drops(env, 1)
    actions = scaler.on_tick_end(env, 1)
    assert any(getattr(a, "type", "") == "resize" and a.reason == "vertical_up" for a in actions)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)


def test_down_terminates_extra_replica_at_minima(tmp_path):
    env = _write_world(tmp_path, two_replicas=True, cpu_alloc=0.5, cpu_max=4.0)
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
    assert terms[0].container_id in {"c-api-1", "c-api-2"}


def test_down_peels_serving_extra_before_terminate(tmp_path):
    env = _write_world(tmp_path, two_replicas=True, cpu_alloc=1.0, cpu_max=4.0)
    scaler = build(
        {
            "x_up_streak": 99,
            "y_down_streak": 1,
            "cooldown_ticks": 0,
            "theta_free": 0.35,
            "sustained_up_streak": 99,
            "cascade_home": False,
        }
    )
    _push_slack(env, 1)
    first = scaler.on_tick_end(env, 1)
    downs = [a for a in first if getattr(a, "reason", "") == "vertical_down"]
    terms = [a for a in first if getattr(a, "type", "") == "terminate"]
    assert terms == []
    assert len(downs) == 1
    victim = downs[0].container_id
    assert victim in {"c-api-1", "c-api-2"}
    assert downs[0].cpu_alloc_cores is not None and downs[0].cpu_alloc_cores < 1.0
    keeper = "c-api-2" if victim == "c-api-1" else "c-api-1"
    assert not any(getattr(a, "container_id", "") == keeper for a in first)

    results = env.apply_actions(first, tau=1, autoscaler_name="reactive_local")
    scaler.on_actions_applied(results)
    assert env.get_container(victim).cpu_alloc_cores == pytest.approx(0.5)
    assert env.get_container(keeper).cpu_alloc_cores == pytest.approx(1.0)

    _push_slack(env, 2)
    second = scaler.on_tick_end(env, 2)
    terms = [a for a in second if getattr(a, "type", "") == "terminate"]
    downs = [a for a in second if getattr(a, "reason", "") == "vertical_down"]
    assert downs == []
    assert [a.container_id for a in terms] == [victim]


def test_floor_kill_follows_peel_during_cooldown(tmp_path):
    env = _write_world(tmp_path, two_replicas=True, cpu_alloc=1.0, cpu_max=4.0)
    scaler = build(
        {
            "x_up_streak": 99,
            "y_down_streak": 1,
            "cooldown_ticks": 5,
            "theta_free": 0.35,
            "sustained_up_streak": 99,
            "cascade_home": False,
        }
    )
    _push_slack(env, 1)
    first = scaler.on_tick_end(env, 1)
    downs = [a for a in first if getattr(a, "reason", "") == "vertical_down"]
    assert len(downs) == 1
    victim = downs[0].container_id
    keeper = "c-api-2" if victim == "c-api-1" else "c-api-1"
    results = env.apply_actions(first, tau=1, autoscaler_name="reactive_local")
    scaler.on_actions_applied(results)
    assert env.get_container(victim).cpu_alloc_cores == pytest.approx(0.5)
    assert scaler._state["api"].cooldown == 5
    assert scaler._state["api"].pending_floor_kill == victim

    _push_slack(env, 2)
    second = scaler.on_tick_end(env, 2)
    terms = [a for a in second if getattr(a, "type", "") == "terminate"]
    downs = [a for a in second if getattr(a, "reason", "") == "vertical_down"]
    assert downs == []
    assert [a.container_id for a in terms] == [victim]
    assert not any(getattr(a, "container_id", "") == keeper for a in second)


def test_yaml_loads_reactive_local(tmp_path):
    env = _write_world(tmp_path)
    cfg = yaml.safe_load((tmp_path / "cfg.yaml").read_text(encoding="utf-8"))
    cfg["autoscaler"] = {
        "enabled": True,
        "name": "reactive_local",
        "params": {"x_up_streak": 1, "sustained_up_streak": 4},
    }
    path = tmp_path / "with_scaler.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    scaler = load_autoscaler_from_yaml(path)
    assert scaler is not None
    assert scaler.name == "reactive_local"
    assert scaler.cycle == "cluster_manager"
    assert scaler.allocate == "allocate_resources"
    assert scaler.params.sustained_up_streak == 4
    from hierarchical_edge_sim.env.api import _autoscaler_meta

    meta = _autoscaler_meta(scaler)
    assert meta["allocate"] == "allocate_resources"
    assert meta["cycle"] == "cluster_manager"
    assert "decide" not in meta
    assert meta["params"]["grow_weights"] == {"drop": 0.5, "util": 0.3, "room": 0.2}
    assert meta["params"]["shrink_weights"] == {"slack": 0.5, "no_drop": 0.3, "room": 0.2}
    _ = env


def _surplus_obs(**kwargs: Any) -> dict[str, Any]:
    obs: dict[str, Any] = {
        "Lambda": 5.0,
        "spec": SimpleNamespace(cpu_per_request_cores=0.01, ram_per_request_mb=0.5),
        "replicas": [object()],
        "sum_cpu_alloc": 1.0,
        "sum_ram_alloc": 512.0,
        "sum_h_cpu": 0.5,
        "sum_h_ram": 256.0,
    }
    obs.update(kwargs)
    return obs


def test_up_delta_ram_follows_cpu_mu_not_fat_alloc():
    params = ReactiveLocalParams(min_mu_step=25.0)
    cpu, ram = up_delta(
        _surplus_obs(D=80.0, sum_cpu_alloc=1.0, sum_ram_alloc=512.0),
        params,
    )
    # D=80 req → 0.80 cores; RAM is 80 × 0.5 MB, not a fraction of 512.
    assert cpu == pytest.approx(0.80)
    assert ram == pytest.approx(40.0)


def test_up_delta_floors_tiny_d_at_min_mu_step():
    params = ReactiveLocalParams(min_mu_step=25.0)
    cpu, ram = up_delta(_surplus_obs(D=1.0), params)
    assert cpu == pytest.approx(0.25)
    assert ram == pytest.approx(12.5)


def test_surplus_last_replica_does_not_take_delta_min_past_target():
    params = ReactiveLocalParams(theta_free=0.35)
    # Λ=5, q_tgt=0.65 → μ_tgt ≈ 7.69. Matching headroom on CPU and RAM → hold.
    h_cpu = 5.0 * 0.01 / 0.65
    h_ram = 5.0 * 0.5 / 0.65
    cpu, ram = down_delta(_surplus_obs(sum_h_cpu=h_cpu, sum_h_ram=h_ram), params)
    assert cpu == pytest.approx(0.0)
    assert ram == pytest.approx(0.0)


def test_surplus_last_replica_releases_full_overshoot():
    params = ReactiveLocalParams(theta_free=0.35)
    cpu, _ = down_delta(_surplus_obs(sum_h_cpu=0.5), params)
    surplus = 0.5 - 5.0 * 0.01 / 0.65
    assert cpu == pytest.approx(surplus)


def test_surplus_tiny_overshoot_is_the_surplus_not_delta_min():
    params = ReactiveLocalParams(theta_free=0.35)
    extra_mu = 4.0
    cpu, ram = down_delta(
        _surplus_obs(
            sum_h_cpu=5.0 * 0.01 / 0.65 + extra_mu * 0.01,
            sum_h_ram=5.0 * 0.5 / 0.65 + extra_mu * 0.5,
        ),
        params,
    )
    assert cpu == pytest.approx(extra_mu * 0.01)
    assert ram == pytest.approx(extra_mu * 0.5)


def test_surplus_extras_at_floor_do_not_inject_leftover():
    params = ReactiveLocalParams(theta_free=0.35)
    cpu, ram = down_delta(_surplus_obs(replicas=[object(), object()], sum_h_cpu=0.0, sum_h_ram=0.0), params)
    assert cpu == pytest.approx(0.0)
    assert ram == pytest.approx(0.0)
