"""Overlay plots: load, serve μ, oracle/sweet CPU, TCN hats, drops, replicas."""

from __future__ import annotations

from pathlib import Path

from .aggregate import (
    app_owner_cluster_id,
    cluster_to_vicinity,
    ms_physics_from_meta,
    packed_cpu_cores,
    replica_counts_by_site,
    serve_mu_series,
    sum_aligned,
)
from .io import find_container_logs, load_run_meta, read_container_log
from .plots import (
    plot_forecast_vs_actual,
    plot_story_cpu,
    plot_story_dropped,
    plot_story_overview,
    plot_story_replicas,
    plot_story_serve_capacity,
)
from .tcn_hats import compute_tcn_hats


def write_story_plots(
    labeled_dirs: list[tuple[str, Path]],
    *,
    out_dir: Path,
    app_id: str | None = None,
    ms_id: str | None = None,
    cold_start_until: int | None = None,
) -> list[Path]:
    """Write the canvas-style story PNGs under ``out_dir`` and each run's ``analysis/story/``."""
    resolved = [(label, Path(run_dir).resolve()) for label, run_dir in labeled_dirs]
    metas = [load_run_meta(run_dir) for _, run_dir in resolved]

    chosen_app = app_id
    chosen_ms = ms_id
    packed: list[tuple[str, Path, dict, list]] = []
    tau: list[int] = []
    for (label, run_dir), meta in zip(resolved, metas):
        containers = [read_container_log(p) for p in find_container_logs(run_dir)]
        if chosen_app:
            containers = [c for c in containers if c.app_id == chosen_app]
        if chosen_ms:
            containers = [c for c in containers if c.microservice_id == chosen_ms]
        if not containers:
            raise KeyError(f"{label}: no containers after filters")
        if chosen_app is None:
            chosen_app = containers[0].app_id
        if chosen_ms is None:
            chosen_ms = containers[0].microservice_id
        n = int(meta.get("N") or 0)
        tau = list(range(1, n + 1)) if n else sorted({t for c in containers for t in c.tau})
        packed.append((label, run_dir, meta, containers))

    assert chosen_app is not None and chosen_ms is not None
    physics_meta = next(
        (meta for _, _, meta, _ in packed if (meta.get("autoscaler") or {}).get("name") == "proactive_auto_scaler"),
        packed[0][2],
    )
    spec = ms_physics_from_meta(physics_meta, chosen_app, chosen_ms)

    incoming = sum_aligned(tau, packed[0][3], "incoming")
    mu_by_label: list[tuple[str, list[float]]] = []
    cpu_by_label: list[tuple[str, list[float]]] = []
    dropped_by_label: list[tuple[str, list[float]]] = []
    replicas_by_label: list[tuple[str, list[float]]] = []
    hats: tuple[list[float], list[float]] | None = None
    for label, _run_dir, meta, containers in packed:
        mu_by_label.append((label, serve_mu_series(tau, containers, spec)))
        cpu_by_label.append((label, sum_aligned(tau, containers, "cpu_capacity")))
        dropped_by_label.append((label, sum_aligned(tau, containers, "dropped")))
        owner = app_owner_cluster_id(meta, chosen_app)
        counts = replica_counts_by_site(
            tau, containers, owner_cluster_id=owner, vmap=cluster_to_vicinity(meta)
        )
        replicas_by_label.append(
            (label, [sum(counts[site][i] for site in counts) for i in range(len(tau))])
        )
        if hats is None:
            hats = compute_tcn_hats(meta, tau, incoming)

    cpu_oracle = [packed_cpu_cores(v, spec, theta=1.0) for v in incoming]
    cpu_sweet = [packed_cpu_cores(v, spec, theta=spec.theta_target) for v in incoming]
    hat1 = hats[0] if hats is not None else None
    hat5 = hats[1] if hats is not None else None

    targets = [out_dir]
    for _label, run_dir, _meta, _containers in packed:
        targets.append(run_dir / "analysis" / "story")

    written: list[Path] = []
    seen: set[Path] = set()
    for directory in targets:
        directory = directory.resolve()
        if directory in seen:
            continue
        seen.add(directory)
        directory.mkdir(parents=True, exist_ok=True)
        plot_story_serve_capacity(
            tau=tau,
            incoming=incoming,
            mu_by_label=mu_by_label,
            out_path=directory / "serve_capacity.png",
            title="Incoming vs serve capacity μ (drops when incoming > μ)",
            cold_start_until=cold_start_until,
        )
        plot_story_cpu(
            tau=tau,
            cpu_oracle=cpu_oracle,
            cpu_sweet=cpu_sweet,
            cpu_by_label=cpu_by_label,
            out_path=directory / "cpu_needed_vs_provided.png",
            title="CPU: oracle to serve all, 60% target, and what each scaler gave",
            cold_start_until=cold_start_until,
        )
        plot_story_dropped(
            tau=tau,
            dropped_by_label=dropped_by_label,
            out_path=directory / "dropped.png",
            title="Dropped requests",
            cold_start_until=cold_start_until,
        )
        plot_story_replicas(
            tau=tau,
            replicas_by_label=replicas_by_label,
            out_path=directory / "replicas.png",
            title="Live replicas",
            cold_start_until=cold_start_until,
        )
        if hat1 is not None and hat5 is not None:
            plot_forecast_vs_actual(
                tau=tau,
                actual_counts=incoming,
                pred_step1=hat1,
                pred_horizon=hat5,
                out_path=directory / "tcn_forecast.png",
                title="Incoming vs TCN t+1 and t+5 (hats start after lookback)",
                cold_start_until=cold_start_until,
            )
        plot_story_overview(
            tau=tau,
            incoming=incoming,
            mu_by_label=mu_by_label,
            cpu_oracle=cpu_oracle,
            cpu_sweet=cpu_sweet,
            cpu_by_label=cpu_by_label,
            hat1=hat1,
            hat5=hat5,
            dropped_by_label=dropped_by_label,
            replicas_by_label=replicas_by_label,
            out_path=directory / "overview.png",
            title="Load, capacity, forecast, drops, replicas",
            cold_start_until=cold_start_until,
        )
        written.extend(sorted(directory.glob("*.png")))
    return written
