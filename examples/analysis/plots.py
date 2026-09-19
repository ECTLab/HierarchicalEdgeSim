"""Plotting helpers for request / CPU / RAM diagnostics and ladder figures."""

from __future__ import annotations

from pathlib import Path

try:
    import matplotlib.pyplot as plt
    from matplotlib.ticker import MaxNLocator
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "matplotlib is required for analysis plots; install with pip install -e '.[plot]'"
    ) from exc

from .aggregate import sum_aligned, sum_series
from .io import ContainerSeries

_FAMILY_STYLE = {
    "vertical up": {"color": "#1f77b4", "linestyle": "--"},
    "vertical down": {"color": "#17becf", "linestyle": ":"},
    "horizontal spawn": {"color": "#ff7f0e", "linestyle": "--"},
    "horizontal terminate": {"color": "#ffbb78", "linestyle": ":"},
    "vicinity": {"color": "#2ca02c", "linestyle": "-."},
    "vicinity up": {"color": "#2ca02c", "linestyle": "--"},
    "vicinity down": {"color": "#8c564b", "linestyle": ":"},
    "vicinity terminate": {"color": "#98df8a", "linestyle": ":"},
    "cascade": {"color": "#9467bd", "linestyle": ":"},
    "escalate": {"color": "#7f7f7f", "linestyle": ":"},
    "unmet": {"color": "#d62728", "linestyle": ":"},
}

_ROUTING_TOP_N = 6
_COLD_START_FACE = "#9e9e9e"


def _ylim_from_zero(ax) -> None:
    _, hi = ax.get_ylim()
    ax.set_ylim(0.0, hi if hi > 0.0 else 1.0)


def _save(fig, out_path: Path) -> None:
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _legend(ax, *, ncol: int = 1, loc: str = "upper left") -> None:
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return
    ax.legend(
        handles,
        labels,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        ncol=1 if len(labels) <= 6 else ncol,
        fontsize=8,
        frameon=False,
        borderaxespad=0.0,
    )


def _draw_cold_start_span(
    ax,
    until: int | None,
    *,
    legend: bool = True,
) -> None:
    """Grey band over τ=1…W: no hats yet; first proactive apply is τ=W+1."""
    if until is None or until < 1:
        return
    ax.axvspan(
        0.5,
        float(until) + 0.5,
        color=_COLD_START_FACE,
        alpha=0.22,
        zorder=0,
        label=f"no forecast (τ≤{until})" if legend else None,
    )


def _annotate_drop_rates(
    ax,
    tau: list[int],
    incoming: list[float],
    dropped: list[float],
    until: int | None,
) -> None:
    if not tau or not incoming:
        return
    t0, t1 = tau[0], tau[-1]
    whole_i = float(sum(incoming))
    whole_d = float(sum(dropped))
    whole_pct = (100.0 * whole_d / whole_i) if whole_i else 0.0
    lines = [f"drop τ={t0}–{t1}: {whole_pct:.2f}%"]
    if until is not None and until < t1:
        after_i = float(sum(v for t, v in zip(tau, incoming) if t > until))
        after_d = float(sum(v for t, v in zip(tau, dropped) if t > until))
        after_pct = (100.0 * after_d / after_i) if after_i else 0.0
        lines.append(f"after forecast on (τ≥{until + 1}): {after_pct:.2f}%")
    ax.text(
        0.99,
        0.97,
        "\n".join(lines),
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=8,
        color="#333333",
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "alpha": 0.85, "edgecolor": "none"},
    )


def _consecutive_runs(ticks: list[int]) -> list[tuple[int, int]]:
    """Inclusive [start, end] runs of consecutive integer ticks."""
    if not ticks:
        return []
    ordered = sorted(ticks)
    runs: list[tuple[int, int]] = []
    start = prev = ordered[0]
    for t in ordered[1:]:
        if t == prev + 1:
            prev = t
            continue
        runs.append((start, prev))
        start = prev = t
    runs.append((start, prev))
    return runs


def _draw_action_markers(ax, markers: dict[str, list[int]], *, legend: bool = True) -> None:
    """Sparse families stay as vlines; long consecutive runs (unmet windows) become a span."""
    seen: set[str] = set()
    for family, ticks in markers.items():
        style = _FAMILY_STYLE.get(family, {"color": "black", "linestyle": ":"})
        for start, end in _consecutive_runs(ticks):
            label = family if legend and family not in seen else None
            if end - start >= 2:
                ax.axvspan(
                    start - 0.5,
                    end + 0.5,
                    color=style["color"],
                    alpha=0.12,
                    zorder=0,
                    label=label,
                )
            else:
                for t in range(start, end + 1):
                    ax.axvline(
                        t,
                        color=style["color"],
                        linestyle=style["linestyle"],
                        alpha=0.35,
                        linewidth=0.9,
                        label=label,
                    )
                    label = None
            if legend:
                seen.add(family)


def plot_combined_requests(
    *,
    tau: list[int],
    trace_requests: list[float],
    containers: list[ContainerSeries],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
) -> None:
    """MS totals only. Per-replica routing goes on ``plot_routing_split``."""
    if containers and all(c.tau == tau for c in containers):
        total_incoming = sum_series([c.incoming for c in containers])
        total_served = sum_series([c.served for c in containers])
        total_dropped = sum_series([c.dropped for c in containers])
    else:
        total_incoming = sum_aligned(tau, containers, "incoming")
        total_served = sum_aligned(tau, containers, "served")
        total_dropped = sum_aligned(tau, containers, "dropped")

    fig, ax = plt.subplots(figsize=(11, 5))
    _draw_cold_start_span(ax, cold_start_until)
    ax.plot(tau, trace_requests, label="trace", linewidth=2.4, color="#222222")
    ax.plot(tau, total_incoming, label="sum incoming", linestyle="--", linewidth=1.8, color="#1f77b4")
    ax.plot(tau, total_served, label="sum served", linewidth=1.8, color="#2ca02c")
    ax.plot(tau, total_dropped, label="sum dropped", linewidth=1.8, color="#d62728")
    ax.set_xlabel("time_unit")
    ax.set_ylabel("requests")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    _annotate_drop_rates(ax, tau, total_incoming, total_dropped, cold_start_until)
    _legend(ax, ncol=2)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_routing_split(
    *,
    tau: list[int],
    containers: list[ContainerSeries],
    out_path: Path,
    title: str,
    top_n: int = _ROUTING_TOP_N,
) -> None:
    """Top-N replicas by total incoming; the rest collapse into ``other``."""
    live = [c for c in containers if c.tau]
    if not live:
        return
    ranked = sorted(live, key=lambda c: sum(c.incoming), reverse=True)
    top = ranked[:top_n]
    rest = ranked[top_n:]

    fig, ax = plt.subplots(figsize=(11, 5))
    for c in top:
        series = sum_aligned(tau, [c], "incoming")
        ax.plot(tau, series, label=c.container_id, linewidth=1.4)
    if rest:
        other = sum_aligned(tau, rest, "incoming")
        ax.plot(tau, other, label=f"other ({len(rest)})", linewidth=1.6, color="#7f7f7f")
    ax.set_xlabel("time_unit")
    ax.set_ylabel("requests")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    _legend(ax, ncol=2)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_cpu(container: ContainerSeries, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(
        container.tau,
        container.cpu_used,
        label="cpu usage (cores)",
        linewidth=2,
        drawstyle="steps-post",
        zorder=3,
    )
    ax.plot(
        container.tau,
        container.cpu_capacity,
        label="cpu alloc (cores)",
        linewidth=2,
        linestyle="--",
        drawstyle="steps-post",
        zorder=2,
    )
    ax.set_xlabel("time_unit")
    ax.set_ylabel("cpu cores")
    ax.set_title(f"{container.container_id}: CPU alloc vs usage")
    ax.grid(True, alpha=0.3)
    _legend(ax)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_ram(container: ContainerSeries, out_path: Path) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(
        container.tau,
        container.ram_used,
        label="ram usage (MB)",
        linewidth=2,
        drawstyle="steps-post",
        zorder=3,
    )
    ax.plot(
        container.tau,
        container.ram_capacity,
        label="ram alloc (MB)",
        linewidth=2,
        linestyle="--",
        drawstyle="steps-post",
        zorder=2,
    )
    ax.set_xlabel("time_unit")
    ax.set_ylabel("ram MB")
    ax.set_title(f"{container.container_id}: RAM alloc vs usage")
    ax.grid(True, alpha=0.3)
    _legend(ax)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_ladder_qos(
    *,
    tau: list[int],
    incoming: list[float],
    cpu_capacity: list[float],
    dropped: list[float],
    markers: dict[str, list[int]],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
) -> None:
    fig, (ax_load, ax_cpu) = plt.subplots(
        2,
        1,
        figsize=(11, 7.5),
        sharex=True,
        gridspec_kw={"height_ratios": [2.0, 1.0]},
    )
    _draw_cold_start_span(ax_load, cold_start_until)
    ax_load.plot(tau, incoming, label="incoming", linewidth=2)
    ax_load.plot(tau, dropped, label="dropped", color="#d62728", linewidth=1.8)
    ax_load.set_ylabel("requests")
    ax_load.set_title(title)
    ax_load.grid(True, alpha=0.3)
    _draw_action_markers(ax_load, markers)
    _annotate_drop_rates(ax_load, tau, incoming, dropped, cold_start_until)
    _legend(ax_load, ncol=3)
    _ylim_from_zero(ax_load)

    _draw_cold_start_span(ax_cpu, cold_start_until, legend=False)
    ax_cpu.plot(
        tau,
        cpu_capacity,
        label="sum CPU alloc",
        color="#ff7f0e",
        linewidth=2,
        drawstyle="steps-post",
    )
    ax_cpu.set_xlabel("time_unit")
    ax_cpu.set_ylabel("CPU cores")
    ax_cpu.grid(True, alpha=0.3)
    _draw_action_markers(ax_cpu, markers, legend=False)
    _legend(ax_cpu)
    _ylim_from_zero(ax_cpu)
    _save(fig, out_path)


def plot_user_latency(
    *,
    tau: list[int],
    incoming: list[float],
    mean_sec: list[float],
    p95_sec: list[float],
    p99_sec: list[float],
    sla_miss: list[float],
    out_path: Path,
    title: str,
    sla_timeout_sec: float | None = None,
    cold_start_until: int | None = None,
) -> None:
    """Offered-load delay (timeouts included) and SLA-miss rate."""
    miss_rate = [
        (100.0 * m / i) if i else 0.0 for m, i in zip(sla_miss, incoming)
    ]
    fig, (ax_t, ax_s) = plt.subplots(
        2,
        1,
        figsize=(11, 7.5),
        sharex=True,
        gridspec_kw={"height_ratios": [2.0, 1.0]},
    )
    _draw_cold_start_span(ax_t, cold_start_until)
    ax_t.plot(tau, mean_sec, label="mean offered", linewidth=1.8, color="#1f77b4")
    ax_t.plot(tau, p95_sec, label="p95 offered", linewidth=1.5, color="#ff7f0e")
    ax_t.plot(tau, p99_sec, label="p99 offered", linewidth=1.8, color="#d62728")
    if sla_timeout_sec is not None and sla_timeout_sec > 0:
        ax_t.axhline(
            sla_timeout_sec,
            color="#7f7f7f",
            linestyle=":",
            linewidth=1.2,
            label=f"T_slo={sla_timeout_sec:g}s",
        )
    ax_t.set_ylabel("seconds")
    ax_t.set_title(title)
    ax_t.grid(True, alpha=0.3)
    _legend(ax_t, ncol=2)
    _ylim_from_zero(ax_t)

    _draw_cold_start_span(ax_s, cold_start_until, legend=False)
    ax_s.plot(tau, miss_rate, label="SLA miss", color="#d62728", linewidth=1.8)
    ax_s.set_xlabel("time_unit")
    ax_s.set_ylabel("SLA miss %")
    ax_s.grid(True, alpha=0.3)
    _legend(ax_s)
    _ylim_from_zero(ax_s)
    _save(fig, out_path)


def plot_replica_sites(
    *,
    tau: list[int],
    counts: dict[str, list[float]],
    markers: dict[str, list[int]],
    out_path: Path,
    title: str,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    order = [s for s in ("home", "vicinity", "outside", "remote") if s in counts]
    for site in order:
        ax.plot(tau, counts[site], label=site, linewidth=2, drawstyle="steps-post")
    marker_ticks = sum(len(v) for v in markers.values())
    if marker_ticks <= 40:
        _draw_action_markers(ax, markers)
    ax.set_xlabel("time_unit")
    ax.set_ylabel("live replicas")
    ax.set_title(title)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)
    _legend(ax, ncol=3)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_forecast_vs_actual(
    *,
    tau: list[int],
    actual_counts: list[float],
    pred_step1: list[float],
    pred_horizon: list[float],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
    step1_label: str = "t+1 hat",
    horizon_label: str = "t+H hat",
) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    _draw_cold_start_span(ax, cold_start_until)
    ax.plot(tau, actual_counts, label="trace", color="#222222", linewidth=2.0)
    ax.plot(tau, pred_step1, label=step1_label, color="#1f77b4", linewidth=1.6)
    ax.plot(tau, pred_horizon, label=horizon_label, color="#ff7f0e", linewidth=1.4, linestyle="--")
    ax.set_xlabel("time_unit")
    ax.set_ylabel("requests")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    _legend(ax, ncol=3)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_baseline_comparison(
    *,
    series: list[tuple[str, list[int], list[float], list[float]]],
    totals: list[tuple[str, float, float, int]],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
    drop_windows: list[tuple[str, float, float]] | None = None,
) -> None:
    """series: (label, tau, dropped, replica_count). totals: (label, sum_drop, max_replicas, n_ok_actions).

    When ``drop_windows`` is set (label, dropped_in_lookback, dropped_after), the
    bar panel compares those two windows instead of mixing drop counts with
    replica/action counts.
    """
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=False)
    ax_drop, ax_rep, ax_bar = axes

    _draw_cold_start_span(ax_drop, cold_start_until)
    _draw_cold_start_span(ax_rep, cold_start_until, legend=False)
    for label, tau, dropped, replicas in series:
        ax_drop.plot(tau, dropped, label=label, linewidth=2)
        ax_rep.plot(tau, replicas, label=label, linewidth=2, drawstyle="steps-post")
    ax_drop.set_ylabel("dropped requests")
    ax_drop.set_title(title)
    ax_drop.grid(True, alpha=0.3)
    _legend(ax_drop)
    _ylim_from_zero(ax_drop)
    ax_rep.set_xlabel("time_unit")
    ax_rep.set_ylabel("live replicas")
    ax_rep.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax_rep.grid(True, alpha=0.3)
    _legend(ax_rep)
    _ylim_from_zero(ax_rep)

    if drop_windows:
        labels = [row[0] for row in drop_windows]
        x = list(range(len(labels)))
        width = 0.35
        before = [row[1] for row in drop_windows]
        after = [row[2] for row in drop_windows]
        w = int(cold_start_until or 0)
        ax_bar.bar(
            [i - width / 2 for i in x],
            before,
            width=width,
            label=f"dropped τ≤{w}" if w else "dropped (lookback)",
            color="#9e9e9e",
        )
        ax_bar.bar(
            [i + width / 2 for i in x],
            after,
            width=width,
            label=f"dropped τ≥{w + 1}" if w else "dropped (after forecast on)",
            color="#d62728",
        )
    else:
        labels = [row[0] for row in totals]
        x = list(range(len(labels)))
        width = 0.25
        drops = [row[1] for row in totals]
        max_rep = [row[2] for row in totals]
        n_act = [float(row[3]) for row in totals]
        ax_bar.bar([i - width for i in x], drops, width=width, label="total dropped")
        ax_bar.bar(x, max_rep, width=width, label="peak replicas")
        ax_bar.bar([i + width for i in x], n_act, width=width, label="OK actions")
    ax_bar.set_xticks(x)
    ax_bar.set_xticklabels(labels)
    ax_bar.set_ylabel("count")
    ax_bar.grid(True, axis="y", alpha=0.3)
    _legend(ax_bar, ncol=3)
    _save(fig, out_path)


_STORY_COLORS = {
    "incoming": "#222222",
    "oracle": "#1f77b4",
    "sweet": "#ff7f0e",
    "hat1": "#1f77b4",
    "hat5": "#ff7f0e",
    "reactive_local": "#d62728",
    "proactive_tcn": "#2ca02c",
}


def _story_color(label: str, fallback_index: int) -> str:
    if label in _STORY_COLORS:
        return _STORY_COLORS[label]
    cycle = ("#d62728", "#2ca02c", "#1f77b4", "#ff7f0e", "#9467bd", "#8c564b")
    return cycle[fallback_index % len(cycle)]


def plot_story_serve_capacity(
    *,
    tau: list[int],
    incoming: list[float],
    mu_by_label: list[tuple[str, list[float]]],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    _draw_cold_start_span(ax, cold_start_until)
    ax.plot(tau, incoming, label="incoming (trace)", color=_STORY_COLORS["incoming"], linewidth=2.2)
    for i, (label, mu) in enumerate(mu_by_label):
        ax.plot(
            tau,
            mu,
            label=f"{label} serve μ",
            color=_story_color(label, i),
            linewidth=1.8,
            drawstyle="steps-post",
        )
    ax.set_xlabel("time_unit")
    ax.set_ylabel("requests / min")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    _legend(ax, ncol=2)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_story_cpu(
    *,
    tau: list[int],
    cpu_oracle: list[float],
    cpu_sweet: list[float],
    cpu_by_label: list[tuple[str, list[float]]],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    _draw_cold_start_span(ax, cold_start_until)
    ax.plot(
        tau,
        cpu_oracle,
        label="CPU to serve all (oracle)",
        color=_STORY_COLORS["oracle"],
        linewidth=1.8,
    )
    ax.plot(
        tau,
        cpu_sweet,
        label="CPU at 60% target (sweet spot)",
        color=_STORY_COLORS["sweet"],
        linewidth=1.6,
        linestyle="--",
    )
    for i, (label, cpu) in enumerate(cpu_by_label):
        ax.plot(
            tau,
            cpu,
            label=f"{label} provided",
            color=_story_color(label, i),
            linewidth=1.8,
            drawstyle="steps-post",
        )
    ax.set_xlabel("time_unit")
    ax.set_ylabel("CPU cores")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    _legend(ax, ncol=2)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_story_dropped(
    *,
    tau: list[int],
    dropped_by_label: list[tuple[str, list[float]]],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    _draw_cold_start_span(ax, cold_start_until)
    for i, (label, dropped) in enumerate(dropped_by_label):
        ax.plot(tau, dropped, label=f"{label} dropped", color=_story_color(label, i), linewidth=1.8)
    ax.set_xlabel("time_unit")
    ax.set_ylabel("dropped requests")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    _legend(ax)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_story_replicas(
    *,
    tau: list[int],
    replicas_by_label: list[tuple[str, list[float]]],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    _draw_cold_start_span(ax, cold_start_until)
    for i, (label, replicas) in enumerate(replicas_by_label):
        ax.plot(
            tau,
            replicas,
            label=f"{label} replicas",
            color=_story_color(label, i),
            linewidth=1.8,
            drawstyle="steps-post",
        )
    ax.set_xlabel("time_unit")
    ax.set_ylabel("live replicas")
    ax.set_title(title)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)
    _legend(ax)
    _ylim_from_zero(ax)
    _save(fig, out_path)


def plot_story_overview(
    *,
    tau: list[int],
    incoming: list[float],
    mu_by_label: list[tuple[str, list[float]]],
    cpu_oracle: list[float],
    cpu_sweet: list[float],
    cpu_by_label: list[tuple[str, list[float]]],
    hat1: list[float] | None,
    hat5: list[float] | None,
    dropped_by_label: list[tuple[str, list[float]]],
    replicas_by_label: list[tuple[str, list[float]]],
    out_path: Path,
    title: str,
    cold_start_until: int | None = None,
) -> None:
    n_rows = 5 if hat1 is not None else 4
    fig, axes = plt.subplots(
        n_rows,
        1,
        figsize=(11, 3.1 * n_rows),
        sharex=True,
        gridspec_kw={"hspace": 0.18},
    )
    ax_mu, ax_cpu, *rest = axes
    if hat1 is not None:
        ax_hat, ax_drop, ax_rep = rest
    else:
        ax_hat = None
        ax_drop, ax_rep = rest

    _draw_cold_start_span(ax_mu, cold_start_until)
    ax_mu.plot(tau, incoming, label="incoming (trace)", color=_STORY_COLORS["incoming"], linewidth=2.0)
    for i, (label, mu) in enumerate(mu_by_label):
        ax_mu.plot(
            tau,
            mu,
            label=f"{label} serve μ",
            color=_story_color(label, i),
            linewidth=1.6,
            drawstyle="steps-post",
        )
    ax_mu.set_ylabel("requests / min")
    ax_mu.set_title(title)
    ax_mu.grid(True, alpha=0.3)
    _legend(ax_mu, ncol=2)
    _ylim_from_zero(ax_mu)

    _draw_cold_start_span(ax_cpu, cold_start_until, legend=False)
    ax_cpu.plot(tau, cpu_oracle, label="CPU to serve all (oracle)", color=_STORY_COLORS["oracle"], linewidth=1.6)
    ax_cpu.plot(
        tau,
        cpu_sweet,
        label="CPU at 60% target",
        color=_STORY_COLORS["sweet"],
        linewidth=1.4,
        linestyle="--",
    )
    for i, (label, cpu) in enumerate(cpu_by_label):
        ax_cpu.plot(
            tau,
            cpu,
            label=f"{label} provided",
            color=_story_color(label, i),
            linewidth=1.6,
            drawstyle="steps-post",
        )
    ax_cpu.set_ylabel("CPU cores")
    ax_cpu.grid(True, alpha=0.3)
    _legend(ax_cpu, ncol=2)
    _ylim_from_zero(ax_cpu)

    if ax_hat is not None and hat1 is not None and hat5 is not None:
        _draw_cold_start_span(ax_hat, cold_start_until, legend=False)
        ax_hat.plot(tau, incoming, label="incoming", color=_STORY_COLORS["incoming"], linewidth=2.0)
        ax_hat.plot(tau, hat1, label="TCN t+1", color=_STORY_COLORS["hat1"], linewidth=1.5)
        ax_hat.plot(tau, hat5, label="TCN t+5", color=_STORY_COLORS["hat5"], linewidth=1.3, linestyle="--")
        ax_hat.set_ylabel("requests / min")
        ax_hat.grid(True, alpha=0.3)
        _legend(ax_hat, ncol=3)
        _ylim_from_zero(ax_hat)

    _draw_cold_start_span(ax_drop, cold_start_until, legend=False)
    for i, (label, dropped) in enumerate(dropped_by_label):
        ax_drop.plot(tau, dropped, label=f"{label} dropped", color=_story_color(label, i), linewidth=1.6)
    ax_drop.set_ylabel("dropped")
    ax_drop.grid(True, alpha=0.3)
    _legend(ax_drop)
    _ylim_from_zero(ax_drop)

    _draw_cold_start_span(ax_rep, cold_start_until, legend=False)
    for i, (label, replicas) in enumerate(replicas_by_label):
        ax_rep.plot(
            tau,
            replicas,
            label=f"{label} replicas",
            color=_story_color(label, i),
            linewidth=1.6,
            drawstyle="steps-post",
        )
    ax_rep.set_xlabel("time_unit")
    ax_rep.set_ylabel("replicas")
    ax_rep.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax_rep.grid(True, alpha=0.3)
    _legend(ax_rep)
    _ylim_from_zero(ax_rep)
    _save(fig, out_path)
