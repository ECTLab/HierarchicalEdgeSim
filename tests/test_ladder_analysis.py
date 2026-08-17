"""Ladder analysis helpers (site classification, replica timeline, plots)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from hierarchical_edge_sim.env.api import Env, TerminateAction

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

from analysis.aggregate import (  # noqa: E402
    action_markers,
    app_owner_cluster_id,
    classify_site,
    packed_cpu_cores,
    replica_counts_by_site,
    replica_serve_mu,
    series_on_tau,
    sum_aligned,
    sum_tau_window,
    MsPhysics,
)
from analysis.io import (  # noqa: E402
    ActionRow,
    ContainerSeries,
    cold_start_until_tau,
    find_container_logs,
    list_microservice_trace_refs,
    load_run_meta,
    read_container_log,
    read_trace,
    resolve_trace_path,
)


def _tiny_plot_env(tmp_path: Path) -> Env:
    cfg = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "servers": [
                        {"id": "c1-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096},
                        {"id": "c1-w2", "cpu_cap_cores": 8.0, "ram_cap_mb": 4096},
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
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    (tdir / "api.csv").write_text(
        "time_unit,requests\n1,10\n2,10\n3,10\n", encoding="utf-8"
    )
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return Env.from_config(path)


def test_series_on_tau_fills_gaps():
    assert series_on_tau([1, 2, 3, 4], [2, 3], [10.0, 20.0]) == [0.0, 10.0, 20.0, 0.0]


def test_sum_tau_window_inclusive():
    tau = [1, 2, 3, 4]
    vals = [10.0, 20.0, 30.0, 40.0]
    assert sum_tau_window(tau, vals, start=1, end=60) == 100.0
    assert sum_tau_window(tau, vals, start=3, end=4) == 70.0
    assert sum_tau_window(tau, vals, start=5, end=10) == 0.0


def test_packed_cpu_and_serve_mu_match_alibaba_physics():
    spec = MsPhysics(
        cpu_min=0.5,
        cpu_max=4.0,
        ram_min=256.0,
        rho_cpu=0.0004,
        rho_ram=0.02,
        theta_target=0.60,
    )
    assert replica_serve_mu(2.0, 1024.0, spec) == 3750.0
    assert abs(packed_cpu_cores(29778.0, spec, theta=1.0) - 13.9112) < 1e-6
    assert replica_serve_mu(0.5, 256.0, spec) == 0.0


def test_cold_start_until_tau_from_meta():
    assert cold_start_until_tau({}) is None
    assert cold_start_until_tau({"autoscaler": {"name": "reactive_local"}}) is None
    assert (
        cold_start_until_tau(
            {
                "autoscaler": {
                    "name": "proactive_auto_scaler",
                    "params": {"feature_window": 10, "predictor": "persistence"},
                }
            }
        )
        is None
    )
    assert (
        cold_start_until_tau(
            {
                "autoscaler": {
                    "name": "proactive_auto_scaler",
                    "params": {"feature_window": 60, "predictor": "tcn_delta"},
                }
            }
        )
        == 60
    )


def test_classify_site_home_vicinity_global():
    vmap = {"c1": "v1", "c2": "v1", "c3": "v2"}
    assert classify_site("c1", "c1", vmap) == "home"
    assert classify_site("c2", "c1", vmap) == "vicinity"
    assert classify_site("c3", "c1", vmap) == "global"
    assert classify_site("c2", "c1", {}) == "remote"


def test_app_owner_cluster_id_uses_sorted_container_id():
    meta = {
        "config": {
            "clusters": [
                {"id": "c1", "servers": [{"id": "c1-w1"}]},
                {"id": "c2", "servers": [{"id": "c2-w1"}]},
            ],
            "apps": [
                {
                    "id": "demo_app",
                    "microservices": [
                        {
                            "containers": [
                                {"id": "c-api-2", "server_id": "c2-w1"},
                                {"id": "c-api-1", "server_id": "c1-w1"},
                            ]
                        }
                    ],
                }
            ],
        }
    }
    assert app_owner_cluster_id(meta, "demo_app") == "c1"


def test_replica_counts_by_site_and_action_markers():
    tau = [1, 2, 3]
    home = ContainerSeries(
        app_id="a",
        microservice_id="api",
        container_id="c-home",
        log_path=Path("x"),
        tau=[1, 2, 3],
        incoming=[0, 0, 0],
        served=[0, 0, 0],
        dropped=[0, 0, 0],
        cpu_capacity=[1, 1, 1],
        cpu_used=[0, 0, 0],
        ram_capacity=[1, 1, 1],
        ram_used=[0, 0, 0],
        cluster_id="c1",
    )
    borrowed = ContainerSeries(
        app_id="a",
        microservice_id="api",
        container_id="c-v",
        log_path=Path("x"),
        tau=[2, 3],
        incoming=[0, 0],
        served=[0, 0],
        dropped=[0, 0],
        cpu_capacity=[0.5, 0.5],
        cpu_used=[0, 0],
        ram_capacity=[1, 1],
        ram_used=[0, 0],
        cluster_id="c2",
    )
    counts = replica_counts_by_site(
        tau, [home, borrowed], owner_cluster_id="c1", vmap={"c1": "v1", "c2": "v1"}
    )
    assert counts["home"] == [1.0, 1.0, 1.0]
    assert counts["vicinity"] == [0.0, 1.0, 1.0]
    assert "remote" not in counts
    markers = action_markers(
        [
            ActionRow(2, "reactive_local", "api", "spawn", "c-v", "vicinity_spawn", "OK"),
            ActionRow(2, "reactive_local", "api", "spawn", "c-v", "vicinity_spawn", "OK"),
            ActionRow(3, "reactive_local", "other", "spawn", "x", "beg_spawn", "OK"),
            ActionRow(4, "reactive_local", "api", "resize", "c-home", "bev_up", "OK"),
            ActionRow(5, "reactive_local", "api", "resize", "c-home", "bev_down", "OK"),
        ],
        ms_id="api",
    )
    assert markers["vicinity"] == [2]
    assert markers["BEV up"] == [4]
    assert markers["BEV down"] == [5]
    assert "BEG" not in markers


def test_analyze_run_emits_ladder_plots(tmp_path: Path):
    pytest.importorskip("matplotlib")
    from analysis.report import analyze_run

    env = _tiny_plot_env(tmp_path)
    run_dir = env.run(max_ticks=3, now_utc=datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC))
    summaries = analyze_run(run_dir, project_root=tmp_path)
    assert summaries[0].total_incoming == 30.0
    out = summaries[0].output_dir
    assert (out / "trace_vs_log_requests.png").is_file()
    assert (out / "ladder_qos.png").is_file()
    assert (out / "replicas_by_site.png").is_file()


class _KillSpawned:
    name = "kill_spawned"

    def __init__(self, container_id: str) -> None:
        self.container_id = container_id

    def on_tick_end(self, env: Env, tau: int) -> list:
        if tau != 2:
            return []
        return [
            TerminateAction(
                type="terminate",
                ms_id="api",
                container_id=self.container_id,
                reason="beh_terminate",
            )
        ]


def test_terminated_replica_log_still_matches_trace(tmp_path: Path):
    env = _tiny_plot_env(tmp_path)
    spawned = env.spawn(ms_id="api", server_id="c1-w2")
    assert spawned.ok
    run_dir = env.run(
        max_ticks=3,
        now_utc=datetime(2026, 8, 15, 12, 30, 0, tzinfo=UTC),
        autoscaler=_KillSpawned(spawned.container_id),
    )
    assert spawned.container_id not in env.world.containers
    log_path = run_dir / "apps" / "demo_app" / "api" / f"{spawned.container_id}.log.csv"
    assert log_path.is_file()

    containers = [read_container_log(p) for p in find_container_logs(run_dir)]
    assert spawned.container_id in {c.container_id for c in containers}
    meta = load_run_meta(run_dir)
    ref = list_microservice_trace_refs(meta)[0]
    tau, trace_requests = read_trace(resolve_trace_path(tmp_path, meta, ref.trace_file))
    incoming = sum_aligned(tau, containers, "incoming")
    assert incoming == trace_requests
    assert sum(incoming) == 30.0


def test_compare_runs_writes_png(tmp_path: Path):
    pytest.importorskip("matplotlib")
    from analysis.compare import compare_runs

    run_a = _tiny_plot_env(tmp_path / "a").run(
        max_ticks=3, now_utc=datetime(2026, 8, 15, 13, 0, 0, tzinfo=UTC)
    )
    run_b = _tiny_plot_env(tmp_path / "b").run(
        max_ticks=3, now_utc=datetime(2026, 8, 15, 13, 1, 0, tzinfo=UTC)
    )
    out = tmp_path / "baseline_comparison.png"
    compare_runs([("off", run_a), ("local", run_b)], out_path=out)
    assert out.is_file()
    story = out.parent / "story"
    assert (story / "serve_capacity.png").is_file()
    assert (story / "cpu_needed_vs_provided.png").is_file()
    assert (story / "overview.png").is_file()
