"""Post-run analysis: compare traces to container logs and emit plots."""

from .report import analyze_run

__all__ = ["analyze_run"]
