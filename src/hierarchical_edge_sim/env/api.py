"""Env facade for Part A workflow and read APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from .config import MicroserviceSpec, WorldSpec, load_yaml
from .engine import EngineState, run_ticks, tick
from .metrics_log import make_run_id, write_run_outputs
from .models import App, Cluster, Container, Microservice, Server, Vicinity
from .root import RootOrchestrator
from .traces import TraceStore, load_traces
from .validate import validate_or_raise
from .world import World, build_world, server_free_cpu_cores, server_free_ram_mb


class RejectReason(str, Enum):
    NOT_IMPLEMENTED_IN_PART_A = "not_implemented_in_part_a"


@dataclass(slots=True)
class Env:
    world: World
    traces: TraceStore
    world_spec: WorldSpec
    state: EngineState

    @classmethod
    def from_config(cls, config_path: str | Path) -> "Env":
        raw = load_yaml(config_path)
        spec = validate_or_raise(raw)
        world = build_world(spec)
        traces = load_traces(spec)
        return cls(world=world, traces=traces, world_spec=spec, state=EngineState())

    @property
    def root(self) -> RootOrchestrator | None:
        return self.world.root

    def run(self, max_ticks: int | None = None, now_utc: datetime | None = None) -> Path:
        """Run engine then write outputs. max_ticks supports test/dev partial runs."""
        if max_ticks is None:
            run_ticks(world=self.world, traces=self.traces, world_spec=self.world_spec, state=self.state)
        else:
            self._run_partial(max_ticks=max_ticks)

        run_id = make_run_id(self.world_spec.sim.seed, now_utc=now_utc)
        return write_run_outputs(world=self.world, world_spec=self.world_spec, traces=self.traces, run_id=run_id)

    def _run_partial(self, max_ticks: int) -> None:
        if max_ticks < 0:
            raise ValueError("max_ticks must be >= 0")
        ms_specs = _microservice_spec_index(self.world_spec)
        horizon = self.traces.horizon
        target = min(max_ticks, horizon)
        for tau in range(1, target + 1):
            tick(world=self.world, traces=self.traces, ms_specs=ms_specs, tau=tau)
            self.state.current_tau = tau

    # Read APIs
    def get_time(self) -> int:
        return self.state.current_tau

    def list_apps(self) -> list[str]:
        return sorted(self.world.apps.keys())

    def list_clusters(self) -> list[str]:
        return sorted(self.world.clusters.keys())

    def list_servers(self) -> list[str]:
        return sorted(self.world.servers.keys())

    def list_microservices(self) -> list[str]:
        return sorted(self.world.microservices.keys())

    def list_containers(self) -> list[str]:
        return sorted(self.world.containers.keys())

    def get_ms_spec(self, ms_id: str) -> MicroserviceSpec:
        for app in self.world_spec.apps:
            for ms in app.microservices:
                if ms.id == ms_id:
                    return ms
        raise KeyError(f"unknown microservice id '{ms_id}'")

    def get_container(self, container_id: str) -> Container:
        return self.world.containers[container_id]

    def get_server(self, server_id: str) -> Server:
        return self.world.servers[server_id]

    def get_cluster(self, cluster_id: str) -> Cluster:
        return self.world.clusters[cluster_id]

    def get_app(self, app_id: str) -> App:
        return self.world.apps[app_id]

    def get_microservice(self, ms_id: str) -> Microservice:
        return self.world.microservices[ms_id]

    def get_server_free(self, server_id: str) -> tuple[float, float]:
        return server_free_cpu_cores(self.world, server_id), server_free_ram_mb(self.world, server_id)

    # Hierarchy read APIs (require topology.vicinities)
    def list_vicinities(self) -> list[str]:
        return self._require_root().list_vicinities()

    def get_vicinity(self, vicinity_id: str) -> Vicinity:
        return self._require_root().get_vicinity(vicinity_id)

    def vicinity_of(self, cluster_id: str) -> str:
        return self._require_root().vicinity_of(cluster_id)

    def leader_of(self, vicinity_id: str) -> str:
        return self._require_root().leader_of(vicinity_id)

    def is_leader(self, cluster_id: str) -> bool:
        return self._require_root().is_leader(cluster_id)

    def list_vicinity_members(self, vicinity_id: str) -> list[str]:
        return self._require_root().list_vicinity_members(vicinity_id)

    def _require_root(self) -> RootOrchestrator:
        if self.world.root is None:
            raise RuntimeError(
                "hierarchy APIs require topology.vicinities in the config "
                "(World.root is None)"
            )
        return self.world.root

    # Write APIs (Part A stubs only)
    def spawn(self, *args, **kwargs):
        raise NotImplementedError(RejectReason.NOT_IMPLEMENTED_IN_PART_A.value)

    def resize(self, *args, **kwargs):
        raise NotImplementedError(RejectReason.NOT_IMPLEMENTED_IN_PART_A.value)

    def terminate(self, *args, **kwargs):
        raise NotImplementedError(RejectReason.NOT_IMPLEMENTED_IN_PART_A.value)


def _microservice_spec_index(world_spec: WorldSpec) -> dict[str, MicroserviceSpec]:
    index: dict[str, MicroserviceSpec] = {}
    for app in world_spec.apps:
        for ms in app.microservices:
            index[ms.id] = ms
    return index
