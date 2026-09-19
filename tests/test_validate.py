from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from hierarchical_edge_sim.env.config import load_yaml
from hierarchical_edge_sim.env.validate import ConfigError, validate, validate_or_raise


def _tiny_dict() -> dict[str, Any]:
    return {
        "sim": {"tick_sec": 1.0, "results_dir": "results/", "seed": 42},
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
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 512,
                            }
                        ],
                    }
                ],
            }
        ],
    }


def _write_config_tree(tmp_path: Path, config_data: dict[str, Any], traces: dict[str, str]) -> Path:
    config_dir = tmp_path / "config_root"
    trace_dir = config_dir / "traces" / "demo"
    trace_dir.mkdir(parents=True, exist_ok=True)

    for fname, content in traces.items():
        (trace_dir / fname).write_text(content, encoding="utf-8")

    config_path = config_dir / "00-tiny.yaml"
    config_path.write_text(yaml.safe_dump(config_data, sort_keys=False), encoding="utf-8")
    return config_path


VALID_TRACE = "time_unit,requests\n1,0\n2,25\n3,80\n4,120\n5,50\n"


def _build_and_validate(
    tmp_path: Path,
    mutate: Callable[[dict[str, Any], dict[str, str]], None],
) -> list[str]:
    config_data = deepcopy(_tiny_dict())
    traces = {"api.csv": VALID_TRACE}
    mutate(config_data, traces)
    config_path = _write_config_tree(tmp_path, config_data, traces)
    raw = load_yaml(config_path)
    return [err.message for err in validate(raw)]


def test_tiny_yaml_validates_clean(tiny_config_path):
    raw = load_yaml(tiny_config_path)
    world_spec = validate_or_raise(raw)
    assert world_spec.sim.seed == 42
    assert world_spec.sim.sla_timeout_sec == 1.0
    assert world_spec.clusters[0].id == "c1"


def test_validate_or_raise_raises_config_error(tmp_path):
    def mutate(config_data: dict[str, Any], _traces: dict[str, str]) -> None:
        config_data["sim"]["tick_sec"] = 0

    config_path = _write_config_tree(tmp_path, _tiny_dict(), {"api.csv": VALID_TRACE})
    raw = load_yaml(config_path)
    raw_bad = raw
    # mutate by rebuilding from dict so structure remains parser-valid
    cfg = _tiny_dict()
    mutate(cfg, {"api.csv": VALID_TRACE})
    raw_bad = load_yaml(_write_config_tree(tmp_path / "bad", cfg, {"api.csv": VALID_TRACE}))

    with pytest.raises(ConfigError):
        validate_or_raise(raw_bad)


@pytest.mark.parametrize(
    ("name", "mutate", "expected_substring"),
    [
        (
            "unique_ids",
            lambda cfg, _t: cfg["topology"]["clusters"][0]["servers"].append(
                {"id": "c1-w1", "cpu_cap_cores": 2.0, "ram_cap_mb": 1024}
            ),
            "duplicate server id",
        ),
        ("non_empty_world", lambda cfg, _t: cfg.update({"apps": []}), "must contain at least one app"),
        (
            "ms_coverage",
            lambda cfg, _t: cfg["apps"][0]["microservices"][0].update({"containers": []}),
            "microservice must contain at least one container",
        ),
        (
            "app_coverage",
            lambda cfg, _t: cfg["apps"][0].update({"microservices": []}),
            "app must contain at least one microservice",
        ),
        (
            "cluster_coverage",
            lambda cfg, _t: cfg["topology"]["clusters"][0].update({"servers": []}),
            "cluster must contain at least one server",
        ),
        (
            "references",
            lambda cfg, _t: cfg["apps"][0]["microservices"][0]["containers"][0].update({"server_id": "ghost-server"}),
            "unknown server_id",
        ),
        (
            "cluster_membership",
            lambda cfg, _t: cfg["apps"][0]["microservices"][0]["containers"][0].update({"server_id": "ghost-server"}),
            "must belong to a server listed under some cluster",
        ),
        (
            "server_caps",
            lambda cfg, _t: cfg["topology"]["clusters"][0]["servers"][0].update({"cpu_cap_cores": 0}),
            "must be > 0",
        ),
        (
            "ms_coeffs",
            lambda cfg, _t: cfg["apps"][0]["microservices"][0].update({"cpu_per_request_cores": 0}),
            "must be > 0",
        ),
        (
            "container_alloc",
            lambda cfg, _t: cfg["apps"][0]["microservices"][0]["containers"][0].update({"cpu_alloc_cores": 9.0}),
            "must be <= cpu_max_cores",
        ),
        (
            "server_packing",
            lambda cfg, _t: cfg["apps"][0]["microservices"][0]["containers"].append(
                {"id": "c-api-2", "server_id": "c1-w1", "cpu_alloc_cores": 8.0, "ram_alloc_mb": 512}
            ),
            "exceeds cpu_cap_cores",
        ),
        ("traces_dir", lambda cfg, _t: cfg.update({"traces_dir": "traces/missing/"}), "directory not found"),
        (
            "trace_files",
            lambda cfg, _t: cfg["apps"][0]["microservices"][0].update({"trace_file": "missing.csv"}),
            "file not found",
        ),
        (
            "trace_length",
            lambda cfg, traces: (
                cfg["apps"][0]["microservices"].append(
                    {
                        "id": "api2",
                        "cpu_min_cores": 0.5,
                        "cpu_max_cores": 4.0,
                        "ram_min_mb": 256,
                        "ram_max_mb": 4096,
                        "cpu_per_request_cores": 0.01,
                        "ram_per_request_mb": 0.5,
                        "trace_file": "api2.csv",
                        "containers": [
                            {
                                "id": "c-api-2",
                                "server_id": "c1-w2",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 512,
                            }
                        ],
                    }
                ),
                traces.update({"api2.csv": "time_unit,requests\n1,0\n2,10\n"}),
            ),
            "equal data row counts",
        ),
        (
            "trace_header",
            lambda _cfg, traces: traces.update({"api.csv": "tick,requests\n1,0\n2,25\n"}),
            "header must be exactly",
        ),
        (
            "trace_time_unit",
            lambda _cfg, traces: traces.update({"api.csv": "time_unit,requests\n1,0\n3,25\n"}),
            "must equal 2, got 3",
        ),
        (
            "trace_values",
            lambda _cfg, traces: traces.update({"api.csv": "time_unit,requests\n1,-1\n2,25\n"}),
            "must be >= 0",
        ),
        (
            "trace_values_nan",
            # `req_val < 0` alone is False for NaN (IEEE-754: every comparison
            # with NaN is False), so a naive check would silently accept this.
            lambda _cfg, traces: traces.update({"api.csv": "time_unit,requests\n1,nan\n2,25\n"}),
            "non-finite",
        ),
        (
            "sim",
            lambda cfg, _t: cfg["sim"].update({"results_dir": "   "}),
            "must be a non-empty string",
        ),
        (
            "sla_timeout",
            lambda cfg, _t: cfg["sim"].update({"sla_timeout_sec": 0}),
            "must be > 0",
        ),
        (
            "theta_route",
            lambda cfg, _t: cfg["sim"].update({"theta_route": 0}),
            "must be in (0, 1]",
        ),
    ],
)
def test_reject_rules(name, mutate, expected_substring, tmp_path):
    messages = _build_and_validate(tmp_path / name, mutate)
    assert messages, f"expected validation errors for case: {name}"
    assert any(expected_substring in msg for msg in messages), (
        f"expected message containing '{expected_substring}' for case '{name}', got: {messages}"
    )


def test_duplicate_server_id_keeps_first_cap_for_downstream_checks(tmp_path):
    # Regression guard: server_lookup used to be overwritten by the *last*
    # server parsed with a given id, so a duplicate id with a tiny cap could
    # spuriously flip an unrelated "server packing" check for the original
    # server, muddying the error list beyond the "duplicate id" error itself.
    def mutate(cfg, _t):
        servers = cfg["topology"]["clusters"][0]["servers"]
        servers.append({"id": "c1-w1", "cpu_cap_cores": 0.5, "ram_cap_mb": 16384})

    messages = _build_and_validate(tmp_path, mutate)
    assert any("duplicate server id" in msg for msg in messages)
    assert not any("exceeds cpu_cap_cores" in msg for msg in messages), messages
