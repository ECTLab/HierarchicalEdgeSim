"""Compare labeled run directories (same trace, different scalers)."""

from __future__ import annotations

from pathlib import Path

from .aggregate import (
    app_owner_cluster_id,
    cluster_to_vicinity,
    replica_counts_by_site,
    sum_aligned,
)
from .io import cold_start_until_tau, find_container_logs, load_run_meta, read_actions, read_container_log
from .plots import plot_baseline_comparison
from .story import write_story_plots


def compare_runs(
    labeled_dirs: list[tuple[str, Path]],
    *,
    out_path: Path,
    app_id: str | None = None,
    ms_id: str | None = None,
) -> Path:
    resolved = [(label, Path(run_dir).resolve()) for label, run_dir in labeled_dirs]
    metas = [load_run_meta(run_dir) for _, run_dir in resolved]
    until: int | None = None
    for meta in metas:
        run_until = cold_start_until_tau(meta)
        if run_until is not None:
            until = max(until or 0, run_until)

    series: list[tuple[str, list[int], list[float], list[float]]] = []
    totals: list[tuple[str, float, float, int]] = []
    chosen_app = app_id
    chosen_ms = ms_id
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
        dropped = sum_aligned(tau, containers, "dropped")
        owner = app_owner_cluster_id(meta, chosen_app)
        counts = replica_counts_by_site(
            tau, containers, owner_cluster_id=owner, vmap=cluster_to_vicinity(meta)
        )
        replica_total = [sum(counts[site][i] for site in counts) for i in range(len(tau))]
        actions = [
            a
            for a in read_actions(run_dir)
            if a.result_code == "OK" and a.action_type in {"resize", "spawn", "terminate"}
        ]
        series.append((label, tau, dropped, replica_total))
        totals.append((label, sum(dropped), max(replica_total) if replica_total else 0.0, len(actions)))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    plot_baseline_comparison(
        series=series,
        totals=totals,
        out_path=out_path,
        title=(
            f"Reactive baseline comparison (grey = no forecast, τ≤{until})"
            if until is not None
            else "Reactive baseline comparison"
        ),
        cold_start_until=until,
    )
    write_story_plots(
        resolved,
        out_dir=out_path.parent / "story",
        app_id=chosen_app,
        ms_id=chosen_ms,
        cold_start_until=until,
    )
    return out_path
