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


def _ylim_from_zero(ax) -> None:
    _, hi = ax.get_ylim()
    ax.set_ylim(0.0, hi if hi > 0.0 else 1.0)


def _draw_action_markers(ax, markers: dict[str, list[int]]) -> None:
    seen: set[str] = set()
    for family, ticks in markers.items():
        style = _FAMILY_STYLE.get(family, {"color": "black", "linestyle": ":"})
        for t in ticks:
            label = family if family not in seen else None
            ax.axvline(
                t,
                color=style["color"],
                linestyle=style["linestyle"],
                alpha=0.45,
                linewidth=1.0,
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
    if containers and all(c.tau == tau for c in containers):
        total_incoming = sum_series([c.incoming for c in containers])
        total_served = sum_series([c.served for c in containers])
        total_dropped = sum_series([c.dropped for c in containers])
    else:
        total_incoming = sum_aligned(tau, containers, "incoming")
        total_served = sum_aligned(tau, containers, "served")
        total_dropped = sum_aligned(tau, containers, "dropped")

    plt.figure(figsize=(11, 5))
    plt.plot(tau, trace_requests, label="trace requests", linewidth=2.5)
    plt.plot(tau, total_incoming, label="sum incoming", linestyle="--", linewidth=2)
    plt.plot(tau, total_served, label="sum served", linewidth=2)
    plt.plot(tau, total_dropped, label="sum dropped", linewidth=2)
    for c in containers:
        plt.plot(c.tau, c.incoming, label=f"{c.container_id} incoming", linewidth=1.2, alpha=0.75)
    plt.xlabel("time_unit")
    plt.ylabel("requests")
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.legend()
    _ylim_from_zero(plt.gca())
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_cpu(container: ContainerSeries, out_path: Path) -> None:
    plt.figure(figsize=(11, 5))
    plt.plot(
        container.tau,
        container.cpu_used,
        label="cpu usage (cores)",
        linewidth=2,
        drawstyle="steps-post",
        zorder=3,
    )
    plt.plot(
        container.tau,
        container.cpu_capacity,
        label="cpu alloc (cores)",
        linewidth=2,
        linestyle="--",
        drawstyle="steps-post",
        zorder=2,
    )
    plt.xlabel("time_unit")
    plt.ylabel("cpu cores")
    plt.title(f"{container.container_id}: CPU alloc vs usage")
    plt.grid(True, alpha=0.3)
    plt.legend()
    _ylim_from_zero(plt.gca())
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_ram(container: ContainerSeries, out_path: Path) -> None:
    plt.figure(figsize=(11, 5))
    plt.plot(
        container.tau,
        container.ram_used,
        label="ram usage (MB)",
        linewidth=2,
        drawstyle="steps-post",
        zorder=3,
    )
    plt.plot(
        container.tau,
        container.ram_capacity,
        label="ram alloc (MB)",
        linewidth=2,
        linestyle="--",
        drawstyle="steps-post",
        zorder=2,
    )
    plt.xlabel("time_unit")
    plt.ylabel("ram MB")
    plt.title(f"{container.container_id}: RAM alloc vs usage")
    plt.grid(True, alpha=0.3)
    plt.legend()
    _ylim_from_zero(plt.gca())
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


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
    ax_load.legend(loc="upper left")
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
    _draw_action_markers(ax_cpu, markers)
    ax_cpu.legend(loc="upper left")
    _ylim_from_zero(ax_cpu)

    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


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
    _draw_action_markers(ax, markers)
    ax.set_xlabel("time_unit")
    ax.set_ylabel("live replicas")
    ax.set_title(title)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.grid(True, alpha=0.3)
    ax.legend()
    _ylim_from_zero(ax)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


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
    ax_drop.legend()
    _ylim_from_zero(ax_drop)
    ax_rep.set_xlabel("time_unit")
    ax_rep.set_ylabel("live replicas")
    ax_rep.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax_rep.grid(True, alpha=0.3)
    ax_rep.legend()
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
    ax_bar.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
