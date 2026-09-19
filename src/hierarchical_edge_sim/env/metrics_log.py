"""On-disk metrics output for Part A runs."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .config import MicroserviceSpec, WorldSpec, format_resource, quantize_resource
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
    retired_containers: list | None = None,
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
        world=world,
        world_spec=world_spec,
        traces=traces,
        run_id=run_id,
        autoscaler_meta=autoscaler_meta,
    )
    _write_actions_csv(run_dir=run_dir, action_log=action_log or [])

    # Keep every life. Auto-ids are unique for the run; an explicit respawn of
    # the same id must not overwrite the retired log (trace conservation).
    to_write = list(retired_containers or []) + sorted(
        world.containers.values(), key=lambda c: c.id
    )
    used_stems: set[str] = set()
    for container in to_write:
        ms = world.microservices[container.microservice_id]
        server = world.servers[container.server_id]
        spec = ms_specs[container.microservice_id]
        container_dir = run_dir / "apps" / container.app_id / ms.id
        container_dir.mkdir(parents=True, exist_ok=True)
        stem = _unique_container_stem(container.id, used_stems)
        _write_container_meta(
            container_dir=container_dir,
            container=container,
            server_cluster_id=server.cluster_id,
            spec=spec,
            file_stem=stem,
        )
        _write_container_log(
            container_dir=container_dir,
            file_stem=stem,
            history=container.history,
        )

    return run_dir


def _write_run_meta(
    *,
    run_dir: Path,
    world: World,
    world_spec: WorldSpec,
    traces: TraceStore,
    run_id: str,
    autoscaler_meta: dict | None = None,
) -> None:
    published: list[dict] = []
    source = None
    if world.root is not None:
        source = world.root.vicinity_source
        published = [
            {
                "id": vic.id,
                "members": list(vic.member_cluster_ids),
                "leader": vic.leader_cluster_id,
            }
            for vic in world.root.vicinities.values()
        ]
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
            "vicinities": [asdict(v) for v in world_spec.vicinities],
            "latency_ms": [asdict(e) for e in world_spec.latency_ms],
            "partition": world_spec.partition,
            "vicinity_source": source,
            "published_vicinities": published,
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
                    row.cpu_old if row.cpu_old is None else format_resource(row.cpu_old),
                    row.cpu_new if row.cpu_new is None else format_resource(row.cpu_new),
                    row.ram_old if row.ram_old is None else format_resource(row.ram_old),
                    row.ram_new if row.ram_new is None else format_resource(row.ram_new),
                    row.result_code,
                ]
            )


def _unique_container_stem(container_id: str, used_stems: set[str]) -> str:
    stem = container_id
    n = 2
    while stem in used_stems:
        stem = f"{container_id}__life{n}"
        n += 1
    used_stems.add(stem)
    return stem


def _write_container_meta(
    *,
    container_dir: Path,
    container,
    server_cluster_id: str,
    spec: MicroserviceSpec,
    file_stem: str | None = None,
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
        "initial_cpu_alloc_cores": quantize_resource(container.initial_cpu_alloc_cores or 0.0),
        "initial_ram_alloc_mb": quantize_resource(container.initial_ram_alloc_mb or 0.0),
        "final_cpu_alloc_cores": quantize_resource(container.cpu_alloc_cores),
        "final_ram_alloc_mb": quantize_resource(container.ram_alloc_mb),
    }
    path = container_dir / f"{file_stem or container.id}.meta.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_container_log(*, container_dir: Path, file_stem: str, history) -> None:
    path = container_dir / f"{file_stem}.log.csv"
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
                "t_net_sec",
                "t_mean_offered_sec",
                "t_p95_offered_sec",
                "t_p99_offered_sec",
                "sla_miss_requests",
                "t_wait_sec",
                "t_svc_sec",
                "t_wait_lo_sec",
                "t_wait_hi_sec",
                "queue_len",
            ]
        )
        for rec in history:
            writer.writerow(
                [
                    rec.tau,
                    format_resource(rec.cpu_alloc_cores),
                    format_resource(rec.ram_alloc_mb),
                    format_resource(rec.cpu_usage_cores),
                    format_resource(rec.ram_usage_mb),
                    rec.lambda_in,
                    rec.lambda_served,
                    rec.lambda_dropped,
                    _format_sec(rec.t_net_sec),
                    _format_sec(rec.t_mean_offered_sec),
                    _format_sec(rec.t_p95_offered_sec),
                    _format_sec(rec.t_p99_offered_sec),
                    rec.sla_miss_requests,
                    _format_sec(rec.t_wait_sec),
                    _format_sec(rec.t_svc_sec),
                    _format_sec(rec.t_wait_lo_sec),
                    _format_sec(rec.t_wait_hi_sec),
                    rec.queue_len,
                ]
            )


def _format_sec(value: float) -> str:
    return f"{float(value):.9g}"


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
