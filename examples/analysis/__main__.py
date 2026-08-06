"""CLI: python -m analysis <run_dir>  (from examples/) or via compare_trace_vs_log.py."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python -m analysis ...` when cwd/examples is on sys.path, and also
# `python examples/compare_trace_vs_log.py` importing analysis as a sibling package.
_EXAMPLES_DIR = Path(__file__).resolve().parents[1]
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))

from analysis.report import analyze_run  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze a simulation run directory. Writes per-application plots under "
            "<run_dir>/analysis/<app_id>/."
        )
    )
    parser.add_argument(
        "run_dir",
        type=Path,
        help="Results run directory, e.g. results/42_20260806T101439Z",
    )
    parser.add_argument(
        "--app",
        action="append",
        default=None,
        help="Optional app id filter; may be repeated. Default: all apps in the run.",
    )
    args = parser.parse_args(argv)

    apps_filter = set(args.app) if args.app else None
    summaries = analyze_run(args.run_dir, apps_filter=apps_filter)

    print(f"run_dir={args.run_dir.resolve()}")
    print(f"apps_analyzed={len(summaries)}")
    for s in summaries:
        drop_rate = (s.total_dropped / s.total_incoming * 100.0) if s.total_incoming else 0.0
        print(f"[app={s.app_id}]")
        print(f"  containers={s.container_ids}")
        print(f"  ticks={s.ticks}")
        print(f"  max_abs_diff(trace,sum_incoming)={s.max_abs_diff_trace_vs_incoming:.6f}")
        print(f"  total_incoming={s.total_incoming:.2f}")
        print(f"  total_served={s.total_served:.2f}")
        print(f"  total_dropped={s.total_dropped:.2f}")
        print(f"  drop_rate_percent={drop_rate:.2f}")
        print(f"  output_dir={s.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
