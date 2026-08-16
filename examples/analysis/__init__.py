"""Post-run analysis: compare traces to container logs and emit plots."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .compare import compare_runs
    from .report import analyze_run

__all__ = ["analyze_run", "compare_runs"]


def __getattr__(name: str):
    if name == "analyze_run":
        from .report import analyze_run

        return analyze_run
    if name == "compare_runs":
        from .compare import compare_runs

        return compare_runs
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
