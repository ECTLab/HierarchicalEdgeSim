"""Hierarchy figure: edge cores stay at the seed, cloud cores take the rest."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
RUN = sorted((ROOT / "results" / "ikt-hierarchy" / "edge-cloud").glob("42_*"))[-1]
OUT = ROOT / "results" / "ikt-hierarchy" / "ms588_edge_cloud.pdf"


def series() -> tuple[dict[int, float], dict[int, float], dict[int, float]]:
    offered: dict[int, float] = defaultdict(float)
    edge: dict[int, float] = defaultdict(float)
    cloud: dict[int, float] = defaultdict(float)
    for meta_path in RUN.rglob("*.meta.json"):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        log = Path(str(meta_path).replace(".meta.json", ".log.csv"))
        bucket = cloud if meta["cluster_id"] == "cloud" else edge
        with log.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                minute = int(float(row["time_unit"]))
                offered[minute] += float(row["incoming_requests"])
                bucket[minute] += float(row["cpu_core_capacity"])
    return offered, edge, cloud


def main() -> None:
    offered, edge, cloud = series()
    minutes = list(range(1, 722))
    load = [offered[minute] for minute in minutes]
    peak = max(minutes, key=lambda minute: offered[minute])

    plt.rcParams.update(
        {
            "font.family": "serif",
            "font.size": 8,
            "axes.labelsize": 8,
            "legend.fontsize": 7,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )
    fig, (ax_load, ax_cores) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(3.45, 2.55),
        gridspec_kw={"height_ratios": [1.0, 1.15], "hspace": 0.08},
    )
    ax_load.plot(minutes, load, color="0.15", linewidth=0.7)
    ax_load.set_ylabel("Requests/min")
    ax_load.set_ylim(0, 32000)
    ax_load.axvline(peak, color="0.45", linewidth=0.6, linestyle=":")
    ax_load.tick_params(labelbottom=False)

    ax_cores.plot(minutes, [edge[minute] for minute in minutes], color="0.55", linewidth=0.9, label="Edge")
    ax_cores.plot(
        minutes,
        [cloud[minute] for minute in minutes],
        color="0.15",
        linewidth=1.0,
        linestyle="--",
        label="Cloud",
    )
    ax_cores.axvline(peak, color="0.45", linewidth=0.6, linestyle=":")
    ax_cores.set_ylabel("Allocated cores")
    ax_cores.set_xlabel("Minute")
    ax_cores.set_xlim(1, 721)
    ax_cores.set_ylim(0, 12)
    ax_cores.legend(
        frameon=False,
        ncol=2,
        loc="upper center",
        handlelength=1.8,
        columnspacing=0.8,
        borderaxespad=0.2,
    )

    fig.subplots_adjust(left=0.17, right=0.98, top=0.98, bottom=0.16, hspace=0.12)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT)
    fig.savefig(OUT.with_suffix(".png"), dpi=200)
    print(f"peak_minute={peak} offered={offered[peak]:.0f}")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
