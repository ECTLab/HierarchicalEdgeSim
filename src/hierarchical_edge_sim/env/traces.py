"""Trace loading and 1-based access for Part A."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from .config import WorldSpec, resolve_traces_dir


@dataclass(slots=True)
class TraceStore:
    """In-memory trace table keyed by microservice id."""

    _data: dict[str, list[float]]

    def get(self, ms_id: str, tau: int) -> float:
        """Return trace requests for microservice at 1-based tick tau."""
        if tau < 1:
            raise IndexError(f"tau must be >= 1, got {tau}")
        if ms_id not in self._data:
            raise KeyError(f"unknown microservice id '{ms_id}'")
        series = self._data[ms_id]
        if tau > len(series):
            raise IndexError(f"tau={tau} out of range for ms '{ms_id}' with N={len(series)}")
        return series[tau - 1]

    @property
    def horizon(self) -> int:
        """Return number of ticks N represented by each microservice series."""
        if not self._data:
            return 0
        first_series = next(iter(self._data.values()))
        return len(first_series)


def load_traces(world_spec: WorldSpec) -> TraceStore:
    """Load all microservice traces from disk after validation succeeds."""
    traces_dir = resolve_traces_dir(world_spec.traces_dir, world_spec.source_path)
    data: dict[str, list[float]] = {}

    for app in world_spec.apps:
        for microservice in app.microservices:
            trace_path = traces_dir / microservice.trace_file
            data[microservice.id] = _read_requests_column(trace_path)

    return TraceStore(_data=data)


def _read_requests_column(path: Path) -> list[float]:
    """Parse the `requests` column of a trace CSV.

    Uses the same strict row shape as validate.py's trace checker (exactly
    two columns per data row) instead of `csv.DictReader`, which silently
    *skips* blank/malformed rows. That leniency would let a blank line
    anywhere in the file quietly shift every subsequent row's effective tau
    by one -- a silent Lambda misalignment -- if this loader is ever reached
    on data that hasn't gone through (or diverges from) `validate()`'s exact
    check. Raising loudly here keeps `load_traces()` self-defending rather
    than relying entirely on callers honoring the validate-then-load order.
    """
    with path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))

    if not rows:
        raise ValueError(f"trace file is empty: {path}")

    header = rows[0]
    if header != ["time_unit", "requests"]:
        raise ValueError(f"trace file {path} has unexpected header {header!r}")

    requests: list[float] = []
    for line_no, row in enumerate(rows[1:], start=2):
        if len(row) != 2:
            raise ValueError(f"trace file {path}, line {line_no}: expected 2 columns, got {row!r}")
        requests.append(float(row[1]))
    return requests
