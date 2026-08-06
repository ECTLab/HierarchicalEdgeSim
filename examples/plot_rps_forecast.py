"""Plot RPS observations vs multi-lead forecasts from rps_forecast.csv.

Usage:
  .venv/bin/python examples/run_with_autoscaler.py configs/demo_300_proactive_auto_scaler.yaml
  .venv/bin/python examples/plot_rps_forecast.py results/proactive_300/<run_id>
  .venv/bin/python examples/plot_rps_forecast.py results/proactive_300/<run_id> --ms api
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _to_float(val: str) -> float | None:
    if val is None or val == "":
        return None
    return float(val)


def plot_ms(rows: list[dict[str, str]], ms_id: str, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ms_rows = [r for r in rows if r["ms_id"] == ms_id]
    if not ms_rows:
        raise SystemExit(f"no rows for ms_id={ms_id!r}")

    obs_ttw: list[int] = []
    obs_r: list[float] = []
    # lead -> {target_ttw: r_hat}
    by_lead: dict[int, dict[int, float]] = defaultdict(dict)

    for r in ms_rows:
        lead = int(r["lead"])
        if lead == 0:
            rt = _to_float(r["r_t"])
            if rt is None:
                continue
            obs_ttw.append(int(r["ttw"]))
            obs_r.append(rt)
        else:
            rh = _to_float(r["r_hat"])
            if rh is None:
                continue
            by_lead[lead][int(r["target_ttw"])] = rh

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    ax0 = axes[0]
    ax0.plot(obs_ttw, obs_r, label="observed r_t (lead=0)", color="black", linewidth=2.0)
    # Overlay one-step forecast aligned to target_ttw (when that TTW's truth exists)
    if 1 in by_lead:
        xs = sorted(t for t in by_lead[1] if t in set(obs_ttw))
        ys = [by_lead[1][t] for t in xs]
        ax0.plot(xs, ys, label="forecast lead=1 @ target_ttw", linestyle="--", linewidth=1.8)
    if max(by_lead, default=0) >= 3 and 3 in by_lead:
        xs = sorted(t for t in by_lead[3] if t in set(obs_ttw))
        ys = [by_lead[3][t] for t in xs]
        ax0.plot(xs, ys, label="forecast lead=3 @ target_ttw", linestyle=":", linewidth=1.6, alpha=0.9)
    ax0.set_ylabel("RPS")
    ax0.set_title(f"{ms_id}: observed RPS vs forecasts (aligned to target_ttw)")
    ax0.grid(True, alpha=0.3)
    ax0.legend()

    # One-step absolute error where both exist
    ax1 = axes[1]
    if 1 in by_lead:
        obs_map = dict(zip(obs_ttw, obs_r, strict=True))
        err_x: list[int] = []
        err_y: list[float] = []
        for t, hat in sorted(by_lead[1].items()):
            if t in obs_map:
                err_x.append(t)
                err_y.append(abs(hat - obs_map[t]))
        ax1.plot(err_x, err_y, label="|r_hat(lead=1) - r_t|", color="tab:red", linewidth=1.5)
    ax1.set_xlabel("ttw (target)")
    ax1.set_ylabel("abs error")
    ax1.set_title(f"{ms_id}: one-step absolute forecast error")
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot rps_forecast.csv observations vs leads.")
    parser.add_argument("run_dir", type=Path, help="Results run directory containing rps_forecast.csv")
    parser.add_argument("--ms", action="append", default=None, help="Microservice id (repeatable). Default: all.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for plots (default: <run_dir>/analysis/rps_forecast)",
    )
    args = parser.parse_args(argv)

    csv_path = args.run_dir / "rps_forecast.csv"
    if not csv_path.is_file():
        raise SystemExit(f"missing {csv_path}")

    rows = _load_rows(csv_path)
    ms_ids = sorted({r["ms_id"] for r in rows})
    if args.ms:
        wanted = set(args.ms)
        missing = wanted - set(ms_ids)
        if missing:
            raise SystemExit(f"ms ids not in CSV: {sorted(missing)}")
        ms_ids = sorted(wanted)

    out_dir = args.out_dir or (args.run_dir / "analysis" / "rps_forecast")
    for ms_id in ms_ids:
        out_path = out_dir / f"{ms_id}_rps_forecast.png"
        plot_ms(rows, ms_id, out_path)
        print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
