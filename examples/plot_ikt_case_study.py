"""Case-study figure: offered load and allocated cores for the IKT paper."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "results" / "ikt-case-study"
OUT = RUNS / "ms588_cores.pdf"


def series(policy: str) -> tuple[list[int], dict[int, float], dict[int, float]]:
    run = sorted((RUNS / policy).glob("42_*"))[-1]
    offered: dict[int, float] = defaultdict(float)
    cores: dict[int, float] = defaultdict(float)
    for log in run.rglob("*.log.csv"):
        with log.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                minute = int(float(row["time_unit"]))
                offered[minute] += float(row["incoming_requests"])
                cores[minute] += float(row["cpu_core_capacity"])
    minutes = list(range(1, 722))
    return minutes, offered, cores


def main() -> None:
    minutes, offered, _ = series("static")
    _, _, vertical = series("vertical")
    _, _, hpa = series("hpa")
    _, _, static_cores = series("static")
    load = [offered[m] for m in minutes]
    peak = max(minutes, key=lambda m: offered[m])

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

    ax_cores.plot(minutes, [static_cores[m] for m in minutes], color="0.55", linewidth=0.9, label="Static")
    ax_cores.plot(
        minutes,
        [vertical[m] for m in minutes],
        color="0.15",
        linewidth=0.9,
        linestyle="--",
        label="Vertical",
    )
    ax_cores.plot(minutes, [hpa[m] for m in minutes], color="0.15", linewidth=1.0, label="HPA")
    ax_cores.axvline(peak, color="0.45", linewidth=0.6, linestyle=":")
    ax_cores.set_ylabel("Allocated cores")
    ax_cores.set_xlabel("Minute")
    ax_cores.set_xlim(1, 721)
    ax_cores.set_ylim(0, 14)
    ax_cores.legend(
        frameon=False,
        ncol=3,
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
