"""Config types and YAML loading for Part A environment."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

EPS = 1e-9
RESOURCE_DECIMALS = 2


def quantize_resource(value: float) -> float:
    """Snap CPU cores / RAM MB to two decimal places (simulator quantum)."""
    return round(float(value), RESOURCE_DECIMALS)


def format_resource(value: float | None) -> str:
    """CSV/log form of a quantized CPU/RAM quantity; empty if missing."""
    if value is None:
        return ""
    return f"{quantize_resource(value):.{RESOURCE_DECIMALS}f}"


@dataclass(frozen=True, slots=True)
class SimConfig:
    tick_sec: float
    results_dir: str
    seed: int


@dataclass(frozen=True, slots=True)
class ServerSpec:
    id: str
    cpu_cap_cores: float
    ram_cap_mb: float


@dataclass(frozen=True, slots=True)
class ClusterSpec:
    id: str
    servers: list[ServerSpec]
    coords: tuple[float, float] | None = None


@dataclass(frozen=True, slots=True)
class VicinitySpec:
    id: str
    members: list[str]
    leader: str


@dataclass(frozen=True, slots=True)
class ContainerSpec:
    id: str
    server_id: str
    cpu_alloc_cores: float
    ram_alloc_mb: float


@dataclass(frozen=True, slots=True)
class MicroserviceSpec:
    id: str
    cpu_min_cores: float
    cpu_max_cores: float
    ram_min_mb: float
    ram_max_mb: float
    cpu_per_request_cores: float
    ram_per_request_mb: float
    trace_file: str
    containers: list[ContainerSpec]


@dataclass(frozen=True, slots=True)
class AppSpec:
    id: str
    microservices: list[MicroserviceSpec]


@dataclass(frozen=True, slots=True)
class LatencyEdge:
    """One undirected inter-cluster RTT. ``from``/``to`` are cluster ids."""

    a: str
    b: str
    ms: float


@dataclass(frozen=True, slots=True)
class RawConfig:
    sim: SimConfig
    traces_dir: str
    topology: list[ClusterSpec]
    apps: list[AppSpec]
    source_path: Path
    vicinities: list[VicinitySpec] = field(default_factory=list)
    latency_ms: list[LatencyEdge] = field(default_factory=list)
    partition: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class WorldSpec:
    sim: SimConfig
    traces_dir: str
    clusters: list[ClusterSpec]
    apps: list[AppSpec]
    source_path: Path
    vicinities: list[VicinitySpec] = field(default_factory=list)
    latency_ms: list[LatencyEdge] = field(default_factory=list)
    partition: dict[str, Any] | None = None


def load_yaml(path: str | Path) -> RawConfig:
    """Load YAML config into typed dataclasses.

    This function intentionally performs structural parsing only.
    Semantic checks (constraints/rules) are handled in validate.py.
    """

    config_path = Path(path).expanduser().resolve()
    raw_data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = _as_mapping(raw_data, path="root")

    sim_data = _as_mapping(_require(root, "sim", "root"), path="sim")
    topology_data = _as_mapping(_require(root, "topology", "root"), path="topology")

    sim = SimConfig(
        tick_sec=_to_float(_require(sim_data, "tick_sec", "sim"), "sim.tick_sec"),
        results_dir=_to_str(_require(sim_data, "results_dir", "sim"), "sim.results_dir"),
        seed=_to_int(_require(sim_data, "seed", "sim"), "sim.seed"),
    )

    clusters_raw = _as_list(_require(topology_data, "clusters", "topology"), "topology.clusters")
    clusters = [_parse_cluster(item, f"topology.clusters[{idx}]") for idx, item in enumerate(clusters_raw)]

    vicinities: list[VicinitySpec] = []
    if "vicinities" in topology_data:
        vicinities_raw = _as_list(topology_data["vicinities"], "topology.vicinities")
        vicinities = [
            _parse_vicinity(item, f"topology.vicinities[{idx}]") for idx, item in enumerate(vicinities_raw)
        ]

    latency_ms: list[LatencyEdge] = []
    if "latency_ms" in topology_data:
        latency_raw = _as_list(topology_data["latency_ms"], "topology.latency_ms")
        latency_ms = [
            _parse_latency_edge(item, f"topology.latency_ms[{idx}]") for idx, item in enumerate(latency_raw)
        ]

    partition: dict[str, Any] | None = None
    if "partition" in topology_data:
        partition = dict(_as_mapping(topology_data["partition"], path="topology.partition"))

    apps_raw = _as_list(_require(root, "apps", "root"), "apps")
    apps = [_parse_app(item, f"apps[{idx}]") for idx, item in enumerate(apps_raw)]

    traces_dir = _to_str(_require(root, "traces_dir", "root"), "traces_dir")
    return RawConfig(
        sim=sim,
        traces_dir=traces_dir,
        topology=clusters,
        apps=apps,
        source_path=config_path,
        vicinities=vicinities,
        latency_ms=latency_ms,
        partition=partition,
    )


def resolve_traces_dir(traces_dir: str, source_path: Path) -> Path:
    """Resolve `traces_dir` relative to the config file, falling back to project root.

    Shared by validate.py (pre-check) and traces.py (actual load) so the two
    stages can never disagree on which directory holds the trace CSVs --
    duplicating this resolution logic risked one call site being updated
    without the other, which would silently break the validate-then-load
    fail-fast guarantee (§3.1: nothing reads real trace data until validate
    has approved the exact same path).
    """
    raw_path = Path(traces_dir)
    if raw_path.is_absolute():
        return raw_path.resolve()

    # Prefer config-relative path, but allow project-root-relative path too.
    # This supports the locked 00-tiny.yaml layout:
    #   configs/00-tiny.yaml + traces_dir: traces/demo/
    by_config_dir = (source_path.parent / raw_path).resolve()
    if by_config_dir.exists():
        return by_config_dir

    by_project_root = (source_path.parent.parent / raw_path).resolve()
    if by_project_root.exists():
        return by_project_root

    # Keep deterministic fallback when neither exists; caller decides how to
    # report the error (validate.py raises a ValidationError for this case).
    return by_config_dir


def to_world_spec(config: RawConfig) -> WorldSpec:
    """Convert RawConfig to WorldSpec by structural copy only."""
    return WorldSpec(
        sim=config.sim,
        traces_dir=config.traces_dir,
        clusters=config.topology,
        apps=config.apps,
        source_path=config.source_path,
        vicinities=list(config.vicinities),
        latency_ms=list(config.latency_ms),
        partition=dict(config.partition) if config.partition is not None else None,
    )


def _parse_cluster(data: Any, path: str) -> ClusterSpec:
    obj = _as_mapping(data, path=path)
    servers_raw = _as_list(_require(obj, "servers", path), f"{path}.servers")
    servers = [_parse_server(item, f"{path}.servers[{idx}]") for idx, item in enumerate(servers_raw)]
    coords: tuple[float, float] | None = None
    if "coords" in obj:
        coords_raw = _as_list(obj["coords"], f"{path}.coords")
        if len(coords_raw) != 2:
            raise ValueError(f"Expected 2 numbers at '{path}.coords', got {len(coords_raw)}")
        coords = (
            _to_float(coords_raw[0], f"{path}.coords[0]"),
            _to_float(coords_raw[1], f"{path}.coords[1]"),
        )
    return ClusterSpec(
        id=_to_str(_require(obj, "id", path), f"{path}.id"),
        servers=servers,
        coords=coords,
    )


def _parse_latency_edge(data: Any, path: str) -> LatencyEdge:
    obj = _as_mapping(data, path=path)
    return LatencyEdge(
        a=_to_str(_require(obj, "from", path), f"{path}.from"),
        b=_to_str(_require(obj, "to", path), f"{path}.to"),
        ms=_to_float(_require(obj, "ms", path), f"{path}.ms"),
    )


def _parse_vicinity(data: Any, path: str) -> VicinitySpec:
    obj = _as_mapping(data, path=path)
    members_raw = _as_list(_require(obj, "members", path), f"{path}.members")
    members = [_to_str(item, f"{path}.members[{idx}]") for idx, item in enumerate(members_raw)]
    return VicinitySpec(
        id=_to_str(_require(obj, "id", path), f"{path}.id"),
        members=members,
        leader=_to_str(_require(obj, "leader", path), f"{path}.leader"),
    )


def _parse_server(data: Any, path: str) -> ServerSpec:
    obj = _as_mapping(data, path=path)
    return ServerSpec(
        id=_to_str(_require(obj, "id", path), f"{path}.id"),
        cpu_cap_cores=_to_float(_require(obj, "cpu_cap_cores", path), f"{path}.cpu_cap_cores"),
        ram_cap_mb=_to_float(_require(obj, "ram_cap_mb", path), f"{path}.ram_cap_mb"),
    )


def _parse_app(data: Any, path: str) -> AppSpec:
    obj = _as_mapping(data, path=path)
    ms_raw = _as_list(_require(obj, "microservices", path), f"{path}.microservices")
    microservices = [_parse_microservice(item, f"{path}.microservices[{idx}]") for idx, item in enumerate(ms_raw)]
    return AppSpec(
        id=_to_str(_require(obj, "id", path), f"{path}.id"),
        microservices=microservices,
    )


def _parse_microservice(data: Any, path: str) -> MicroserviceSpec:
    obj = _as_mapping(data, path=path)
    containers_raw = _as_list(_require(obj, "containers", path), f"{path}.containers")
    containers = [_parse_container(item, f"{path}.containers[{idx}]") for idx, item in enumerate(containers_raw)]

    return MicroserviceSpec(
        id=_to_str(_require(obj, "id", path), f"{path}.id"),
        cpu_min_cores=_to_float(_require(obj, "cpu_min_cores", path), f"{path}.cpu_min_cores"),
        cpu_max_cores=_to_float(_require(obj, "cpu_max_cores", path), f"{path}.cpu_max_cores"),
        ram_min_mb=_to_float(_require(obj, "ram_min_mb", path), f"{path}.ram_min_mb"),
        ram_max_mb=_to_float(_require(obj, "ram_max_mb", path), f"{path}.ram_max_mb"),
        cpu_per_request_cores=_to_float(
            _require(obj, "cpu_per_request_cores", path),
            f"{path}.cpu_per_request_cores",
        ),
        ram_per_request_mb=_to_float(
            _require(obj, "ram_per_request_mb", path),
            f"{path}.ram_per_request_mb",
        ),
        trace_file=_to_str(_require(obj, "trace_file", path), f"{path}.trace_file"),
        containers=containers,
    )


def _parse_container(data: Any, path: str) -> ContainerSpec:
    obj = _as_mapping(data, path=path)
    return ContainerSpec(
        id=_to_str(_require(obj, "id", path), f"{path}.id"),
        server_id=_to_str(_require(obj, "server_id", path), f"{path}.server_id"),
        cpu_alloc_cores=_to_float(_require(obj, "cpu_alloc_cores", path), f"{path}.cpu_alloc_cores"),
        ram_alloc_mb=_to_float(_require(obj, "ram_alloc_mb", path), f"{path}.ram_alloc_mb"),
    )


def _require(mapping: dict[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Missing required key '{path}.{key}'")
    return mapping[key]


def _as_mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Expected mapping at '{path}', got {type(value).__name__}")
    return value


def _as_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError(f"Expected list at '{path}', got {type(value).__name__}")
    return value


def _to_str(value: Any, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Expected string at '{path}', got {type(value).__name__}")
    return value


def _to_float(value: Any, path: str) -> float:
    # bool is a subclass of int in Python, so isinstance(True, int | float) is True;
    # exclude it explicitly so e.g. `cpu_cap_cores: true` is rejected, not silently 1.0.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Expected number at '{path}', got {type(value).__name__}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"Expected finite number at '{path}', got {result}")
    return result


def _to_int(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Expected int at '{path}', got {type(value).__name__}")
    return value
