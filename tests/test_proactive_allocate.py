"""Integration: proactive decide+allocate emits paired resizes after warm-up."""

from __future__ import annotations

from pathlib import Path

import yaml

from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.params import ProactiveAutoScalerParams
from hierarchical_edge_sim.autoscaler.proactive_auto_scaler.policy import ProactiveAutoScaler
from hierarchical_edge_sim.env.api import Env


class _HighPredictor:
    """Always predicts a high RPS so decide stays UP after warm-up."""

    def predict_next(self, x: list[float]) -> float:
        return 200.0


class _LowPredictor:
    def predict_next(self, x: list[float]) -> float:
        return 1.0


def _cfg(tmp_path: Path, *, n_ticks: int, offer: int, cpu_alloc: float, ram_alloc: float) -> Path:
    traces = tmp_path / "traces"
    traces.mkdir(exist_ok=True)
    rows = ["time_unit,requests"] + [f"{t},{offer}" for t in range(1, n_ticks + 1)]
    (traces / "api.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    cfg = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": str(traces),
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [{"id": "s1", "cpu_cap_cores": 8.0, "ram_cap_mb": 16384}],
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
                                "cpu_alloc_cores": cpu_alloc,
                                "ram_alloc_mb": ram_alloc,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_no_actions_before_history_full(tmp_path: Path):
    cfg = _cfg(tmp_path, n_ticks=4, offer=50, cpu_alloc=0.5, ram_alloc=256)
    env = Env.from_config(cfg)
    scaler = ProactiveAutoScaler(
        params=ProactiveAutoScalerParams(
            ttw_ticks=1,
            feature_window=5,
            horizon_H=2,
            cooldown_C=0,
        ),
        _predictor=_HighPredictor(),
    )
    env.run(autoscaler=scaler)
    assert not any(r.action_type == "resize" for r in env.action_log)


def test_scale_up_after_warmup(tmp_path: Path):
    cfg = _cfg(tmp_path, n_ticks=12, offer=80, cpu_alloc=0.5, ram_alloc=256)
    env = Env.from_config(cfg)
    scaler = ProactiveAutoScaler(
        params=ProactiveAutoScalerParams(
            ttw_ticks=1,
            feature_window=3,
            horizon_H=2,
            cooldown_C=0,
            theta_up=0.80,
            theta_down=0.30,
            theta_target=0.60,
        ),
        _predictor=_HighPredictor(),
    )
    before = env.get_container("c1").cpu_alloc_cores
    env.run(autoscaler=scaler)
    after = env.get_container("c1").cpu_alloc_cores
    ups = [r for r in env.action_log if r.action_type == "resize" and r.reason == "proactive_up"]
    assert ups, "expected proactive_up resize"
    assert after > before
    # RAM residual may be 0 when already sufficient for r★; CPU growth is enough here
    assert env.get_container("c1").ram_alloc_mb >= 256.0


def test_import_independence():
    import hierarchical_edge_sim.autoscaler.proactive_auto_scaler as pro
    import inspect

    src = inspect.getsource(pro.policy) + inspect.getsource(pro.allocate) + inspect.getsource(pro.decide)
    assert "reactive_vertical" not in src
