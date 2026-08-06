"""Compare trace input with run logs and plot request/served/dropped lines."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


def read_trace(path: Path) -> tuple[list[int], list[float]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    t = [int(r["time_unit"]) for r in rows]
    req = [float(r["requests"]) for r in rows]
    return t, req


def read_log(path: Path) -> tuple[list[int], list[float], list[float], list[float]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    t = [int(r["time_unit"]) for r in rows]
    incoming = [float(r["incoming_requests"]) for r in rows]
    served = [float(r["served_requests"]) for r in rows]
    dropped = [float(r["dropped_requests"]) for r in rows]
    return t, incoming, served, dropped


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare input trace against container log.")
    parser.add_argument("--trace", required=True, type=Path, help="Path to trace CSV (time_unit,requests)")
    parser.add_argument("--log", required=True, type=Path, help="Path to container log CSV")
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Path to output PNG graph",
    )
    args = parser.parse_args()

    tau_trace, trace_requests = read_trace(args.trace)
    tau_log, incoming, served, dropped = read_log(args.log)

    if tau_trace != tau_log:
        raise ValueError("time_unit mismatch between trace and log")

    max_abs_diff = max(abs(a - b) for a, b in zip(trace_requests, incoming))
    if max_abs_diff > 1e-9:
        raise ValueError(f"trace vs incoming mismatch, max abs diff={max_abs_diff}")

    # Consistency check: incoming must equal served + dropped for every tick.
    residual_max = max(abs(i - (s + d)) for i, s, d in zip(incoming, served, dropped))
    if residual_max > 1e-9:
        raise ValueError(f"incoming != served+dropped, max residual={residual_max}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(11, 5))
    plt.plot(tau_trace, trace_requests, label="trace requests", linewidth=2)
    plt.plot(tau_log, incoming, label="log incoming requests", linestyle="--", linewidth=2)
    plt.plot(tau_log, served, label="served requests", linewidth=2)
    plt.plot(tau_log, dropped, label="dropped requests", linewidth=2)
    plt.xlabel("time_unit")
    plt.ylabel("requests")
    plt.title("Trace vs Container Log (60 ticks)")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(args.out, dpi=150)

    total_in = sum(incoming)
    total_served = sum(served)
    total_dropped = sum(dropped)
    drop_rate = (total_dropped / total_in * 100.0) if total_in > 0 else 0.0

    print(f"ticks={len(tau_log)}")
    print(f"max_abs_diff(trace,incoming)={max_abs_diff:.6f}")
    print(f"max_abs_residual(incoming-served-dropped)={residual_max:.6f}")
    print(f"total_incoming={total_in:.2f}")
    print(f"total_served={total_served:.2f}")
    print(f"total_dropped={total_dropped:.2f}")
    print(f"drop_rate_percent={drop_rate:.2f}")
    print(f"plot={args.out}")


if __name__ == "__main__":
    main()
