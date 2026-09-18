"""Unit tests for reactive_vertical (Step 4)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from hierarchical_edge_sim.autoscaler.reactive_vertical.params import validate_params
from hierarchical_edge_sim.autoscaler.reactive_vertical.policy import ReactiveVerticalAutoscaler, build
from hierarchical_edge_sim.env.api import Env, ResizeAction, ResizeResult, ResizeResultCode
from hierarchical_edge_sim.env.models import ContainerTickRecord


def test_params_defaults_validate():
    p = validate_params({})
    assert p.x_up_streak == 3
    assert p.y_down_streak == 8


def test_params_reject_bad_theta():
    with pytest.raises(ValueError, match="theta_free"):
        validate_params({"theta_free": 1.5})
    with pytest.raises(ValueError, match="alpha_up/alpha_down were removed"):
        validate_params({"alpha_down": 0.10})
    with pytest.raises(ValueError, match="min_mu_step"):
        validate_params({"delta_ram_min_mb": 128.0})


def _toy_env(tmp_path: Path) -> Env:
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
                            {
                                "id": "c-hot",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 512,
                            },
                            {
                                "id": "c-cold",
                                "server_id": "c1-w2",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 512,
                            },
                        ],
                    }
                ],
            }
        ],
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    rows = ["time_unit,requests"] + [f"{i},200" for i in range(1, 21)]
    (tdir / "api.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def _push_history(env: Env, tau: int, *, drop_hot: float, drop_cold: float = 0.0, q: float = 1.0):
    for cid, drop in (("c-hot", drop_hot), ("c-cold", drop_cold)):
        c = env.get_container(cid)
        served = 50.0
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


def test_aggregate_drop_streak_fires_up(tmp_path):
    env = _toy_env(tmp_path)
    scaler = build({"x_up_streak": 2, "y_down_streak": 5, "cooldown_ticks": 1}, decision_every_k_ticks=1)
    _push_history(env, 1, drop_hot=20.0, drop_cold=5.0)
    assert scaler.on_tick_end(env, 1) == []
    _push_history(env, 2, drop_hot=20.0, drop_cold=5.0)
    actions = scaler.on_tick_end(env, 2)
    resizes = [a for a in actions if getattr(a, "type", "") == "resize"]
    assert resizes
    assert resizes[0].container_id == "c-hot"  # hotter first


def test_slack_streak_fires_down(tmp_path):
    env = _toy_env(tmp_path)
    scaler = build(
        {
            "x_up_streak": 5,
            "y_down_streak": 2,
            "cooldown_ticks": 0,
            "theta_free": 0.35,
            "min_mu_step": 10.0,
        }
    )
    # Need alloc above min to shrink
    env.resize("c-hot", cpu_alloc_cores=2.0, ram_alloc_mb=1024)
    env.resize("c-cold", cpu_alloc_cores=2.0, ram_alloc_mb=1024)
    _push_history(env, 1, drop_hot=0.0, drop_cold=0.0, q=0.1)
    assert scaler.on_tick_end(env, 1) == []
    _push_history(env, 2, drop_hot=0.0, drop_cold=0.0, q=0.1)
    actions = scaler.on_tick_end(env, 2)
    assert any(getattr(a, "type", "") == "resize" and a.reason == "reactive_down" for a in actions)


def test_cooldown_suppresses(tmp_path):
    env = _toy_env(tmp_path)
    scaler = build({"x_up_streak": 1, "cooldown_ticks": 2, "y_down_streak": 99})
    _push_history(env, 1, drop_hot=30.0)
    actions = scaler.on_tick_end(env, 1)
    assert actions
    scaler.on_actions_applied(
        [ResizeResult(ok=True, code=ResizeResultCode.OK, container_id="c-hot", cpu_alloc_cores=1.2, ram_alloc_mb=512)]
    )
    _push_history(env, 2, drop_hot=30.0)
    assert scaler.on_tick_end(env, 2) == []  # cooldown


def test_all_rejected_keeps_streaks(tmp_path):
    env = _toy_env(tmp_path)
    scaler = build({"x_up_streak": 1, "cooldown_ticks": 5, "y_down_streak": 99})
    _push_history(env, 1, drop_hot=30.0)
    actions = scaler.on_tick_end(env, 1)
    assert actions
    scaler.on_actions_applied(
        [
            ResizeResult(
                ok=False,
                code=ResizeResultCode.SERVER_CPU_EXCEEDED,
                container_id="c-hot",
                cpu_alloc_cores=1.0,
                ram_alloc_mb=512,
            )
        ]
    )
    assert scaler._state["api"].u_streak >= 1
    assert scaler._state["api"].cooldown == 0


def test_decision_every_k_ticks_gates_emission(tmp_path):
    env = _toy_env(tmp_path)
    scaler = build({"x_up_streak": 1, "cooldown_ticks": 0, "y_down_streak": 99}, decision_every_k_ticks=2)
    _push_history(env, 1, drop_hot=30.0)
    assert scaler.on_tick_end(env, 1) == []  # odd τ gated
    assert scaler._state["api"].u_streak == 1
    _push_history(env, 2, drop_hot=30.0)
    assert scaler.on_tick_end(env, 2)  # even τ emits


def test_one_resize_per_container(tmp_path):
    env = _toy_env(tmp_path)
    scaler = build({"x_up_streak": 1, "cooldown_ticks": 0})
    _push_history(env, 1, drop_hot=100.0, drop_cold=100.0)
    actions = [a for a in scaler.on_tick_end(env, 1) if isinstance(a, ResizeAction)]
    ids = [a.container_id for a in actions]
    assert len(ids) == len(set(ids))


def test_drop_vetoes_down(tmp_path):
    env = _toy_env(tmp_path)
    scaler = build({"x_up_streak": 99, "y_down_streak": 1, "cooldown_ticks": 0, "theta_free": 0.01})
    env.resize("c-hot", cpu_alloc_cores=2.0)
    _push_history(env, 1, drop_hot=10.0, q=0.0)  # drops + would-be slack
    actions = scaler.on_tick_end(env, 1)
    assert not any(getattr(a, "reason", "") == "reactive_down" for a in actions)


def test_need_horizontal_logged_on_residual_room(tmp_path):
    env = _toy_env(tmp_path)
    # Max out both containers
    env.resize("c-hot", cpu_alloc_cores=4.0, ram_alloc_mb=4096)
    env.resize("c-cold", cpu_alloc_cores=4.0, ram_alloc_mb=4096)
    scaler = build({"x_up_streak": 1, "cooldown_ticks": 0, "min_mu_step": 100.0})
    _push_history(env, 1, drop_hot=500.0, drop_cold=500.0)
    actions = scaler.on_tick_end(env, 1)
    assert any(getattr(a, "type", "") == "need_horizontal" for a in actions)
    assert not any(
        getattr(a, "type", "") == "resize" and a.cpu_alloc_cores and a.cpu_alloc_cores > 4.0 + 1e-9
        for a in actions
    )
