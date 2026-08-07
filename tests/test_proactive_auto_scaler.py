"""Unit tests for proactive_auto_scaler Step 1 building blocks."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
import yaml

from hierarchical_edge_sim.autoscaler.common.load import load_autoscaler_from_yaml
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.forecast import forecast_horizon
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.history import RpsHistory
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.params import (
    ProactiveAutoScalerParams,
    validate_params,
)
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.policy import ProactiveAutoScaler
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.ttw_rps import (
    counts_to_rps,
    is_ttw_close,
    ttw_index,
)
from hierarchical_edge_sim.env.api import Env


def test_load_proactive_auto_scaler(tmp_path: Path):
    # build() always constructs the real LSTM predictor now (no more "average"
    # fallback), so feature_window here must match the installed default model
    # bundle's meta.json; skip if that bundle isn't present.
    pytest.importorskip("torch")
    pytest.importorskip("sklearn")
    pytest.importorskip("joblib")
    from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.lstm_torch import (
        default_model_dir,
    )

    if not (default_model_dir() / "lstm_edge_weights.pth").is_file():
        pytest.skip("LSTM artifacts not present under models/rps_lstm_v1")

    cfg = {
        "sim": {"tick_sec": 1.0, "results_dir": "results/", "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {"clusters": [{"id": "c1", "servers": [{"id": "s1", "cpu_cap_cores": 1, "ram_cap_mb": 1}]}]},
        "apps": [],
        "autoscaler": {
            "enabled": True,
            "name": "proactive_auto_scaler",
            "params": {"ttw_ticks": 2, "feature_window": 10, "horizon_H": 3},
        },
    }
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    scaler = load_autoscaler_from_yaml(path)
    assert scaler is not None
    assert scaler.name == "proactive_auto_scaler"
    assert scaler.params.ttw_ticks == 2
    assert scaler.params.feature_window == 10
    assert scaler.params.horizon_H == 3


def test_validate_params_rejects_unknown():
    with pytest.raises(ValueError, match="unknown"):
        validate_params({"ttw_ticks": 1, "not_a_real_knob": 3})


def test_validate_params_accepts_decide_knobs():
    p = validate_params(
        {
            "ttw_ticks": 60,
            "feature_window": 10,
            "theta_up": 0.85,
            "theta_down": 0.25,
            "theta_target": 0.55,
            "sustained_tau": 2,
            "cooldown_C": 3,
        }
    )
    assert p.ttw_ticks == 60
    assert p.feature_window == 10
    assert p.cooldown_C == 3
    assert p.theta_up == 0.85


def test_validate_params_rejects_bad_theta_order():
    with pytest.raises(ValueError, match="theta"):
        validate_params({"theta_up": 0.5, "theta_target": 0.6, "theta_down": 0.3})


def test_legacy_window_W_alias():
    p = validate_params({"window_W": 12, "horizon_H": 2})
    assert p.feature_window == 12


def test_counts_to_rps_and_ttw_close():
    assert counts_to_rps(10.0, ttw_ticks=2, tick_sec=1.0) == 5.0
    assert is_ttw_close(2, 2)
    assert not is_ttw_close(1, 2)
    assert ttw_index(4, 2) == 2


def test_history_slides_and_rejects_overfill_conceptually():
    h = RpsHistory(3)
    h.append(1.0)
    h.append(2.0)
    h.append(3.0)
    assert h.is_full()
    h.append(4.0)
    assert h.as_list() == [2.0, 3.0, 4.0]


class _MeanPredictor:
    """Test double: predict_next(x) = mean(x). Used to check forecast_horizon's algorithm
    in isolation from the real LSTM predictor."""

    def predict_next(self, x: list[float]) -> float:
        return sum(x) / len(x)


def test_forecast_horizon_purity_and_constant_mean():
    pred = _MeanPredictor()
    x = [10.0, 10.0, 10.0, 10.0]
    x_before = list(x)
    out = forecast_horizon(x, 3, pred, feature_window=4)
    assert x == x_before
    assert out == [10.0, 10.0, 10.0]


def _write_two_container_env(tmp_path: Path, *, n_ticks: int, results_dir: Path) -> Path:
    traces = tmp_path / "traces"
    traces.mkdir()
    # Constant 10 requests/tick offered to the MS.
    rows = ["time_unit,requests"] + [f"{t},10" for t in range(1, n_ticks + 1)]
    (traces / "api.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    cfg = {
        "sim": {"tick_sec": 1.0, "results_dir": str(results_dir), "seed": 7},
        "traces_dir": str(traces),
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [
                        {"id": "s1", "cpu_cap_cores": 8.0, "ram_cap_mb": 8192},
                        {"id": "s2", "cpu_cap_cores": 8.0, "ram_cap_mb": 8192},
                    ],
                }
            ]
        },
        "apps": [
            {
                "id": "app",
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
                                "id": "c1",
                                "server_id": "s1",
                                "cpu_alloc_cores": 2.0,
                                "ram_alloc_mb": 1024,
                            },
                            {
                                "id": "c2",
                                "server_id": "s2",
                                "cpu_alloc_cores": 2.0,
                                "ram_alloc_mb": 1024,
                            },
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_policy_long_log_warmup_then_forecast(tmp_path: Path):
    # Uses a plain mean-predictor test double so this policy-logic test does not
    # depend on torch/sklearn or a trained LSTM bundle (see the dedicated
    # test_policy_lstm_writes_forecast_rows below for the real predictor).
    results = tmp_path / "results"
    results.mkdir()
    cfg = _write_two_container_env(tmp_path, n_ticks=12, results_dir=results)
    env = Env.from_config(cfg)
    scaler = ProactiveAutoScaler(
        params=ProactiveAutoScalerParams(ttw_ticks=1, feature_window=5, horizon_H=3),
        _predictor=_MeanPredictor(),
    )
    env.run(autoscaler=scaler, now_utc=None)

    obs = [r for r in scaler.rps_forecast_log if r.lead == 0 and r.ms_id == "api"]
    assert len(obs) == 12
    # First 4 TTWs: no forecasts yet (need feature_window=5)
    for t in range(1, 5):
        frows = [r for r in scaler.rps_forecast_log if r.ttw == t and r.lead >= 1]
        assert frows == []
    # From ttw=5 onward: H forecast rows
    for t in range(5, 13):
        frows = sorted(
            [r for r in scaler.rps_forecast_log if r.ttw == t and r.ms_id == "api" and r.lead >= 1],
            key=lambda r: r.lead,
        )
        assert [r.lead for r in frows] == [1, 2, 3]
        assert [r.target_ttw for r in frows] == [t + 1, t + 2, t + 3]
        assert all(r.forecast_ready and r.r_hat is not None for r in frows)

    # Constant offer 10 req/tick, tick_sec=1 → r_t ≈ 10
    assert obs[0].r_t == pytest.approx(10.0)


def test_rps_forecast_csv_flushed(tmp_path: Path):
    from datetime import UTC, datetime

    results = tmp_path / "out"
    results.mkdir()
    cfg = _write_two_container_env(tmp_path, n_ticks=8, results_dir=results)
    env = Env.from_config(cfg)
    scaler = ProactiveAutoScaler(
        params=ProactiveAutoScalerParams(ttw_ticks=1, feature_window=3, horizon_H=2, theta_down=0.05),
        _predictor=_MeanPredictor(),
    )
    run_dir = env.run(autoscaler=scaler, now_utc=datetime(2026, 1, 1, tzinfo=UTC))

    path = run_dir / "rps_forecast.csv"
    assert path.is_file()
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert rows
    assert set(rows[0].keys()) >= {
        "tau",
        "ttw",
        "ms_id",
        "lead",
        "target_ttw",
        "r_t",
        "r_hat",
        "history_len",
        "forecast_ready",
    }
    lead0 = [r for r in rows if r["lead"] == "0"]
    assert len(lead0) == 8
    # Decide may emit resizes once history is full; this test only locks forecast CSV.


def test_no_actions_leave_alloc_unchanged(tmp_path: Path):
    """With mid-band thresholds and light load, expect no vertical moves."""
    results = tmp_path / "out2"
    results.mkdir()
    cfg = _write_two_container_env(tmp_path, n_ticks=6, results_dir=results)
    env = Env.from_config(cfg)
    # Raise alloc so RPS util and typical q stay below theta_up and above theta_down.
    env.resize("c1", cpu_alloc_cores=3.0, ram_alloc_mb=2048)
    env.resize("c2", cpu_alloc_cores=3.0, ram_alloc_mb=2048)
    before = {cid: (c.cpu_alloc_cores, c.ram_alloc_mb) for cid, c in env.world.containers.items()}
    scaler = ProactiveAutoScaler(
        params=ProactiveAutoScalerParams(
            ttw_ticks=1,
            feature_window=3,
            horizon_H=2,
            theta_up=0.95,
            theta_down=0.01,
            theta_target=0.50,
            cooldown_C=0,
        ),
        _predictor=_MeanPredictor(),
    )
    env.run(autoscaler=scaler)
    after = {cid: (c.cpu_alloc_cores, c.ram_alloc_mb) for cid, c in env.world.containers.items()}
    assert before == after


def test_lstm_predict_next_minmax_roundtrip():
    torch = pytest.importorskip("torch")
    _ = torch
    pytest.importorskip("sklearn")
    pytest.importorskip("joblib")

    from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.lstm_torch import (
        build_lstm_predictor,
        default_model_dir,
    )

    model_dir = default_model_dir()
    if not (model_dir / "lstm_edge_weights.pth").is_file():
        pytest.skip("LSTM artifacts not present under models/rps_lstm_v1")

    pred = build_lstm_predictor(feature_window=10)
    x = [400.0 + 10.0 * i for i in range(10)]
    y = pred.predict_next(x)
    assert isinstance(y, float)
    assert y >= 0.0
    assert y == pytest.approx(y)  # finite

    # Wrong window length
    with pytest.raises(ValueError, match="feature_window"):
        pred.predict_next(x[:5])

    # feature_window must match meta.json
    with pytest.raises(ValueError, match="does not match"):
        build_lstm_predictor(feature_window=5)


def test_policy_lstm_writes_forecast_rows(tmp_path: Path):
    pytest.importorskip("torch")
    pytest.importorskip("sklearn")
    pytest.importorskip("joblib")

    from hierarchical_edge_sim.autoscaler.proactive_auto_scaler import build
    from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.predictors.lstm_torch import (
        default_model_dir,
    )

    model_dir = default_model_dir()
    if not (model_dir / "lstm_edge_weights.pth").is_file():
        pytest.skip("LSTM artifacts not present under models/rps_lstm_v1")

    results = tmp_path / "lstm_out"
    results.mkdir()
    cfg = _write_two_container_env(tmp_path, n_ticks=12, results_dir=results)
    env = Env.from_config(cfg)
    scaler = build(
        {
            "ttw_ticks": 1,
            "feature_window": 10,
            "horizon_H": 3,
            "model_path": str(model_dir / "lstm_edge_weights.pth"),
            "scaler_path": str(model_dir / "traffic_scaler.pkl"),
            "meta_path": str(model_dir / "meta.json"),
        }
    )
    env.run(autoscaler=scaler, now_utc=None)

    frows = [r for r in scaler.rps_forecast_log if r.lead >= 1 and r.ms_id == "api"]
    assert len(frows) == 3 * (12 - 10 + 1)  # from ttw 10..12
    assert all(r.r_hat is not None and r.r_hat >= 0.0 for r in frows)
