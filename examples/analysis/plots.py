"""Plotting helpers for request / CPU / RAM diagnostics."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from .aggregate import sum_series
from .io import ActionEvent, ContainerSeries


def plot_combined_requests(
    *,
    tau: list[int],
    trace_requests: list[float],
    containers: list[ContainerSeries],
    out_path: Path,
    title: str,
) -> None:
    total_incoming = sum_series([c.incoming for c in containers])
    total_served = sum_series([c.served for c in containers])
    total_dropped = sum_series([c.dropped for c in containers])

    plt.figure(figsize=(11, 5))
    plt.plot(tau, trace_requests, label="trace requests", linewidth=2.5)
    plt.plot(tau, total_incoming, label="sum incoming", linestyle="--", linewidth=2)
    plt.plot(tau, total_served, label="sum served", linewidth=2)
    plt.plot(tau, total_dropped, label="sum dropped", linewidth=2)
    for c in containers:
        plt.plot(tau, c.incoming, label=f"{c.container_id} incoming", linewidth=1.2, alpha=0.75)
    plt.xlabel("time_unit")
    plt.ylabel("requests")
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_cpu(container: ContainerSeries, out_path: Path) -> None:
    plt.figure(figsize=(11, 5))
    plt.plot(container.tau, container.cpu_capacity, label="cpu capacity (cores)", linewidth=2)
    plt.plot(container.tau, container.cpu_used, label="cpu usage (cores)", linewidth=2)
    plt.xlabel("time_unit")
    plt.ylabel("cpu cores")
    plt.title(f"{container.container_id}: CPU Capacity vs Usage")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_ram(container: ContainerSeries, out_path: Path) -> None:
    plt.figure(figsize=(11, 5))
    plt.plot(container.tau, container.ram_capacity, label="ram capacity (MB)", linewidth=2)
    plt.plot(container.tau, container.ram_used, label="ram usage (MB)", linewidth=2)
    plt.xlabel("time_unit")
    plt.ylabel("ram MB")
    plt.title(f"{container.container_id}: RAM Capacity vs Usage")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    plt.close()


def plot_scaling_decisions(
    *,
    containers: list[ContainerSeries],
    actions: list[ActionEvent],
    out_path: Path,
    title: str,
    ttw_ticks: int | None = None,
    rps_obs: list[tuple[int, float]] | None = None,
) -> None:
    """Multi-panel view: optional RPS, CPU/RAM alloc, and vertical scale markers."""
    if not containers:
        return

    tau = containers[0].tau
    # Fleet alloc = sum over containers in this MS/app slice
    cpu_alloc = sum_series([c.cpu_capacity for c in containers])
    ram_alloc = sum_series([c.ram_capacity for c in containers])
    cpu_used = sum_series([c.cpu_used for c in containers])
    ram_used = sum_series([c.ram_used for c in containers])

    ms_ids = {c.microservice_id for c in containers}
    relevant = [
        a
        for a in actions
        if a.action_type == "resize"
        and (not a.ms_id or a.ms_id in ms_ids)
        and a.result_code == "OK"
    ]
    ups = [a for a in relevant if "up" in a.reason]
    downs = [a for a in relevant if "down" in a.reason]
    need_h = [a for a in actions if a.action_type == "need_horizontal" and (not a.ms_id or a.ms_id in ms_ids)]

    n_rows = 3 if rps_obs else 2
    fig, axes = plt.subplots(n_rows, 1, figsize=(12, 3.2 * n_rows), sharex=True)
    if n_rows == 1:
        axes = [axes]

    row = 0
    if rps_obs:
        ax = axes[row]
        xs = [t for t, _ in rps_obs]
        ys = [v for _, v in rps_obs]
        if ttw_ticks and ttw_ticks > 1:
            # Place TTW samples at end of window (tau = ttw * ttw_ticks) when possible
            ax.plot(xs, ys, color="black", linewidth=1.8, label="observed RPS (TTW)")
        else:
            ax.plot(xs, ys, color="black", linewidth=1.8, label="observed RPS")
        ax.set_ylabel("RPS")
        ax.set_title(f"{title}: load")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right")
        row += 1

    ax_cpu = axes[row]
    ax_cpu.plot(tau, cpu_alloc, label="CPU alloc (cores)", color="tab:blue", linewidth=2)
    ax_cpu.plot(tau, cpu_used, label="CPU used (cores)", color="tab:cyan", linewidth=1.4, alpha=0.85)
    _mark_resizes(ax_cpu, ups, downs, value_from="cpu")
    ax_cpu.set_ylabel("CPU cores")
    ax_cpu.set_title(f"{title}: CPU capacity & scaling decisions")
    ax_cpu.grid(True, alpha=0.3)
    ax_cpu.legend(loc="upper right")
    row += 1

    ax_ram = axes[row]
    ax_ram.plot(tau, ram_alloc, label="RAM alloc (MB)", color="tab:orange", linewidth=2)
    ax_ram.plot(tau, ram_used, label="RAM used (MB)", color="tab:red", linewidth=1.4, alpha=0.75)
    _mark_resizes(ax_ram, ups, downs, value_from="ram")
    if need_h:
        for a in need_h:
            ax_ram.axvline(a.tau, color="tab:purple", alpha=0.35, linestyle=":")
        ax_ram.plot([], [], color="tab:purple", linestyle=":", label="need_horizontal")
    ax_ram.set_xlabel("time_unit (tick)")
    ax_ram.set_ylabel("RAM MB")
    ax_ram.set_title(f"{title}: RAM capacity & scaling decisions")
    ax_ram.grid(True, alpha=0.3)
    ax_ram.legend(loc="upper right")

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _mark_resizes(ax, ups: list[ActionEvent], downs: list[ActionEvent], *, value_from: str) -> None:
    def _y(a: ActionEvent) -> float | None:
        if value_from == "cpu":
            return a.cpu_new
        return a.ram_new

    up_pts = [(a.tau, y) for a in ups if (y := _y(a)) is not None]
    down_pts = [(a.tau, y) for a in downs if (y := _y(a)) is not None]
    if up_pts:
        ax.scatter(
            [t for t, _ in up_pts],
            [y for _, y in up_pts],
            marker="^",
            s=90,
            color="tab:green",
            zorder=5,
            label=f"scale up ({len(up_pts)})",
        )
    if down_pts:
        ax.scatter(
            [t for t, _ in down_pts],
            [y for _, y in down_pts],
            marker="v",
            s=90,
            color="tab:red",
            zorder=5,
            label=f"scale down ({len(down_pts)})",
        )
