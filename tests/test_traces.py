from pathlib import Path

import pytest

from hierarchical_edge_sim.env.config import load_yaml
from hierarchical_edge_sim.env.traces import load_traces
from hierarchical_edge_sim.env.validate import validate_or_raise


def _load_store(tiny_config_path):
    raw = load_yaml(tiny_config_path)
    spec = validate_or_raise(raw)
    return load_traces(spec)


def test_load_demo_trace(tiny_config_path):
    store = _load_store(tiny_config_path)
    assert store.horizon == 5
    assert store.get("api", 4) == 120.0


def test_get_tau_one_based(tiny_config_path):
    store = _load_store(tiny_config_path)
    assert store.get("api", 1) == 0.0
    assert store.get("api", 2) == 25.0
    assert store.get("api", 5) == 50.0


def test_get_unknown_ms_raises_key_error(tiny_config_path):
    store = _load_store(tiny_config_path)
    with pytest.raises(KeyError):
        store.get("missing-ms", 1)


def test_get_tau_out_of_range_raises_index_error(tiny_config_path):
    store = _load_store(tiny_config_path)
    with pytest.raises(IndexError):
        store.get("api", 0)
    with pytest.raises(IndexError):
        store.get("api", 6)


def _single_ms_world_spec(traces_dir: Path, source_path: Path):
    from hierarchical_edge_sim.env.config import AppSpec, MicroserviceSpec, SimConfig, WorldSpec

    return WorldSpec(
        sim=SimConfig(tick_sec=1.0, results_dir="results/", seed=1),
        traces_dir=str(traces_dir),
        clusters=[],
        apps=[
            AppSpec(
                id="demo_app",
                microservices=[
                    MicroserviceSpec(
                        id="api",
                        cpu_min_cores=0.5,
                        cpu_max_cores=4.0,
                        ram_min_mb=256.0,
                        ram_max_mb=4096.0,
                        cpu_per_request_cores=0.01,
                        ram_per_request_mb=0.5,
                        trace_file="api.csv",
                        containers=[],
                    )
                ],
            )
        ],
        source_path=source_path,
    )


def test_load_traces_rejects_blank_line_instead_of_silently_misaligning(tmp_path):
    """Regression guard for a validate/load parser mismatch.

    `csv.DictReader` (previously used by `_read_requests_column`) silently
    *skips* blank rows anywhere in a file, while `validate.py`'s trace
    checker uses `csv.reader` and would flag a blank row as malformed. If
    `load_traces()` is ever reached on data that bypassed (or diverged from)
    `validate()`, the old DictReader-based loader would have silently
    shifted every row after the blank line by one tau -- e.g. `get("api",
    3)` silently returning the row meant for tau=4. `load_traces` must now
    fail loudly instead.
    """
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    (trace_dir / "api.csv").write_text(
        "time_unit,requests\n1,0\n2,25\n\n3,80\n", encoding="utf-8"
    )
    spec = _single_ms_world_spec(trace_dir, tmp_path / "config.yaml")

    with pytest.raises(ValueError, match="expected 2 columns"):
        load_traces(spec)


def test_load_traces_rejects_unexpected_header(tmp_path):
    trace_dir = tmp_path / "traces"
    trace_dir.mkdir()
    (trace_dir / "api.csv").write_text("tick,requests\n1,0\n", encoding="utf-8")
    spec = _single_ms_world_spec(trace_dir, tmp_path / "config.yaml")

    with pytest.raises(ValueError, match="unexpected header"):
        load_traces(spec)
