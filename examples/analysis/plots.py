"""Plotting helpers for request / CPU / RAM diagnostics."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from .aggregate import sum_series
from .io import ContainerSeries


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
