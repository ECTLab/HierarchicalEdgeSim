"""I/O helpers for traces, container logs, and run metadata."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(slots=True)
class ContainerSeries:
    app_id: str
    microservice_id: str
    container_id: str
    log_path: Path
    tau: list[int]
    incoming: list[float]
    served: list[float]
    dropped: list[float]
    cpu_capacity: list[float]
    cpu_used: list[float]
    ram_capacity: list[float]
    ram_used: list[float]


@dataclass(slots=True)
class MicroserviceTraceRef:
    app_id: str
    microservice_id: str
    trace_file: str


@dataclass(slots=True)
class ActionEvent:
    tau: int
    ms_id: str
    container_id: str
    action_type: str
    reason: str
    result_code: str
    cpu_old: float | None
    cpu_new: float | None
    ram_old: float | None
    ram_new: float | None


def _optional_float(val: str | None) -> float | None:
    if val is None or val == "":
        return None
    return float(val)


def read_actions(run_dir: Path) -> list[ActionEvent]:
    """Load ``actions.csv`` if present; return [] when missing or header-only."""
    path = run_dir / "actions.csv"
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    events: list[ActionEvent] = []
    for r in rows:
        events.append(
            ActionEvent(
                tau=int(r["tau"]),
                ms_id=r.get("ms_id", ""),
                container_id=r.get("container_id", "") or "",
                action_type=r.get("action_type", ""),
                reason=r.get("reason", ""),
                result_code=r.get("result_code", ""),
                cpu_old=_optional_float(r.get("cpu_old")),
                cpu_new=_optional_float(r.get("cpu_new")),
                ram_old=_optional_float(r.get("ram_old")),
                ram_new=_optional_float(r.get("ram_new")),
            )
        )
    return events


def read_trace(path: Path) -> tuple[list[int], list[float]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return [int(r["time_unit"]) for r in rows], [float(r["requests"]) for r in rows]


def read_container_log(path: Path) -> ContainerSeries:
    # Expected layout: .../apps/<app_id>/<ms_id>/<container_id>.log.csv
    container_id = path.name.removesuffix(".log.csv")
    microservice_id = path.parent.name
    app_id = path.parent.parent.name
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return ContainerSeries(
        app_id=app_id,
        microservice_id=microservice_id,
        container_id=container_id,
        log_path=path,
        tau=[int(r["time_unit"]) for r in rows],
        incoming=[float(r["incoming_requests"]) for r in rows],
        served=[float(r["served_requests"]) for r in rows],
        dropped=[float(r["dropped_requests"]) for r in rows],
        cpu_capacity=[float(r["cpu_core_capacity"]) for r in rows],
        cpu_used=[float(r["cpu_core_used"]) for r in rows],
        ram_capacity=[float(r["ram_size_capacity_mb"]) for r in rows],
        ram_used=[float(r["ram_size_used_mb"]) for r in rows],
    )


def find_container_logs(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob("apps/*/*/*.log.csv"))


def load_run_meta(run_dir: Path) -> dict:
    meta_path = run_dir / "run_meta.yaml"
    if not meta_path.is_file():
        raise FileNotFoundError(f"missing run_meta.yaml in {run_dir}")
    return yaml.safe_load(meta_path.read_text(encoding="utf-8"))


def list_microservice_trace_refs(meta: dict) -> list[MicroserviceTraceRef]:
    refs: list[MicroserviceTraceRef] = []
    for app in meta.get("config", {}).get("apps", []):
        for ms in app.get("microservices", []):
            refs.append(
                MicroserviceTraceRef(
                    app_id=app["id"],
                    microservice_id=ms["id"],
                    trace_file=ms["trace_file"],
                )
            )
    return refs


def resolve_trace_path(project_root: Path, meta: dict, trace_file: str) -> Path:
    traces_dir = Path(meta["config"]["traces_dir"])
    if traces_dir.is_absolute():
        candidate = traces_dir / trace_file
    else:
        candidate = project_root / traces_dir / trace_file
    if not candidate.is_file():
        raise FileNotFoundError(f"could not resolve trace file: {candidate}")
    return candidate.resolve()
