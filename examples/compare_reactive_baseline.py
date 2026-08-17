#!/usr/bin/env python3
"""Compare two or more run directories (same trace, different scalers)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_EXAMPLES_DIR = Path(__file__).resolve().parent
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))

from analysis.compare import compare_runs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plot dropped load, replica count, and action totals across labeled runs."
    )
    parser.add_argument(
        "--run",
        nargs=2,
        metavar=("LABEL", "RUN_DIR"),
        action="append",
        required=True,
        help="Label and results directory; repeat (e.g. --run off DIR --run vertical DIR --run local DIR).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output PNG (default: <first_run_dir>/analysis/baseline_comparison.png)",
    )
    parser.add_argument("--app", default=None, help="Optional app id filter")
    parser.add_argument("--ms", default=None, help="Optional microservice id filter")
    args = parser.parse_args(argv)

    labeled = [(label, Path(path)) for label, path in args.run]
    out = args.out
    if out is None:
        out = labeled[0][1].resolve() / "analysis" / "baseline_comparison.png"
    path = compare_runs(labeled, out_path=out, app_id=args.app, ms_id=args.ms)
    print(f"wrote {path}")
    story = path.parent / "story"
    if story.is_dir():
        print(f"story plots: {story}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
