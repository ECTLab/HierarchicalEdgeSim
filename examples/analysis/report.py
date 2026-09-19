"""Orchestrate per-application analysis for a completed simulation run."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .aggregate import (
    action_markers,
    app_owner_cluster_id,
    cluster_to_vicinity,
    demand_weighted_aligned,
    group_containers_by_app,
    group_containers_by_microservice,
    mix_quantile_aligned,
    replica_counts_by_site,
    sum_aligned,
    sum_tau_window,
)
from .io import (
    cold_start_until_tau,
    find_container_logs,
    list_microservice_trace_refs,
    load_run_meta,
    read_actions,
    read_container_log,
    read_trace,
    resolve_trace_path,
)
from .plots import (
    plot_combined_requests,
    plot_cpu,
    plot_forecast_vs_actual,
    plot_ladder_qos,
    plot_ram,
    plot_replica_sites,
    plot_routing_split,
    plot_user_latency,
    plot_queue_wait,
)

_MAX_REPLICA_RESOURCE_PLOTS = 8
_MIN_TICKS_FOR_RESOURCE_PLOT = 2


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
    cold_start_until: int | None = None
    incoming_after_tcn: float | None = None
    dropped_after_tcn: float | None = None


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
      - ladder QoS (incoming, CPU alloc, drops + action markers)
      - user latency (offered mean/p95/p99 and SLA-miss rate)
      - replica counts by site (home / vicinity / outside)
    """
    run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise NotADirectoryError(f"run_dir is not a directory: {run_dir}")

    if project_root is None:
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
    actions = read_actions(run_dir)
    vmap = cluster_to_vicinity(meta)
    until = cold_start_until_tau(meta)

    summaries: list[AppAnalysisSummary] = []
    for app_id, app_containers in by_app.items():
        app_out = run_dir / "analysis" / app_id
        app_out.mkdir(parents=True, exist_ok=True)
        owner = app_owner_cluster_id(meta, app_id)

        by_ms = group_containers_by_microservice(app_containers)
        max_diff = 0.0
        total_incoming = 0.0
        total_served = 0.0
        total_dropped = 0.0
        incoming_after_tcn = 0.0
        dropped_after_tcn = 0.0
        ticks = 0

        for ms_id, ms_containers in by_ms.items():
            for c in ms_containers:
                if not c.tau:
                    continue
                q = c.queue_len if len(c.queue_len) == len(c.incoming) else [0.0] * len(c.incoming)
                prev_q = 0.0
                residual = 0.0
                for i, s, d, qn in zip(c.incoming, c.served, c.dropped, q):
                    residual = max(residual, abs((i + prev_q) - (s + d + qn)))
                    prev_q = qn
                if residual > 1e-6:
                    raise ValueError(
                        f"{c.container_id}: incoming+queue != served+dropped+queue, "
                        f"max residual={residual}"
                    )

            ref = trace_refs.get((app_id, ms_id))
            if ref is None:
                raise KeyError(f"no trace_file in run_meta for app={app_id} ms={ms_id}")
            trace_path = resolve_trace_path(project_root, meta, ref.trace_file)
            tau_trace, trace_requests = read_trace(trace_path)
            ticks = max(ticks, len(tau_trace))

            incoming = sum_aligned(tau_trace, ms_containers, "incoming")
            served = sum_aligned(tau_trace, ms_containers, "served")
            dropped = sum_aligned(tau_trace, ms_containers, "dropped")
            diff = max(abs(a - b) for a, b in zip(trace_requests, incoming))
            if diff > 1e-9:
                raise ValueError(
                    f"app={app_id} ms={ms_id}: trace vs sum(incoming) mismatch, max abs diff={diff}"
                )

            max_diff = max(max_diff, diff)
            total_incoming += sum(incoming)
            total_served += sum(served)
            total_dropped += sum(dropped)
            if until is not None and tau_trace:
                incoming_after_tcn += sum_tau_window(
                    tau_trace, incoming, start=until + 1, end=tau_trace[-1]
                )
                dropped_after_tcn += sum_tau_window(
                    tau_trace, dropped, start=until + 1, end=tau_trace[-1]
                )

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
                cold_start_until=until,
            )
            split_name = (
                "routing_split.png" if len(by_ms) == 1 else f"routing_split_{ms_id}.png"
            )
            plot_routing_split(
                tau=tau_trace,
                containers=ms_containers,
                out_path=app_out / split_name,
                title=f"{app_id}/{ms_id}: incoming by replica",
            )
            _maybe_plot_tcn_forecast(
                meta=meta,
                tau=tau_trace,
                incoming=incoming,
                out_path=app_out / (
                    "tcn_forecast.png" if len(by_ms) == 1 else f"tcn_forecast_{ms_id}.png"
                ),
                title=f"{app_id}/{ms_id}: TCN vs observed incoming",
                cold_start_until=until,
            )

            markers = action_markers(actions, ms_id=ms_id)
            qos_name = "ladder_qos.png" if len(by_ms) == 1 else f"ladder_qos_{ms_id}.png"
            plot_ladder_qos(
                tau=tau_trace,
                incoming=incoming,
                cpu_capacity=sum_aligned(tau_trace, ms_containers, "cpu_capacity"),
                dropped=dropped,
                markers=markers,
                out_path=app_out / qos_name,
                title=f"{app_id}/{ms_id}: load and drops",
                cold_start_until=until,
            )
            sla_timeout = 1.0
            sim_cfg = (meta.get("config") or {}).get("sim") or {}
            if sim_cfg.get("sla_timeout_sec") is not None:
                sla_timeout = float(sim_cfg["sla_timeout_sec"])
            tick_sec = float(sim_cfg.get("tick_sec") or 0.0)
            xlabel = "minute" if abs(tick_sec - 60.0) < 1e-9 else "time_unit"
            lat_name = "user_latency.png" if len(by_ms) == 1 else f"user_latency_{ms_id}.png"
            plot_user_latency(
                tau=tau_trace,
                incoming=incoming,
                mean_sec=demand_weighted_aligned(tau_trace, ms_containers, "t_mean_offered_sec"),
                p95_sec=mix_quantile_aligned(tau_trace, ms_containers, 0.95, sla_timeout),
                p99_sec=mix_quantile_aligned(tau_trace, ms_containers, 0.99, sla_timeout),
                sla_miss=sum_aligned(tau_trace, ms_containers, "sla_miss"),
                out_path=app_out / lat_name,
                title=f"{app_id}/{ms_id}: completed delay (timeouts excluded)",
                sla_timeout_sec=sla_timeout,
                cold_start_until=until,
                xlabel=xlabel,
            )
            q_name = "queue_wait.png" if len(by_ms) == 1 else f"queue_wait_{ms_id}.png"
            plot_queue_wait(
                tau=tau_trace,
                queue_wait_sec=_max_aligned(tau_trace, ms_containers, "t_wait_sec"),
                queue_len=sum_aligned(tau_trace, ms_containers, "queue_len"),
                out_path=app_out / q_name,
                title=f"{app_id}/{ms_id}: FCFS queue (drain time vs SLO)",
                sla_timeout_sec=sla_timeout,
                cold_start_until=until,
                xlabel=xlabel,
            )
            counts = replica_counts_by_site(
                tau_trace, ms_containers, owner_cluster_id=owner, vmap=vmap
            )
            rep_name = "replicas_by_site.png" if len(by_ms) == 1 else f"replicas_by_site_{ms_id}.png"
            plot_replica_sites(
                tau=tau_trace,
                counts=counts,
                markers=markers,
                out_path=app_out / rep_name,
                title=f"{app_id}/{ms_id}: replicas by site",
            )

        for c in _resource_plot_targets(app_containers):
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
                cold_start_until=until,
                incoming_after_tcn=incoming_after_tcn if until is not None else None,
                dropped_after_tcn=dropped_after_tcn if until is not None else None,
            )
        )

    return summaries


def _max_aligned(tau_full: list[int], containers: list, attr: str) -> list[float]:
    out: list[float] = []
    for t in tau_full:
        vals = []
        for c in containers:
            by = dict(zip(c.tau, getattr(c, attr)))
            vals.append(float(by.get(t, 0.0)))
        out.append(max(vals) if vals else 0.0)
    return out


def _resource_plot_targets(containers: list) -> list:
    """Home / longest-lived replicas only — skip empty and one-tick spawn leftovers."""
    live = [c for c in containers if len(c.tau) >= _MIN_TICKS_FOR_RESOURCE_PLOT]
    if not live:
        return []
    ranked = sorted(live, key=lambda c: (len(c.tau), sum(c.incoming)), reverse=True)
    return ranked[:_MAX_REPLICA_RESOURCE_PLOTS]


def _maybe_plot_tcn_forecast(
    *,
    meta: dict,
    tau: list[int],
    incoming: list[float],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
) -> None:
    from .tcn_hats import compute_tcn_hats

    hats = compute_tcn_hats(meta, tau, incoming)
    if hats is None:
        return
    step1, step_h = hats
    plot_forecast_vs_actual(
        tau=tau,
        actual_counts=incoming,
        pred_step1=step1,
        pred_horizon=step_h,
        out_path=out_path,
        title=title,
        cold_start_until=cold_start_until,
    )
