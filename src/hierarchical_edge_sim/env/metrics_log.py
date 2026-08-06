"""On-disk metrics output for Part A runs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .config import MicroserviceSpec, WorldSpec
from .traces import TraceStore
from .world import World


def make_run_id(seed: int, now_utc: datetime | None = None) -> str:
    """Create run_id as '{seed}_{utc_timestamp}'."""
    now = now_utc or datetime.now(UTC)
    ts = now.strftime("%Y%m%dT%H%M%SZ")
    return f"{seed}_{ts}"


def write_run_outputs(
    *,
    world: World,
    world_spec: WorldSpec,
    traces: TraceStore,
    run_id: str,
    action_log: list | None = None,
    autoscaler_meta: dict | None = None,
    rps_forecast_log: list | None = None,
) -> Path:
    """Write run_meta + per-container metadata/log CSVs.

    Returns:
        Path to the created run directory: <results_dir>/<run_id>
    """
    run_dir = _resolve_results_base(world_spec) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    ms_specs = _microservice_spec_index(world_spec)
    _write_run_meta(
        run_dir=run_dir,
        world_spec=world_spec,
        traces=traces,
        run_id=run_id,
        autoscaler_meta=autoscaler_meta,
    )
    _write_actions_csv(run_dir=run_dir, action_log=action_log or [])
    _write_rps_forecast_csv(run_dir=run_dir, rps_forecast_log=rps_forecast_log or [])

    for container in world.containers.values():
        ms = world.microservices[container.microservice_id]
        server = world.servers[container.server_id]
        spec = ms_specs[container.microservice_id]
        container_dir = run_dir / "apps" / container.app_id / ms.id
        container_dir.mkdir(parents=True, exist_ok=True)
        _write_container_meta(container_dir=container_dir, container=container, server_cluster_id=server.cluster_id, spec=spec)
        _write_container_log(container_dir=container_dir, container_id=container.id, history=container.history)

    return run_dir


def _write_run_meta(
    *,
    run_dir: Path,
    world_spec: WorldSpec,
    traces: TraceStore,
    run_id: str,
    autoscaler_meta: dict | None = None,
) -> None:
    payload = {
        "run_id": run_id,
        "seed": world_spec.sim.seed,
        "N": traces.horizon,
        "source_path": str(world_spec.source_path),
        "autoscaler": autoscaler_meta,
        "config": {
            "sim": asdict(world_spec.sim),
            "traces_dir": world_spec.traces_dir,
            "clusters": [asdict(c) for c in world_spec.clusters],
            "apps": [asdict(a) for a in world_spec.apps],
        },
    }
    with (run_dir / "run_meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False)


def _write_actions_csv(*, run_dir: Path, action_log: list) -> None:
    path = run_dir / "actions.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "tau",
                "autoscaler_name",
                "ms_id",
                "action_type",
                "container_id",
                "reason",
                "cpu_old",
                "cpu_new",
                "ram_old",
                "ram_new",
                "result_code",
            ]
        )
        for row in action_log:
            writer.writerow(
                [
                    row.tau,
                    row.autoscaler_name,
                    row.ms_id,
                    row.action_type,
                    row.container_id,
                    row.reason,
                    row.cpu_old if row.cpu_old is not None else "",
                    row.cpu_new if row.cpu_new is not None else "",
                    row.ram_old if row.ram_old is not None else "",
                    row.ram_new if row.ram_new is not None else "",
                    row.result_code,
                ]
            )


def _write_rps_forecast_csv(*, run_dir: Path, rps_forecast_log: list) -> None:
    """Long-format RPS observation + multi-lead forecast log."""
    path = run_dir / "rps_forecast.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "tau",
                "ttw",
                "ms_id",
                "lead",
                "target_ttw",
                "r_t",
                "r_hat",
                "history_len",
                "forecast_ready",
            ]
        )
        for row in rps_forecast_log:
            writer.writerow(
                [
                    row.tau,
                    row.ttw,
                    row.ms_id,
                    row.lead,
                    row.target_ttw,
                    row.r_t if row.r_t is not None else "",
                    row.r_hat if row.r_hat is not None else "",
                    row.history_len,
                    "true" if row.forecast_ready else "false",
                ]
            )


def _write_container_meta(
    *,
    container_dir: Path,
    container,
    server_cluster_id: str,
    spec: MicroserviceSpec,
) -> None:
    payload = {
        "container_id": container.id,
        "app_id": container.app_id,
        "microservice_id": container.microservice_id,
        "server_id": container.server_id,
        "cluster_id": server_cluster_id,
        "cpu_min_cores": spec.cpu_min_cores,
        "cpu_max_cores": spec.cpu_max_cores,
        "ram_min_mb": spec.ram_min_mb,
        "ram_max_mb": spec.ram_max_mb,
        "cpu_per_request_cores": spec.cpu_per_request_cores,
        "ram_per_request_mb": spec.ram_per_request_mb,
        "initial_cpu_alloc_cores": container.initial_cpu_alloc_cores,
        "initial_ram_alloc_mb": container.initial_ram_alloc_mb,
        "final_cpu_alloc_cores": container.cpu_alloc_cores,
        "final_ram_alloc_mb": container.ram_alloc_mb,
    }
    path = container_dir / f"{container.id}.meta.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_container_log(*, container_dir: Path, container_id: str, history) -> None:
    path = container_dir / f"{container_id}.log.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "time_unit",
                "cpu_core_capacity",
                "ram_size_capacity_mb",
                "cpu_core_used",
                "ram_size_used_mb",
                "incoming_requests",
                "served_requests",
                "dropped_requests",
            ]
        )
        for rec in history:
            writer.writerow(
                [
                    rec.tau,
                    rec.cpu_alloc_cores,
                    rec.ram_alloc_mb,
                    rec.cpu_usage_cores,
                    rec.ram_usage_mb,
                    rec.lambda_in,
                    rec.lambda_served,
                    rec.lambda_dropped,
                ]
            )


def _resolve_results_base(world_spec: WorldSpec) -> Path:
    raw = Path(world_spec.sim.results_dir)
    if raw.is_absolute():
        return raw.resolve()
    # Keep consistency with configs/ + traces/ layout used in this project.
    by_project_root = (world_spec.source_path.parent.parent / raw).resolve()
    return by_project_root


def _microservice_spec_index(world_spec: WorldSpec) -> dict[str, MicroserviceSpec]:
    index: dict[str, MicroserviceSpec] = {}
    for app in world_spec.apps:
        for ms in app.microservices:
            index[ms.id] = ms
    return index
