"""Tests for autoscaler YAML load / supported list (Step 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hierarchical_edge_sim.autoscaler.common.load import AutoscalerLoadError, load_autoscaler_from_yaml
from hierarchical_edge_sim.autoscaler.common.params_base import parse_wrapper


def _write_cfg(tmp_path: Path, autoscaler: dict | None) -> Path:
    cfg = {
        "sim": {"tick_sec": 1.0, "results_dir": "results/", "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {"clusters": [{"id": "c1", "servers": [{"id": "s1", "cpu_cap_cores": 1, "ram_cap_mb": 1}]}]},
        "apps": [],
    }
    if autoscaler is not None:
        cfg["autoscaler"] = autoscaler
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_missing_block_returns_none(tmp_path):
    assert load_autoscaler_from_yaml(_write_cfg(tmp_path, None)) is None


def test_disabled_returns_none(tmp_path):
    assert load_autoscaler_from_yaml(_write_cfg(tmp_path, {"enabled": False})) is None


def test_unknown_name_raises(tmp_path):
    with pytest.raises(AutoscalerLoadError, match="unknown autoscaler"):
        load_autoscaler_from_yaml(
            _write_cfg(tmp_path, {"enabled": True, "name": "not_a_scaler", "params": {}})
        )


def test_wrapper_requires_name_when_enabled():
    with pytest.raises(ValueError, match="name"):
        parse_wrapper({"enabled": True, "params": {}})


def test_decision_every_k_ticks_defaults_to_one(tmp_path):
    scaler = load_autoscaler_from_yaml(
        _write_cfg(tmp_path, {"enabled": True, "name": "reactive_vertical", "params": {}})
    )
    assert scaler is not None
    assert scaler.decision_every_k_ticks == 1


def test_env_does_not_import_autoscaler_package():
    import hierarchical_edge_sim.env.api as env_api
    import hierarchical_edge_sim.env.engine as env_engine

    assert "hierarchical_edge_sim.autoscaler" not in (env_api.__name__ and "")
    # No import of the autoscaler package from env modules
    import ast

    for mod in (env_api, env_engine):
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "autoscaler" not in alias.name
            if isinstance(node, ast.ImportFrom) and node.module:
                assert "autoscaler" not in node.module


def test_config_tolerates_autoscaler_block_for_env_load(tmp_path, project_root):
    # Env load_yaml ignores unknown top-level autoscaler; validate still works on tiny+block
    from copy import deepcopy

    from hierarchical_edge_sim.env.config import load_yaml

    tiny = yaml.safe_load((project_root / "configs" / "tiny.yaml").read_text(encoding="utf-8"))
    tiny = deepcopy(tiny)
    tiny["autoscaler"] = {"enabled": True, "name": "reactive_vertical", "params": {"x_up_streak": 3}}
    # Rewrite with traces relative to project - use real tiny path by patching via write under project style
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    traces = cfg_dir / "traces" / "demo"
    traces.mkdir(parents=True)
    (traces / "api.csv").write_text(
        (project_root / "traces" / "demo" / "api.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    tiny["traces_dir"] = "traces/demo/"
    path = cfg_dir / "tiny.yaml"
    path.write_text(yaml.safe_dump(tiny), encoding="utf-8")
    raw = load_yaml(path)
    assert raw.sim.seed == 42
    # no autoscaler field on RawConfig — ignored
    assert not hasattr(raw, "autoscaler") or getattr(raw, "autoscaler", None) in (None, [], ())
