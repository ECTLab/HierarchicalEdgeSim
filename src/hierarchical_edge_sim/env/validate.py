"""Config validation for Part A environment."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from .config import EPS, RawConfig, WorldSpec, resolve_traces_dir, to_world_spec


@dataclass(frozen=True, slots=True)
class ValidationError:
    path: str
    message: str


class ConfigError(Exception):
    """Raised when config validation fails with one or more errors."""

    def __init__(self, errors: list[ValidationError]) -> None:
        self.errors = errors
        joined = "; ".join(f"{err.path}: {err.message}" for err in errors)
        super().__init__(f"Config validation failed ({len(errors)} error(s)): {joined}")


def validate(config: RawConfig) -> list[ValidationError]:
    errors: list[ValidationError] = []

    _validate_sim(config, errors)
    _validate_ids_and_counts(config, errors)

    server_lookup: dict[str, tuple[float, float]] = {}
    seen_server_ids: set[str] = set()
    seen_cluster_ids: set[str] = set()
    seen_app_ids: set[str] = set()
    seen_ms_ids: set[str] = set()
    seen_container_ids: set[str] = set()

    # Collect server IDs and static cap checks
    for cidx, cluster in enumerate(config.topology):
        if cluster.id in seen_cluster_ids:
            errors.append(
                ValidationError(path=f"topology.clusters[{cidx}].id", message=f"duplicate cluster id '{cluster.id}'")
            )
        seen_cluster_ids.add(cluster.id)

        if not cluster.servers:
            errors.append(
                ValidationError(
                    path=f"topology.clusters[{cidx}].servers",
                    message="cluster must contain at least one server",
                )
            )

        for sidx, server in enumerate(cluster.servers):
            spath = f"topology.clusters[{cidx}].servers[{sidx}]"
            if server.id in seen_server_ids:
                errors.append(ValidationError(path=f"{spath}.id", message=f"duplicate server id '{server.id}'"))
            seen_server_ids.add(server.id)
            # Keep the first occurrence on duplicate ids so downstream cap/packing
            # checks stay deterministic instead of silently keying off whichever
            # duplicate happened to be parsed last.
            server_lookup.setdefault(server.id, (server.cpu_cap_cores, server.ram_cap_mb))

            if server.cpu_cap_cores <= 0:
                errors.append(ValidationError(path=f"{spath}.cpu_cap_cores", message="must be > 0"))
            if server.ram_cap_mb <= 0:
                errors.append(ValidationError(path=f"{spath}.ram_cap_mb", message="must be > 0"))

    server_alloc_sums: dict[str, tuple[float, float]] = {sid: (0.0, 0.0) for sid in server_lookup}
    ms_trace_files: dict[str, str] = {}

    # App/MS/container checks
    for aidx, app in enumerate(config.apps):
        apath = f"apps[{aidx}]"
        if app.id in seen_app_ids:
            errors.append(ValidationError(path=f"{apath}.id", message=f"duplicate app id '{app.id}'"))
        seen_app_ids.add(app.id)

        if not app.microservices:
            errors.append(
                ValidationError(path=f"{apath}.microservices", message="app must contain at least one microservice")
            )

        for midx, ms in enumerate(app.microservices):
            mpath = f"{apath}.microservices[{midx}]"
            if ms.id in seen_ms_ids:
                errors.append(ValidationError(path=f"{mpath}.id", message=f"duplicate microservice id '{ms.id}'"))
            seen_ms_ids.add(ms.id)
            # Keep the first occurrence on duplicate ids, matching server_lookup above.
            ms_trace_files.setdefault(ms.id, ms.trace_file)

            if ms.cpu_min_cores <= 0:
                errors.append(ValidationError(path=f"{mpath}.cpu_min_cores", message="must be > 0"))
            if ms.cpu_max_cores + EPS < ms.cpu_min_cores:
                errors.append(
                    ValidationError(path=f"{mpath}.cpu_max_cores", message="must be >= cpu_min_cores (with EPS)")
                )
            if ms.ram_min_mb <= 0:
                errors.append(ValidationError(path=f"{mpath}.ram_min_mb", message="must be > 0"))
            if ms.ram_max_mb + EPS < ms.ram_min_mb:
                errors.append(
                    ValidationError(path=f"{mpath}.ram_max_mb", message="must be >= ram_min_mb (with EPS)")
                )
            if ms.cpu_per_request_cores <= 0:
                errors.append(ValidationError(path=f"{mpath}.cpu_per_request_cores", message="must be > 0"))
            if ms.ram_per_request_mb < 0:
                errors.append(ValidationError(path=f"{mpath}.ram_per_request_mb", message="must be >= 0"))

            if not ms.containers:
                errors.append(
                    ValidationError(
                        path=f"{mpath}.containers",
                        message="microservice must contain at least one container",
                    )
                )

            for kidx, container in enumerate(ms.containers):
                cpath = f"{mpath}.containers[{kidx}]"
                if container.id in seen_container_ids:
                    errors.append(ValidationError(path=f"{cpath}.id", message=f"duplicate container id '{container.id}'"))
                seen_container_ids.add(container.id)

                if container.server_id not in server_lookup:
                    errors.append(
                        ValidationError(
                            path=f"{cpath}.server_id",
                            message=f"unknown server_id '{container.server_id}'",
                        )
                    )
                    errors.append(
                        ValidationError(
                            path=f"{cpath}.server_id",
                            message="server_id must belong to a server listed under some cluster",
                        )
                    )

                if container.cpu_alloc_cores + EPS < ms.cpu_min_cores:
                    errors.append(
                        ValidationError(
                            path=f"{cpath}.cpu_alloc_cores",
                            message="must be >= cpu_min_cores (with EPS)",
                        )
                    )
                if container.cpu_alloc_cores > ms.cpu_max_cores + EPS:
                    errors.append(
                        ValidationError(
                            path=f"{cpath}.cpu_alloc_cores",
                            message="must be <= cpu_max_cores (with EPS)",
                        )
                    )
                if container.ram_alloc_mb + EPS < ms.ram_min_mb:
                    errors.append(
                        ValidationError(
                            path=f"{cpath}.ram_alloc_mb",
                            message="must be >= ram_min_mb (with EPS)",
                        )
                    )
                if container.ram_alloc_mb > ms.ram_max_mb + EPS:
                    errors.append(
                        ValidationError(
                            path=f"{cpath}.ram_alloc_mb",
                            message="must be <= ram_max_mb (with EPS)",
                        )
                    )

                if container.server_id in server_alloc_sums:
                    cpu_sum, ram_sum = server_alloc_sums[container.server_id]
                    server_alloc_sums[container.server_id] = (
                        cpu_sum + container.cpu_alloc_cores,
                        ram_sum + container.ram_alloc_mb,
                    )

    # Server packing against physical caps
    for server_id, (cpu_sum, ram_sum) in server_alloc_sums.items():
        cpu_cap, ram_cap = server_lookup[server_id]
        if cpu_sum > cpu_cap + EPS:
            errors.append(
                ValidationError(
                    path=f"server[{server_id}].cpu_alloc_sum",
                    message=f"sum cpu_alloc_cores {cpu_sum} exceeds cpu_cap_cores {cpu_cap} (+EPS)",
                )
            )
        if ram_sum > ram_cap + EPS:
            errors.append(
                ValidationError(
                    path=f"server[{server_id}].ram_alloc_sum",
                    message=f"sum ram_alloc_mb {ram_sum} exceeds ram_cap_mb {ram_cap} (+EPS)",
                )
            )

    _validate_traces(config, ms_trace_files, errors)
    _validate_vicinities(config, seen_cluster_ids, errors)
    _validate_distance_and_partition(config, seen_cluster_ids, errors)
    return errors


def validate_or_raise(config: RawConfig) -> WorldSpec:
    errs = validate(config)
    if errs:
        raise ConfigError(errs)
    return to_world_spec(config)


def _validate_sim(config: RawConfig, errors: list[ValidationError]) -> None:
    if config.sim.tick_sec <= 0:
        errors.append(ValidationError(path="sim.tick_sec", message="must be > 0"))
    if config.sim.sla_timeout_sec <= 0:
        errors.append(ValidationError(path="sim.sla_timeout_sec", message="must be > 0"))
    if not config.sim.results_dir.strip():
        errors.append(ValidationError(path="sim.results_dir", message="must be a non-empty string"))
    if not isinstance(config.sim.seed, int):
        errors.append(ValidationError(path="sim.seed", message="must be int"))


def _validate_vicinities(
    config: RawConfig,
    known_cluster_ids: set[str],
    errors: list[ValidationError],
) -> None:
    """Validate topology.vicinities when present; no-op if the block is absent."""
    if not config.vicinities:
        return

    seen_vicinity_ids: set[str] = set()
    assigned: dict[str, str] = {}  # cluster_id -> vicinity_id

    for vidx, vicinity in enumerate(config.vicinities):
        vpath = f"topology.vicinities[{vidx}]"
        if vicinity.id in seen_vicinity_ids:
            errors.append(
                ValidationError(path=f"{vpath}.id", message=f"duplicate vicinity id '{vicinity.id}'")
            )
        seen_vicinity_ids.add(vicinity.id)

        if not vicinity.members:
            errors.append(ValidationError(path=f"{vpath}.members", message="must contain at least one member"))

        seen_members_local: set[str] = set()
        for midx, member in enumerate(vicinity.members):
            mpath = f"{vpath}.members[{midx}]"
            if member in seen_members_local:
                errors.append(ValidationError(path=mpath, message=f"duplicate member '{member}' in vicinity"))
            seen_members_local.add(member)
            if member not in known_cluster_ids:
                errors.append(ValidationError(path=mpath, message=f"unknown cluster id '{member}'"))
            if member in assigned:
                errors.append(
                    ValidationError(
                        path=mpath,
                        message=f"cluster '{member}' appears in more than one vicinity "
                        f"('{assigned[member]}' and '{vicinity.id}')",
                    )
                )
            else:
                assigned[member] = vicinity.id

        if vicinity.leader not in vicinity.members:
            errors.append(
                ValidationError(
                    path=f"{vpath}.leader",
                    message=f"leader '{vicinity.leader}' must be listed in members",
                )
            )
        elif vicinity.leader not in known_cluster_ids:
            errors.append(
                ValidationError(
                    path=f"{vpath}.leader",
                    message=f"unknown cluster id '{vicinity.leader}'",
                )
            )

    # Covering: every known cluster must appear in exactly one vicinity.
    missing = sorted(known_cluster_ids - set(assigned.keys()))
    for cluster_id in missing:
        errors.append(
            ValidationError(
                path="topology.vicinities",
                message=f"cluster '{cluster_id}' is not assigned to any vicinity",
            )
            )


def _validate_distance_and_partition(
    config: RawConfig,
    known_cluster_ids: set[str],
    errors: list[ValidationError],
) -> None:
    """Coords / latency_ms / partition knobs. YAML vicinities stay a valid override."""
    from .partition import (
        matrix_is_complete,
        parse_partition_params,
        pair_key,
    )

    cluster_ids = [c.id for c in config.topology]
    coords = {c.id: c.coords for c in config.topology if c.coords is not None}
    partial_coords = 0 < len(coords) < len(cluster_ids)

    for cidx, cluster in enumerate(config.topology):
        if cluster.coords is None:
            continue
        x, y = cluster.coords
        if not (math.isfinite(x) and math.isfinite(y)):
            errors.append(
                ValidationError(
                    path=f"topology.clusters[{cidx}].coords",
                    message="coords must be finite numbers",
                )
            )

    latency_pairs: dict[tuple[str, str], float] = {}
    seen_edge: set[tuple[str, str]] = set()
    for eidx, edge in enumerate(config.latency_ms):
        epath = f"topology.latency_ms[{eidx}]"
        if edge.a not in known_cluster_ids:
            errors.append(ValidationError(path=f"{epath}.from", message=f"unknown cluster id '{edge.a}'"))
        if edge.b not in known_cluster_ids:
            errors.append(ValidationError(path=f"{epath}.to", message=f"unknown cluster id '{edge.b}'"))
        if edge.a == edge.b:
            errors.append(ValidationError(path=epath, message="from and to must be different clusters"))
        if edge.ms <= 0:
            errors.append(ValidationError(path=f"{epath}.ms", message="must be > 0"))
        key = pair_key(edge.a, edge.b)
        if key in seen_edge:
            errors.append(ValidationError(path=epath, message=f"duplicate pair '{edge.a}'-'{edge.b}'"))
        seen_edge.add(key)
        latency_pairs[key] = edge.ms

    if config.partition is not None:
        try:
            parse_partition_params(config.partition)
        except (TypeError, ValueError) as exc:
            errors.append(ValidationError(path="topology.partition", message=str(exc)))

    wants_geometry = bool(coords) or bool(config.latency_ms) or config.partition is not None
    if config.vicinities:
        # Hand groups win. Geometry is optional (stored for Env.distance when complete).
        if config.latency_ms and not matrix_is_complete(cluster_ids, latency_pairs):
            errors.append(
                ValidationError(
                    path="topology.latency_ms",
                    message="must include every unordered cluster pair when the list is present",
                )
            )
        if partial_coords and not matrix_is_complete(cluster_ids, latency_pairs):
            errors.append(
                ValidationError(
                    path="topology.clusters",
                    message="every cluster must have coords when any cluster has coords",
                )
            )
        return

    if not wants_geometry:
        return

    latency_complete = bool(latency_pairs) and matrix_is_complete(cluster_ids, latency_pairs)
    coords_complete = len(coords) == len(cluster_ids) and len(cluster_ids) >= 1
    if latency_pairs and not latency_complete:
        errors.append(
            ValidationError(
                path="topology.latency_ms",
                message="must include every unordered cluster pair (algorithm needs a complete d(·,·))",
            )
        )
    if partial_coords and not latency_complete:
        errors.append(
            ValidationError(
                path="topology.clusters",
                message="every cluster must have coords when any cluster has coords",
            )
        )
    if not latency_complete and not coords_complete:
        errors.append(
            ValidationError(
                path="topology",
                message="VicinityPartitionAndLeaderElection needs cluster coords or a complete "
                "topology.latency_ms matrix (or set topology.vicinities by hand)",
            )
        )


def _validate_ids_and_counts(config: RawConfig, errors: list[ValidationError]) -> None:
    if not config.topology:
        errors.append(ValidationError(path="topology.clusters", message="must contain at least one cluster"))
    server_count = sum(len(cluster.servers) for cluster in config.topology)
    if server_count < 1:
        errors.append(ValidationError(path="topology.clusters[*].servers", message="must contain at least one server"))
    if not config.apps:
        errors.append(ValidationError(path="apps", message="must contain at least one app"))
    ms_count = sum(len(app.microservices) for app in config.apps)
    if ms_count < 1:
        errors.append(ValidationError(path="apps[*].microservices", message="must contain at least one microservice"))
    container_count = sum(len(ms.containers) for app in config.apps for ms in app.microservices)
    if container_count < 1:
        errors.append(
            ValidationError(
                path="apps[*].microservices[*].containers",
                message="must contain at least one container",
            )
        )


def _validate_traces(config: RawConfig, ms_trace_files: dict[str, str], errors: list[ValidationError]) -> None:
    traces_dir = resolve_traces_dir(config.traces_dir, config.source_path)
    if not traces_dir.exists():
        errors.append(ValidationError(path="traces_dir", message=f"directory not found: {traces_dir}"))
        return
    if not traces_dir.is_dir():
        errors.append(ValidationError(path="traces_dir", message=f"not a directory: {traces_dir}"))
        return

    lengths: dict[str, int] = {}
    for ms_id, filename in ms_trace_files.items():
        trace_path = (traces_dir / filename).resolve()
        if not trace_path.exists():
            errors.append(ValidationError(path=f"trace_file[{ms_id}]", message=f"file not found: {trace_path}"))
            continue
        if not trace_path.is_file():
            errors.append(ValidationError(path=f"trace_file[{ms_id}]", message=f"not a file: {trace_path}"))
            continue

        row_count, trace_errors = _validate_trace_file(ms_id, trace_path)
        lengths[ms_id] = row_count
        errors.extend(trace_errors)

    if not lengths:
        return

    unique_lengths = set(lengths.values())
    if len(unique_lengths) > 1:
        lengths_repr = ", ".join(f"{k}:{v}" for k, v in sorted(lengths.items()))
        errors.append(
            ValidationError(
                path="traces[*]",
                message=f"all traces must have equal data row counts; got {lengths_repr}",
            )
        )
    if min(unique_lengths) < 1:
        errors.append(ValidationError(path="traces[*]", message="trace data row count must be >= 1"))


def _validate_trace_file(ms_id: str, trace_path: Path) -> tuple[int, list[ValidationError]]:
    local_errors: list[ValidationError] = []
    path_key = f"trace_file[{ms_id}]"

    with trace_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if not rows:
        local_errors.append(ValidationError(path=path_key, message="trace file is empty"))
        return 0, local_errors

    header = rows[0]
    if header != ["time_unit", "requests"]:
        local_errors.append(
            ValidationError(path=f"{path_key}.header", message="header must be exactly 'time_unit,requests'")
        )

    data_rows = rows[1:]
    for idx, row in enumerate(data_rows, start=1):
        rpath = f"{path_key}.row[{idx}]"
        if len(row) != 2:
            local_errors.append(ValidationError(path=rpath, message="row must have exactly two columns"))
            continue
        time_raw, req_raw = row

        try:
            time_val = int(time_raw)
        except ValueError:
            local_errors.append(ValidationError(path=f"{rpath}.time_unit", message="must be int"))
            continue

        if time_val != idx:
            local_errors.append(
                ValidationError(path=f"{rpath}.time_unit", message=f"must equal {idx}, got {time_val}")
            )

        try:
            req_val = float(req_raw)
        except ValueError:
            local_errors.append(ValidationError(path=f"{rpath}.requests", message="must be numeric"))
            continue
        # `req_val < 0` alone would silently accept NaN, since every comparison
        # with NaN is False in Python/IEEE-754 (nan < 0 is False, nan >= 0 is
        # also False). Require a finite, non-negative value explicitly.
        if not math.isfinite(req_val):
            local_errors.append(ValidationError(path=f"{rpath}.requests", message="must be >= 0 (got non-finite value)"))
        elif req_val < 0:
            local_errors.append(ValidationError(path=f"{rpath}.requests", message="must be >= 0"))

    return len(data_rows), local_errors
