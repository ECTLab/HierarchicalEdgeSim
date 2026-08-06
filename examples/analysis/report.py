"""Orchestrate per-application analysis for a completed simulation run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .aggregate import group_containers_by_app, group_containers_by_microservice, sum_series
from .io import (
    find_container_logs,
    list_microservice_trace_refs,
    load_run_meta,
    read_container_log,
    read_trace,
    resolve_trace_path,
)
from .plots import plot_combined_requests, plot_cpu, plot_ram


@dataclass(slots=True)
class AppAnalysisSummary:
    app_id: str
    container_ids: list[str]
    ticks: int
    total_incoming: float
    total_served: float
    total_dropped: float
    max_abs_diff_trace_vs_incoming: float
    output_dir: Path


def analyze_run(
    run_dir: Path,
    *,
    project_root: Path | None = None,
    apps_filter: set[str] | None = None,
) -> list[AppAnalysisSummary]:
    """Analyze one run directory and write plots under ``<run_dir>/analysis/<app_id>/``.

    For each application:
      - one combined requests plot (trace vs sum incoming/served/dropped)
      - per-container CPU and RAM plots
    """
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise NotADirectoryError(f"run_dir is not a directory: {run_dir}")

    if project_root is None:
        # examples/analysis/report.py -> examples/analysis -> examples -> project root
        project_root = Path(__file__).resolve().parents[2]

    meta = load_run_meta(run_dir)
    logs = find_container_logs(run_dir)
    if not logs:
        raise FileNotFoundError(f"no container log CSV found under {run_dir}/apps/")

    containers = [read_container_log(path) for path in logs]
    by_app = group_containers_by_app(containers)
    if apps_filter is not None:
        missing = apps_filter - set(by_app)
        if missing:
            raise KeyError(f"apps not found in run logs: {sorted(missing)}")
        by_app = {app_id: by_app[app_id] for app_id in sorted(apps_filter)}

    trace_refs = {
        (ref.app_id, ref.microservice_id): ref
        for ref in list_microservice_trace_refs(meta)
    }

    summaries: list[AppAnalysisSummary] = []
    for app_id, app_containers in by_app.items():
        app_out = run_dir / "analysis" / app_id
        app_out.mkdir(parents=True, exist_ok=True)

        # One combined requests figure per microservice in the app (usually one).
        by_ms = group_containers_by_microservice(app_containers)
        max_diff = 0.0
        total_incoming = 0.0
        total_served = 0.0
        total_dropped = 0.0
        ticks = len(app_containers[0].tau)

        for ms_id, ms_containers in by_ms.items():
            for c in ms_containers:
                residual = max(abs(i - (s + d)) for i, s, d in zip(c.incoming, c.served, c.dropped))
                if residual > 1e-9:
                    raise ValueError(
                        f"{c.container_id}: incoming != served+dropped, max residual={residual}"
                    )

            ref = trace_refs.get((app_id, ms_id))
            if ref is None:
                raise KeyError(f"no trace_file in run_meta for app={app_id} ms={ms_id}")
            trace_path = resolve_trace_path(project_root, meta, ref.trace_file)
            tau_trace, trace_requests = read_trace(trace_path)

            for c in ms_containers:
                if c.tau != tau_trace:
                    raise ValueError(f"time_unit mismatch between trace and log for {c.container_id}")

            incoming = sum_series([c.incoming for c in ms_containers])
            served = sum_series([c.served for c in ms_containers])
            dropped = sum_series([c.dropped for c in ms_containers])
            diff = max(abs(a - b) for a, b in zip(trace_requests, incoming))
            if diff > 1e-9:
                raise ValueError(
                    f"app={app_id} ms={ms_id}: trace vs sum(incoming) mismatch, max abs diff={diff}"
                )

            max_diff = max(max_diff, diff)
            total_incoming += sum(incoming)
            total_served += sum(served)
            total_dropped += sum(dropped)

            plot_name = (
                "trace_vs_log_requests.png"
                if len(by_ms) == 1
                else f"trace_vs_log_requests_{ms_id}.png"
            )
            plot_combined_requests(
                tau=tau_trace,
                trace_requests=trace_requests,
                containers=ms_containers,
                out_path=app_out / plot_name,
                title=f"{app_id}/{ms_id}: Trace vs Logs",
            )

        for c in app_containers:
            plot_cpu(c, app_out / f"{c.container_id}_cpu.png")
            plot_ram(c, app_out / f"{c.container_id}_ram.png")

        summaries.append(
            AppAnalysisSummary(
                app_id=app_id,
                container_ids=[c.container_id for c in app_containers],
                ticks=ticks,
                total_incoming=total_incoming,
                total_served=total_served,
                total_dropped=total_dropped,
                max_abs_diff_trace_vs_incoming=max_diff,
                output_dir=app_out,
            )
        )

    return summaries
