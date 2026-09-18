"""S7: sensing, persistence forecast, and ladder driven by PredictAndDecide."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from hierarchical_edge_sim.autoscaler.common.load import load_autoscaler_from_yaml
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.forecast import forecast_horizon
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.params import validate_params
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.policy import build
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.persistence import (
    PersistencePredictor,
)
from hierarchical_edge_sim.env.api import Env, NeedVicinityHelpAction, ResizeResult, ResizeResultCode
from hierarchical_edge_sim.env.models import ContainerTickRecord


class _FixedPredictor:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict_next(self, x: list[float]) -> float:
        _ = x
        return self.value


def test_params_defaults_and_unknown_predictor():
    p = validate_params({})
    assert p.predictor == "persistence"
    assert p.feature_window == 10
    assert p.ladder.cascade_home is True
    assert p.cooldown_C == 3
    assert p.kappa_min == 0.5
    assert p.window_kappa is None
    with pytest.raises(ValueError, match="kappa_min"):
        validate_params({"kappa_min": 0.0})
    tcn = validate_params({"predictor": "tcn_delta", "feature_window": 60, "forecast_horizon": 5})
    assert tcn.cooldown_C == 5
    assert tcn.ticks_per_window == 1
    assert tcn.forecast_horizon == 5
    legacy = validate_params(
        {
            "ttw_ticks": 1,
            "horizon_H": 3,
            "sustained_tau": 4,
        }
    )
    assert legacy.ticks_per_window == 1
    assert legacy.forecast_horizon == 3
    assert legacy.sustained_steps == 4
    with pytest.raises(ValueError, match="hold_down_ticks was removed"):
        validate_params({"hold_down_ticks": 55})
    with pytest.raises(ValueError, match="predictor must be one of"):
        validate_params({"predictor": "lstm"})
    with pytest.raises(ValueError, match="feature_window=60"):
        validate_params({"predictor": "tcn_delta", "feature_window": 10, "forecast_horizon": 5})


def test_window_rps_conversion():
    from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.window_rps import (
        counts_to_rps,
        is_window_close,
        window_index,
    )

    assert counts_to_rps(120.0, ticks_per_window=2, tick_sec=1.0) == 60.0
    assert is_window_close(2, 2)
    assert not is_window_close(1, 2)
    assert window_index(2, 2) == 1


def test_forecast_horizon_does_not_mutate_history():
    x = [1.0, 2.0, 3.0]
    preds = forecast_horizon(x, 2, PersistencePredictor(), feature_window=3)
    assert x == [1.0, 2.0, 3.0]
    assert preds == [3.0, 3.0]


def _write_world(
    tmp_path: Path,
    *,
    w1_cpu: float = 8.0,
    w2_cpu: float = 8.0,
    cpu_max: float = 4.0,
    cpu_alloc: float = 1.0,
    ram_alloc: float = 512.0,
    ram_max: float = 2048.0,
) -> Env:
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
                        "containers": [
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": cpu_alloc,
                                "ram_alloc_mb": ram_alloc,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    (tdir / "api.csv").write_text(
        "time_unit,requests\n" + "\n".join(f"{i},10" for i in range(1, 11)) + "\n",
        encoding="utf-8",
    )
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def _push(env: Env, tau: int, *, incoming: float, drop: float = 0.0, q: float = 0.2) -> None:
    served = incoming - drop
    for cid in env.get_microservice("api").container_ids:
        c = env.get_container(cid)
        c.append_history(
            ContainerTickRecord(
                tau=tau,
                lambda_in=incoming,
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


def test_cold_start_uses_reactive_ladder(tmp_path: Path):
    env = _write_world(tmp_path, cpu_max=4.0, cpu_alloc=1.0)
    scaler = build(
        {
            "feature_window": 5,
            "x_up_streak": 1,
            "y_down_streak": 99,
            "cooldown_ticks": 0,
            "sustained_up_streak": 99,
        }
    )
    _push(env, 1, incoming=50.0, drop=40.0, q=1.0)
    actions = scaler.on_tick_end(env, 1)
    assert any(getattr(a, "type", "") == "resize" and a.reason == "vertical_up" for a in actions)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)


def test_horizon_spike_scales_up_without_drops(tmp_path: Path):
    env = _write_world(tmp_path, cpu_max=4.0, cpu_alloc=1.0)
    scaler = build(
        {
            "feature_window": 2,
            "forecast_horizon": 3,
            "sustained_steps": 99,
            "x_up_streak": 99,
            "y_down_streak": 99,
            "cooldown_ticks": 0,
            "sustained_up_streak": 99,
        },
        predictor=_FixedPredictor(100.0),
    )
    _push(env, 1, incoming=10.0, drop=0.0, q=0.1)
    assert scaler.on_tick_end(env, 1) == []
    _push(env, 2, incoming=10.0, drop=0.0, q=0.1)
    actions = scaler.on_tick_end(env, 2)
    assert any(getattr(a, "type", "") == "resize" and a.reason == "vertical_up" for a in actions)


def test_horizon_up_applies_full_residual(tmp_path: Path):
    env = _write_world(tmp_path, cpu_max=4.0, cpu_alloc=1.0)
    scaler = build(
        {
            "feature_window": 2,
            "forecast_horizon": 3,
            "sustained_steps": 99,
            "x_up_streak": 99,
            "y_down_streak": 99,
            "cooldown_ticks": 0,
            "delta_cpu_min_cores": 0.25,
        },
        predictor=_FixedPredictor(10_000.0),
    )
    _push(env, 1, incoming=10.0, drop=0.0, q=0.1)
    scaler.on_tick_end(env, 1)
    _push(env, 2, incoming=10.0, drop=0.0, q=0.1)
    actions = scaler.on_tick_end(env, 2)
    resizes = [a for a in actions if getattr(a, "reason", "") == "vertical_up"]
    assert resizes
    # Full residual, not α·alloc=0.20: grow the seed toward cpu_max.
    assert max(a.cpu_alloc_cores for a in resizes) == pytest.approx(4.0)


def test_cluster_full_still_escalates(tmp_path: Path):
    env = _write_world(
        tmp_path, cpu_max=1.0, cpu_alloc=1.0, ram_alloc=2048.0, ram_max=2048.0, w1_cpu=1.0, w2_cpu=0.4
    )
    scaler = build(
        {
            "feature_window": 2,
            "x_up_streak": 99,
            "y_down_streak": 99,
            "cooldown_ticks": 0,
            "sustained_up_streak": 1,
        },
        predictor=_FixedPredictor(100.0),
    )
    _push(env, 1, incoming=10.0, drop=0.0, q=0.1)
    scaler.on_tick_end(env, 1)
    _push(env, 2, incoming=10.0, drop=0.0, q=0.1)
    actions = scaler.on_tick_end(env, 2)
    assert not any(getattr(a, "type", "") == "spawn" for a in actions)
    assert any(isinstance(a, NeedVicinityHelpAction) for a in actions)


def test_cooldown_blocks_down_not_up(tmp_path: Path):
    env = _write_world(tmp_path, cpu_max=4.0, cpu_alloc=1.0)
    pred = _FixedPredictor(100.0)
    scaler = build(
        {
            "feature_window": 2,
            "forecast_horizon": 2,
            "cooldown_C": 2,
            "cooldown_ticks": 0,
            "x_up_streak": 99,
            "y_down_streak": 99,
            "sustained_steps": 99,
        },
        predictor=pred,
    )
    _push(env, 1, incoming=10.0, drop=0.0, q=0.1)
    scaler.on_tick_end(env, 1)
    _push(env, 2, incoming=10.0, drop=0.0, q=0.1)
    up = scaler.on_tick_end(env, 2)
    assert any(getattr(a, "reason", "") == "vertical_up" for a in up)
    applied = [
        ResizeResult(
            ok=True,
            code=ResizeResultCode.OK,
            container_id="c-api-1",
            cpu_alloc_cores=1.2,
            ram_alloc_mb=512.0,
        )
    ]
    scaler.on_actions_applied(applied)
    pred.value = 0.01
    _push(env, 3, incoming=5.0, drop=0.0, q=0.0)
    blocked = scaler.on_tick_end(env, 3)
    assert not any(getattr(a, "reason", "") == "vertical_down" for a in blocked)
    _push(env, 4, incoming=5.0, drop=0.0, q=0.0)
    still_blocked = scaler.on_tick_end(env, 4)
    assert not any(getattr(a, "reason", "") == "vertical_down" for a in still_blocked)
    _push(env, 5, incoming=5.0, drop=0.0, q=0.0)
    released = scaler.on_tick_end(env, 5)
    assert any(getattr(a, "reason", "") == "vertical_down" for a in released)


def test_scale_up_ignores_cooldown(tmp_path: Path):
    env = _write_world(tmp_path, cpu_max=4.0, cpu_alloc=1.0)
    scaler = build(
        {
            "feature_window": 2,
            "forecast_horizon": 2,
            "cooldown_C": 5,
            "cooldown_ticks": 0,
            "x_up_streak": 99,
            "y_down_streak": 99,
            "sustained_steps": 99,
            "kappa_min": 0.01,
        },
        predictor=_FixedPredictor(100.0),
    )
    _push(env, 1, incoming=10.0, drop=0.0, q=0.1)
    scaler.on_tick_end(env, 1)
    _push(env, 2, incoming=10.0, drop=0.0, q=0.1)
    first = scaler.on_tick_end(env, 2)
    assert any(getattr(a, "reason", "") == "vertical_up" for a in first)
    scaler.on_actions_applied(
        [
            ResizeResult(
                ok=True,
                code=ResizeResultCode.OK,
                container_id="c-api-1",
                cpu_alloc_cores=1.2,
                ram_alloc_mb=512.0,
            )
        ]
    )
    _push(env, 3, incoming=10.0, drop=0.0, q=0.1)
    second = scaler.on_tick_end(env, 3)
    assert any(getattr(a, "reason", "") == "vertical_up" for a in second)


def test_low_kappa_ignores_horizon_spike(tmp_path: Path):
    """Paper: κ < κ_min → ignore hats and decide on current λ."""
    env = _write_world(tmp_path, cpu_max=4.0, cpu_alloc=1.0)
    scaler = build(
        {
            "feature_window": 2,
            "forecast_horizon": 3,
            "sustained_steps": 99,
            "x_up_streak": 99,
            "y_down_streak": 99,
            "cooldown_ticks": 0,
            "kappa_min": 0.5,
        },
        predictor=_FixedPredictor(100.0),
    )
    _push(env, 1, incoming=10.0, drop=0.0, q=0.1)
    scaler.on_tick_end(env, 1)
    _push(env, 2, incoming=10.0, drop=0.0, q=0.1)
    first = scaler.on_tick_end(env, 2)
    assert any(getattr(a, "reason", "") == "vertical_up" for a in first)
    scaler.on_actions_applied(
        [
            ResizeResult(
                ok=True,
                code=ResizeResultCode.OK,
                container_id="c-api-1",
                cpu_alloc_cores=1.2,
                ram_alloc_mb=512.0,
            )
        ]
    )
    _push(env, 3, incoming=10.0, drop=0.0, q=0.1)
    second = scaler.on_tick_end(env, 3)
    assert not any(getattr(a, "reason", "") == "vertical_up" for a in second)
    assert scaler._sensing is not None
    assert scaler._sensing._confidence["api"].kappa() < 0.5


def test_scale_down_can_repeat_without_rearming_cooldown(tmp_path: Path):
    env = _write_world(tmp_path, cpu_max=4.0, cpu_alloc=1.0)
    pred = _FixedPredictor(100.0)
    scaler = build(
        {
            "feature_window": 2,
            "forecast_horizon": 2,
            "cooldown_C": 2,
            "cooldown_ticks": 0,
            "x_up_streak": 99,
            "y_down_streak": 99,
            "sustained_steps": 99,
        },
        predictor=pred,
    )
    _push(env, 1, incoming=10.0, drop=0.0, q=0.1)
    scaler.on_tick_end(env, 1)
    _push(env, 2, incoming=10.0, drop=0.0, q=0.1)
    up = scaler.on_tick_end(env, 2)
    assert any(getattr(a, "reason", "") == "vertical_up" for a in up)
    scaler.on_actions_applied(
        [
            ResizeResult(
                ok=True,
                code=ResizeResultCode.OK,
                container_id="c-api-1",
                cpu_alloc_cores=1.2,
                ram_alloc_mb=512.0,
            )
        ]
    )
    pred.value = 0.01
    _push(env, 3, incoming=5.0, drop=0.0, q=0.0)
    assert not any(getattr(a, "reason", "") == "vertical_down" for a in scaler.on_tick_end(env, 3))
    _push(env, 4, incoming=5.0, drop=0.0, q=0.0)
    assert not any(getattr(a, "reason", "") == "vertical_down" for a in scaler.on_tick_end(env, 4))
    _push(env, 5, incoming=5.0, drop=0.0, q=0.0)
    first_down = scaler.on_tick_end(env, 5)
    assert any(getattr(a, "reason", "") == "vertical_down" for a in first_down)
    scaler.on_actions_applied(
        [
            ResizeResult(
                ok=True,
                code=ResizeResultCode.OK,
                container_id="c-api-1",
                cpu_alloc_cores=0.8,
                ram_alloc_mb=512.0,
            )
        ]
    )
    _push(env, 6, incoming=5.0, drop=0.0, q=0.0)
    second_down = scaler.on_tick_end(env, 6)
    assert any(getattr(a, "reason", "") == "vertical_down" for a in second_down)


def test_yaml_loads_proactive(tmp_path: Path, project_root: Path):
    scaler = load_autoscaler_from_yaml(project_root / "configs" / "11-demo_60_proactive.yaml")
    assert scaler is not None
    assert scaler.name == "proactive_auto_scaler"
    assert scaler.cycle == "cluster_manager"
    assert scaler.decide == "predict_and_decide"
    assert scaler.allocate == "allocate_resources"
    assert scaler.params.predictor == "persistence"
    from hierarchical_edge_sim.env.api import _autoscaler_meta

    meta = _autoscaler_meta(scaler)
    assert meta["decide"] == "predict_and_decide"
    assert meta["cycle"] == "cluster_manager"
    assert meta["allocate"] == "allocate_resources"
    _ = tmp_path


def test_yaml_loads_alibaba_tcn(project_root: Path):
    pytest.importorskip("torch")
    scaler = load_autoscaler_from_yaml(project_root / "configs" / "13-demo_alibaba_proactive.yaml")
    assert scaler is not None
    assert scaler.params.predictor == "tcn_delta"
    assert scaler.params.feature_window == 60
    assert scaler.params.forecast_horizon == 5
    assert scaler.params.cooldown_C == 5


def test_yaml_loads_alibaba_ms150_tcn(project_root: Path):
    pytest.importorskip("torch")
    from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.tcn import (
        TcnDeltaPredictor,
    )

    scaler = load_autoscaler_from_yaml(project_root / "configs" / "15-demo_alibaba_ms150_proactive.yaml")
    assert scaler is not None
    assert scaler.params.predictor == "tcn_delta"
    assert scaler.params.model_dir == "models/tcn_delta_v1_ms150"
    assert scaler.params.cooldown_C == 5
    pred = TcnDeltaPredictor.from_model_dir(project_root / scaler.params.model_dir)
    assert pred.load_min == 240.0
    assert pred.load_max == 40083.0
