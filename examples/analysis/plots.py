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
    "BEV up": {"color": "#1f77b4", "linestyle": "--"},
    "BEV down": {"color": "#17becf", "linestyle": ":"},
    "BEH spawn": {"color": "#ff7f0e", "linestyle": "--"},
    "BEH terminate": {"color": "#ffbb78", "linestyle": ":"},
    "vicinity": {"color": "#2ca02c", "linestyle": "-."},
    "BEG": {"color": "#d62728", "linestyle": "-."},
    "cascade": {"color": "#9467bd", "linestyle": ":"},
    "escalate": {"color": "#7f7f7f", "linestyle": ":"},
}

_ROUTING_TOP_N = 6


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


def _draw_action_markers(ax, markers: dict[str, list[int]], *, legend: bool = True) -> None:
    seen: set[str] = set()
    for family, ticks in markers.items():
        style = _FAMILY_STYLE.get(family, {"color": "black", "linestyle": ":"})
        for t in ticks:
            label = family if legend and family not in seen else None
            ax.axvline(
                t,
                color=style["color"],
                linestyle=style["linestyle"],
                alpha=0.35,
                linewidth=0.9,
                label=label,
            )
            if label:
                seen.add(family)


def plot_combined_requests(
    *,
    tau: list[int],
    trace_requests: list[float],
    containers: list[ContainerSeries],
    out_path: Path,
    title: str,
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
    ax.plot(tau, trace_requests, label="trace", linewidth=2.4, color="#222222")
    ax.plot(tau, total_incoming, label="sum incoming", linestyle="--", linewidth=1.8, color="#1f77b4")
    ax.plot(tau, total_served, label="sum served", linewidth=1.8, color="#2ca02c")
    ax.plot(tau, total_dropped, label="sum dropped", linewidth=1.8, color="#d62728")
    ax.set_xlabel("time_unit")
    ax.set_ylabel("requests")
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
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
) -> None:
    fig, (ax_load, ax_cpu) = plt.subplots(
        2,
        1,
        figsize=(11, 7.5),
        sharex=True,
        gridspec_kw={"height_ratios": [2.0, 1.0]},
    )
    ax_load.plot(tau, incoming, label="incoming", linewidth=2)
    ax_load.plot(tau, dropped, label="dropped", color="#d62728", linewidth=1.8)
    ax_load.set_ylabel("requests")
    ax_load.set_title(title)
    ax_load.grid(True, alpha=0.3)
    _draw_action_markers(ax_load, markers)
    _legend(ax_load, ncol=3)
    _ylim_from_zero(ax_load)

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


def plot_replica_sites(
    *,
    tau: list[int],
    counts: dict[str, list[float]],
    markers: dict[str, list[int]],
    out_path: Path,
    title: str,
) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    order = [s for s in ("home", "vicinity", "global", "remote") if s in counts]
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
) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(tau, actual_counts, label="observed incoming", color="#222222", linewidth=2.0)
    ax.plot(tau, pred_step1, label="TCN t+1", color="#1f77b4", linewidth=1.6)
    ax.plot(tau, pred_horizon, label="TCN t+5", color="#ff7f0e", linewidth=1.4, linestyle="--")
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
) -> None:
    """series: (label, tau, dropped, replica_count). totals: (label, sum_drop, max_replicas, n_ok_actions)."""
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=False)
    ax_drop, ax_rep, ax_bar = axes

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
