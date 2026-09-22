"""Overlay plots: load, serve μ, oracle/sweet CPU, TCN hats, drops, replicas."""

from __future__ import annotations

from pathlib import Path

from .aggregate import (
    app_owner_cluster_id,
    cluster_to_vicinity,
    group_containers_by_microservice,
    ms_physics_from_meta,
    packed_cpu_cores,
    replica_counts_by_site,
    serve_mu_series,
    sum_aligned,
    sum_series,
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
from .forecast_hats import compute_forecast_hats


def _serve_mu_by_ms(tau: list[int], containers: list, meta: dict, app_id: str) -> list[float]:
    parts: list[list[float]] = []
    for ms_id, group in group_containers_by_microservice(containers).items():
        spec = ms_physics_from_meta(meta, app_id, ms_id)
        parts.append(serve_mu_series(tau, group, spec))
    return sum_series(parts) if parts else [0.0] * len(tau)


def _oracle_cpu_by_ms(
    tau: list[int],
    containers: list,
    meta: dict,
    app_id: str,
    *,
    theta: float,
) -> list[float]:
    parts: list[list[float]] = []
    for ms_id, group in group_containers_by_microservice(containers).items():
        spec = ms_physics_from_meta(meta, app_id, ms_id)
        incoming = sum_aligned(tau, group, "incoming")
        parts.append([packed_cpu_cores(v, spec, theta=theta) for v in incoming])
    return sum_series(parts) if parts else [0.0] * len(tau)


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
        n = int(meta.get("N") or 0)
        tau = list(range(1, n + 1)) if n else sorted({t for c in containers for t in c.tau})
        packed.append((label, run_dir, meta, containers))

    assert chosen_app is not None
    physics_meta = next(
        (meta for _, _, meta, _ in packed if (meta.get("autoscaler") or {}).get("name") == "proactive_auto_scaler"),
        packed[0][2],
    )
    first_groups = group_containers_by_microservice(packed[0][3])
    theta_sweet = 0.60
    if first_groups:
        first_ms = next(iter(first_groups))
        theta_sweet = ms_physics_from_meta(physics_meta, chosen_app, first_ms).theta_target

    incoming = sum_aligned(tau, packed[0][3], "incoming")
    mu_by_label: list[tuple[str, list[float]]] = []
    cpu_by_label: list[tuple[str, list[float]]] = []
    dropped_by_label: list[tuple[str, list[float]]] = []
    replicas_by_label: list[tuple[str, list[float]]] = []
    forecast = None
    for label, _run_dir, meta, containers in packed:
        mu_by_label.append((label, _serve_mu_by_ms(tau, containers, physics_meta, chosen_app)))
        cpu_by_label.append((label, sum_aligned(tau, containers, "cpu_capacity")))
        dropped_by_label.append((label, sum_aligned(tau, containers, "dropped")))
        owner = app_owner_cluster_id(meta, chosen_app)
        counts = replica_counts_by_site(
            tau, containers, owner_cluster_id=owner, vmap=cluster_to_vicinity(meta)
        )
        replicas_by_label.append(
            (label, [sum(counts[site][i] for site in counts) for i in range(len(tau))])
        )
        candidate = compute_forecast_hats(meta, tau, incoming)
        if candidate is None:
            continue
        if forecast is None or (
            candidate.predictor == "tcn_delta" and forecast.predictor != "tcn_delta"
        ):
            forecast = candidate

    cpu_oracle = _oracle_cpu_by_ms(tau, packed[0][3], physics_meta, chosen_app, theta=1.0)
    cpu_sweet = _oracle_cpu_by_ms(
        tau, packed[0][3], physics_meta, chosen_app, theta=theta_sweet
    )
    hat1 = forecast.step1 if forecast is not None else None
    hat5 = forecast.step_h if forecast is not None else None
    hat_horizon = forecast.horizon if forecast is not None else 0
    if forecast is not None and forecast.predictor == "tcn_delta":
        hat_pretty = "TCN"
        hat1_label = "TCN t+1"
        hat5_label = f"TCN t+{hat_horizon}"
    elif forecast is not None:
        hat_pretty = forecast.predictor
        hat1_label = f"{forecast.predictor} t+1"
        hat5_label = f"{forecast.predictor} t+{hat_horizon}"
    else:
        hat_pretty = ""
        hat1_label = "forecast t+1"
        hat5_label = "forecast t+H"

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
        stale_tcn = directory / "tcn_forecast.png"
        if stale_tcn.exists():
            stale_tcn.unlink()
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
                out_path=directory / "forecast_vs_actual.png",
                title=f"Incoming vs {hat_pretty} t+1 and t+{hat_horizon} (hats start after lookback)",
                cold_start_until=cold_start_until,
                step1_label=hat1_label,
                horizon_label=hat5_label,
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
            hat1_label=hat1_label,
            hat5_label=hat5_label,
        )
        written.extend(sorted(directory.glob("*.png")))
    return written
