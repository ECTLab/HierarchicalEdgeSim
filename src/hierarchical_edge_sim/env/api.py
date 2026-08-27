"""Env facade for Part A workflow and read/write APIs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .config import EPS, ContainerSpec, MicroserviceSpec, WorldSpec, load_yaml, quantize_resource
from .engine import EngineState, run_ticks, tick
from .loans import add_loan, count_ms_on_server, drop_loan, has_loan
from .metrics_log import make_run_id, write_run_outputs
from .models import App, Cluster, Container, LoanTier, Microservice, Server, Vicinity
from .root import RootOrchestrator
from .traces import TraceStore, load_traces
from .validate import validate_or_raise
from .world import (
    World,
    build_world,
    place_container,
    remove_container,
    server_free_cpu_cores,
    server_free_ram_mb,
)


# Apply order lock: terminate → log-only signals → resize → spawn
_APPLY_RANK: dict[str, int] = {
    "terminate": 0,
    "need_horizontal": 1,
    "need_vicinity_help": 2,
    "need_global_help": 3,
    "resize": 4,
    "spawn": 5,
}


class RejectReason(str, Enum):
    NOT_IMPLEMENTED_IN_PART_A = "not_implemented_in_part_a"


class ResizeResultCode(str, Enum):
    OK = "OK"
    UNKNOWN_CONTAINER = "UNKNOWN_CONTAINER"
    BELOW_MS_MIN = "BELOW_MS_MIN"
    ABOVE_MS_MAX = "ABOVE_MS_MAX"
    SERVER_CPU_EXCEEDED = "SERVER_CPU_EXCEEDED"
    SERVER_RAM_EXCEEDED = "SERVER_RAM_EXCEEDED"
    NO_CHANGE = "NO_CHANGE"
    DUPLICATE_IN_BATCH = "DUPLICATE_IN_BATCH"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


class SpawnResultCode(str, Enum):
    OK = "OK"
    UNKNOWN_MS = "UNKNOWN_MS"
    UNKNOWN_SERVER = "UNKNOWN_SERVER"
    BELOW_MS_MIN = "BELOW_MS_MIN"
    ABOVE_MS_MAX = "ABOVE_MS_MAX"
    SERVER_CPU_EXCEEDED = "SERVER_CPU_EXCEEDED"
    SERVER_RAM_EXCEEDED = "SERVER_RAM_EXCEEDED"
    DUPLICATE_CONTAINER_ID = "DUPLICATE_CONTAINER_ID"
    DUPLICATE_IN_BATCH = "DUPLICATE_IN_BATCH"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


class TerminateResultCode(str, Enum):
    OK = "OK"
    UNKNOWN_CONTAINER = "UNKNOWN_CONTAINER"
    LAST_REPLICA = "LAST_REPLICA"
    MS_MISMATCH = "MS_MISMATCH"
    DUPLICATE_IN_BATCH = "DUPLICATE_IN_BATCH"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


@dataclass(frozen=True, slots=True)
class ResizeResult:
    ok: bool
    code: ResizeResultCode
    container_id: str
    cpu_alloc_cores: float
    ram_alloc_mb: float


@dataclass(frozen=True, slots=True)
class SpawnResult:
    ok: bool
    code: SpawnResultCode
    container_id: str
    ms_id: str
    server_id: str
    cpu_alloc_cores: float
    ram_alloc_mb: float


@dataclass(frozen=True, slots=True)
class TerminateResult:
    ok: bool
    code: TerminateResultCode
    container_id: str
    ms_id: str
    server_id: str
    cpu_alloc_cores: float
    ram_alloc_mb: float


@dataclass(frozen=True, slots=True)
class ResizeAction:
    """Vertical resize proposal (absolute alloc targets). Canonical env type."""

    type: str  # "resize"
    ms_id: str
    container_id: str
    cpu_alloc_cores: float | None = None
    ram_alloc_mb: float | None = None
    reason: str = ""
    tau: int | None = None
    actor_cluster_id: str = ""


@dataclass(frozen=True, slots=True)
class SpawnAction:
    """Horizontal scale-out proposal. Canonical env type."""

    type: str  # "spawn"
    ms_id: str
    server_id: str
    container_id: str = ""
    cpu_alloc_cores: float | None = None
    ram_alloc_mb: float | None = None
    reason: str = ""
    tau: int | None = None
    actor_cluster_id: str = ""
    loan_tier: str = ""  # "vicinity" | "global"; S4 grant for foreign spawn


@dataclass(frozen=True, slots=True)
class TerminateAction:
    """Horizontal scale-in proposal. Canonical env type."""

    type: str  # "terminate"
    ms_id: str
    container_id: str
    reason: str = ""
    tau: int | None = None
    actor_cluster_id: str = ""


@dataclass(frozen=True, slots=True)
class NeedHorizontalAction:
    """Signal that vertical room is exhausted but demand remains."""

    type: str  # "need_horizontal"
    ms_id: str
    reason: str = "need_horizontal"
    tau: int | None = None
    residual_cpu_cores: float | None = None
    residual_ram_mb: float | None = None
    container_id: str = ""  # unused; kept for uniform logging


@dataclass(frozen=True, slots=True)
class NeedVicinityHelpAction:
    """Leftover after local BEV/BEH when there is no vicinity root (S2). Log-only."""

    type: str  # "need_vicinity_help"
    ms_id: str
    reason: str = "need_vicinity_help"
    tau: int | None = None
    residual_cpu_cores: float | None = None
    residual_ram_mb: float | None = None
    cluster_id: str = ""
    container_id: str = ""  # unused; kept for uniform logging


@dataclass(frozen=True, slots=True)
class NeedGlobalHelpAction:
    """Leftover after BEG exhausted candidates. Paper LogUnmetDemand; log-only."""

    type: str  # "need_global_help"
    ms_id: str
    reason: str = "need_global_help"
    tau: int | None = None
    residual_cpu_cores: float | None = None
    residual_ram_mb: float | None = None
    cluster_id: str = ""
    container_id: str = ""  # unused; kept for uniform logging


@dataclass(slots=True)
class ActionLogRow:
    tau: int
    autoscaler_name: str
    ms_id: str
    action_type: str
    container_id: str
    reason: str
    cpu_old: float | None
    cpu_new: float | None
    ram_old: float | None
    ram_new: float | None
    result_code: str


@dataclass(slots=True)
class Env:
    world: World
    traces: TraceStore
    world_spec: WorldSpec
    state: EngineState
    action_log: list[ActionLogRow] = field(default_factory=list)
    autoscaler_meta: dict[str, Any] | None = None
    retired_containers: list[Container] = field(default_factory=list)
    used_container_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.used_container_ids.update(self.world.containers)
        self._log_seed_containers()

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

    def run(
        self,
        max_ticks: int | None = None,
        now_utc: datetime | None = None,
        autoscaler: Any | None = None,
    ) -> Path:
        """Run engine then write outputs. max_ticks supports test/dev partial runs."""
        if autoscaler is not None:
            self.autoscaler_meta = _autoscaler_meta(autoscaler)
        if max_ticks is None:
            run_ticks(
                world=self.world,
                traces=self.traces,
                world_spec=self.world_spec,
                state=self.state,
                on_after_tick=(
                    (lambda tau: _invoke_autoscaler(self, autoscaler, tau)) if autoscaler is not None else None
                ),
            )
        else:
            self._run_partial(max_ticks=max_ticks, autoscaler=autoscaler)

        run_id = make_run_id(self.world_spec.sim.seed, now_utc=now_utc)
        return write_run_outputs(
            world=self.world,
            world_spec=self.world_spec,
            traces=self.traces,
            run_id=run_id,
            action_log=self.action_log,
            autoscaler_meta=self.autoscaler_meta,
            retired_containers=self.retired_containers,
        )

    def _run_partial(self, max_ticks: int, autoscaler: Any | None = None) -> None:
        if max_ticks < 0:
            raise ValueError("max_ticks must be >= 0")
        ms_specs = _microservice_spec_index(self.world_spec)
        horizon = self.traces.horizon
        target = min(max_ticks, horizon)
        for tau in range(1, target + 1):
            tick(world=self.world, traces=self.traces, ms_specs=ms_specs, tau=tau)
            self.state.current_tau = tau
            _invoke_autoscaler(self, autoscaler, tau)

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

    def get_app_owner_cluster_id(self, ms_id: str) -> str:
        """Cluster stamped as owner of the app that hosts ``ms_id``."""
        ms = self.world.microservices[ms_id]
        owner = self.world.apps[ms.app_id].owner_cluster_id
        if not owner:
            raise RuntimeError(f"app '{ms.app_id}' has no owner_cluster_id")
        return owner

    def get_microservice(self, ms_id: str) -> Microservice:
        return self.world.microservices[ms_id]

    def get_server_free(self, server_id: str) -> tuple[float, float]:
        return server_free_cpu_cores(self.world, server_id), server_free_ram_mb(self.world, server_id)

    # Hierarchy read APIs (YAML vicinities or Algorithm 1 partition)
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

    def distance(self, cluster_a: str, cluster_b: str) -> float:
        """Inter-cluster distance d(c,c'). Topology only; does not delay requests."""
        return self._require_root().distance(cluster_a, cluster_b)

    def _require_root(self) -> RootOrchestrator:
        if self.world.root is None:
            raise RuntimeError(
                "hierarchy APIs require topology.vicinities or a complete cluster "
                "distance (coords / latency_ms) so the root can publish a partition "
                "(World.root is None)"
            )
        return self.world.root

    def request_worker_owner_scale(
        self,
        *,
        actor_cluster_id: str,
        act: str,
        ms_id: str = "",
        server_id: str = "",
        container_id: str = "",
        cpu_alloc_cores: float | None = None,
        ram_alloc_mb: float | None = None,
        tau: int | None = None,
        loan_tier: str = "",
    ) -> ResizeResult | SpawnResult | TerminateResult:
        """Single writer for a worker: only the worker-owner or a loaned borrower may mutate.

        Direct ``resize`` / ``spawn`` / ``terminate`` remain the physical ops; this is the
        authorized path (paper RequestWorkerOwnerScale). Foreign actors without a loan are
        rejected. Passing ``loan_tier`` (``vicinity`` / ``global``) grants a fresh loan and
        then spawns; a failed spawn rolls the grant back.
        """
        if act == "resize":
            return self._owner_resize(
                actor_cluster_id=actor_cluster_id,
                container_id=container_id,
                cpu_alloc_cores=cpu_alloc_cores,
                ram_alloc_mb=ram_alloc_mb,
            )
        if act == "spawn":
            return self._owner_spawn(
                actor_cluster_id=actor_cluster_id,
                ms_id=ms_id,
                server_id=server_id,
                cpu_alloc_cores=cpu_alloc_cores,
                ram_alloc_mb=ram_alloc_mb,
                container_id=container_id,
                loan_tier=loan_tier,
                tau=tau,
            )
        if act == "terminate":
            return self._owner_terminate(
                actor_cluster_id=actor_cluster_id,
                container_id=container_id,
                ms_id=ms_id or None,
            )
        raise ValueError(f"unknown owner-scale act '{act}'")

    def _authorized_for_server(self, actor_cluster_id: str, server_id: str, ms_id: str) -> bool:
        server = self.world.servers[server_id]
        if actor_cluster_id == server.cluster_id:
            return True
        return has_loan(server, actor_cluster_id, ms_id)

    def _owner_resize(
        self,
        *,
        actor_cluster_id: str,
        container_id: str,
        cpu_alloc_cores: float | None,
        ram_alloc_mb: float | None,
    ) -> ResizeResult:
        if container_id not in self.world.containers:
            return ResizeResult(
                ok=False,
                code=ResizeResultCode.UNKNOWN_CONTAINER,
                container_id=container_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )
        container = self.world.containers[container_id]
        if not self._authorized_for_server(
            actor_cluster_id, container.server_id, container.microservice_id
        ):
            return ResizeResult(
                ok=False,
                code=ResizeResultCode.NOT_AUTHORIZED,
                container_id=container_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )
        return self.resize(
            container_id,
            cpu_alloc_cores=cpu_alloc_cores,
            ram_alloc_mb=ram_alloc_mb,
        )

    def _owner_spawn(
        self,
        *,
        actor_cluster_id: str,
        ms_id: str,
        server_id: str,
        cpu_alloc_cores: float | None,
        ram_alloc_mb: float | None,
        container_id: str,
        loan_tier: str = "",
        tau: int | None = None,
    ) -> SpawnResult:
        if server_id not in self.world.servers:
            return SpawnResult(
                ok=False,
                code=SpawnResultCode.UNKNOWN_SERVER,
                container_id=container_id or "",
                ms_id=ms_id,
                server_id=server_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )
        granted_new_loan = False
        if not self._authorized_for_server(actor_cluster_id, server_id, ms_id):
            tier = _parse_loan_tier(loan_tier)
            if tier is None:
                return SpawnResult(
                    ok=False,
                    code=SpawnResultCode.NOT_AUTHORIZED,
                    container_id=container_id or "",
                    ms_id=ms_id,
                    server_id=server_id,
                    cpu_alloc_cores=0.0,
                    ram_alloc_mb=0.0,
                )
            add_loan(
                self.world.servers[server_id],
                borrower_cluster_id=actor_cluster_id,
                ms_id=ms_id,
                tier=tier,
                ts=int(tau or self.state.current_tau or 0),
            )
            granted_new_loan = True
        result = self.spawn(
            ms_id=ms_id,
            server_id=server_id,
            cpu_alloc_cores=cpu_alloc_cores,
            ram_alloc_mb=ram_alloc_mb,
            container_id=container_id or None,
        )
        if not result.ok and granted_new_loan:
            drop_loan(self.world.servers[server_id], actor_cluster_id, ms_id)
        return result

    def _owner_terminate(
        self,
        *,
        actor_cluster_id: str,
        container_id: str,
        ms_id: str | None,
    ) -> TerminateResult:
        if container_id not in self.world.containers:
            return TerminateResult(
                ok=False,
                code=TerminateResultCode.UNKNOWN_CONTAINER,
                container_id=container_id,
                ms_id=ms_id or "",
                server_id="",
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )
        container = self.world.containers[container_id]
        if not self._authorized_for_server(
            actor_cluster_id, container.server_id, container.microservice_id
        ):
            return TerminateResult(
                ok=False,
                code=TerminateResultCode.NOT_AUTHORIZED,
                container_id=container_id,
                ms_id=container.microservice_id,
                server_id=container.server_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )
        server_id = container.server_id
        ms = container.microservice_id
        result = self.terminate(container_id, ms_id=ms_id)
        if result.ok:
            server = self.world.servers[server_id]
            if server.cluster_id != actor_cluster_id and count_ms_on_server(
                server, self.world.containers, ms
            ) == 0:
                drop_loan(server, actor_cluster_id, ms)
        return result

    def resize(
        self,
        container_id: str,
        cpu_alloc_cores: float | None = None,
        ram_alloc_mb: float | None = None,
    ) -> ResizeResult:
        """Set absolute alloc targets for a container (vertical scale)."""
        if container_id not in self.world.containers:
            return ResizeResult(
                ok=False,
                code=ResizeResultCode.UNKNOWN_CONTAINER,
                container_id=container_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )

        container = self.world.containers[container_id]
        spec = self.get_ms_spec(container.microservice_id)
        new_cpu = container.cpu_alloc_cores if cpu_alloc_cores is None else quantize_resource(float(cpu_alloc_cores))
        new_ram = container.ram_alloc_mb if ram_alloc_mb is None else quantize_resource(float(ram_alloc_mb))

        if cpu_alloc_cores is None and ram_alloc_mb is None:
            return ResizeResult(
                ok=False,
                code=ResizeResultCode.NO_CHANGE,
                container_id=container_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )

        if abs(new_cpu - container.cpu_alloc_cores) <= EPS and abs(new_ram - container.ram_alloc_mb) <= EPS:
            return ResizeResult(
                ok=False,
                code=ResizeResultCode.NO_CHANGE,
                container_id=container_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )

        if new_cpu + EPS < spec.cpu_min_cores or new_ram + EPS < spec.ram_min_mb:
            return ResizeResult(
                ok=False,
                code=ResizeResultCode.BELOW_MS_MIN,
                container_id=container_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )
        if new_cpu > spec.cpu_max_cores + EPS or new_ram > spec.ram_max_mb + EPS:
            return ResizeResult(
                ok=False,
                code=ResizeResultCode.ABOVE_MS_MAX,
                container_id=container_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )

        server = self.world.servers[container.server_id]
        other_cpu = sum(
            self.world.containers[cid].cpu_alloc_cores
            for cid in server.container_ids
            if cid != container_id
        )
        other_ram = sum(
            self.world.containers[cid].ram_alloc_mb
            for cid in server.container_ids
            if cid != container_id
        )
        if other_cpu + new_cpu > server.cpu_cap_cores + EPS:
            return ResizeResult(
                ok=False,
                code=ResizeResultCode.SERVER_CPU_EXCEEDED,
                container_id=container_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )
        if other_ram + new_ram > server.ram_cap_mb + EPS:
            return ResizeResult(
                ok=False,
                code=ResizeResultCode.SERVER_RAM_EXCEEDED,
                container_id=container_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )

        container.cpu_alloc_cores = new_cpu
        container.ram_alloc_mb = new_ram
        return ResizeResult(
            ok=True,
            code=ResizeResultCode.OK,
            container_id=container_id,
            cpu_alloc_cores=new_cpu,
            ram_alloc_mb=new_ram,
        )

    def spawn(
        self,
        ms_id: str,
        server_id: str,
        cpu_alloc_cores: float | None = None,
        ram_alloc_mb: float | None = None,
        container_id: str | None = None,
    ) -> SpawnResult:
        """Create a new container for ``ms_id`` on ``server_id`` (horizontal scale-out).

        Defaults alloc to MS minima when cpu/ram are omitted. Rejects alloc below
        MS min, above MS max, or when the server lacks free capacity.
        """
        if ms_id not in self.world.microservices:
            return SpawnResult(
                ok=False,
                code=SpawnResultCode.UNKNOWN_MS,
                container_id=container_id or "",
                ms_id=ms_id,
                server_id=server_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )
        if server_id not in self.world.servers:
            return SpawnResult(
                ok=False,
                code=SpawnResultCode.UNKNOWN_SERVER,
                container_id=container_id or "",
                ms_id=ms_id,
                server_id=server_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )

        spec = self.get_ms_spec(ms_id)
        new_cpu = quantize_resource(spec.cpu_min_cores if cpu_alloc_cores is None else float(cpu_alloc_cores))
        new_ram = quantize_resource(spec.ram_min_mb if ram_alloc_mb is None else float(ram_alloc_mb))
        cid = container_id if container_id else self._allocate_container_id(ms_id, server_id)

        if cid in self.world.containers:
            return SpawnResult(
                ok=False,
                code=SpawnResultCode.DUPLICATE_CONTAINER_ID,
                container_id=cid,
                ms_id=ms_id,
                server_id=server_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )
        if new_cpu + EPS < spec.cpu_min_cores or new_ram + EPS < spec.ram_min_mb:
            return SpawnResult(
                ok=False,
                code=SpawnResultCode.BELOW_MS_MIN,
                container_id=cid,
                ms_id=ms_id,
                server_id=server_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )
        if new_cpu > spec.cpu_max_cores + EPS or new_ram > spec.ram_max_mb + EPS:
            return SpawnResult(
                ok=False,
                code=SpawnResultCode.ABOVE_MS_MAX,
                container_id=cid,
                ms_id=ms_id,
                server_id=server_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )

        free_cpu, free_ram = self.get_server_free(server_id)
        if new_cpu > free_cpu + EPS:
            return SpawnResult(
                ok=False,
                code=SpawnResultCode.SERVER_CPU_EXCEEDED,
                container_id=cid,
                ms_id=ms_id,
                server_id=server_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )
        if new_ram > free_ram + EPS:
            return SpawnResult(
                ok=False,
                code=SpawnResultCode.SERVER_RAM_EXCEEDED,
                container_id=cid,
                ms_id=ms_id,
                server_id=server_id,
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )

        ms = self.world.microservices[ms_id]
        app = self.world.apps[ms.app_id]
        server = self.world.servers[server_id]
        place_container(
            world=self.world,
            server=server,
            app=app,
            microservice=ms,
            spec=ContainerSpec(
                id=cid,
                server_id=server_id,
                cpu_alloc_cores=new_cpu,
                ram_alloc_mb=new_ram,
            ),
        )
        self.used_container_ids.add(cid)
        return SpawnResult(
            ok=True,
            code=SpawnResultCode.OK,
            container_id=cid,
            ms_id=ms_id,
            server_id=server_id,
            cpu_alloc_cores=new_cpu,
            ram_alloc_mb=new_ram,
        )

    def terminate(self, container_id: str, *, ms_id: str | None = None) -> TerminateResult:
        """Remove a live container (horizontal scale-in).

        Refuses to terminate the last replica of a microservice (routing requires
        ≥1 live container).
        """
        if container_id not in self.world.containers:
            return TerminateResult(
                ok=False,
                code=TerminateResultCode.UNKNOWN_CONTAINER,
                container_id=container_id,
                ms_id=ms_id or "",
                server_id="",
                cpu_alloc_cores=0.0,
                ram_alloc_mb=0.0,
            )

        container = self.world.containers[container_id]
        if ms_id is not None and ms_id != container.microservice_id:
            return TerminateResult(
                ok=False,
                code=TerminateResultCode.MS_MISMATCH,
                container_id=container_id,
                ms_id=container.microservice_id,
                server_id=container.server_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )

        ms = self.world.microservices[container.microservice_id]
        if len(ms.container_ids) <= 1:
            return TerminateResult(
                ok=False,
                code=TerminateResultCode.LAST_REPLICA,
                container_id=container_id,
                ms_id=container.microservice_id,
                server_id=container.server_id,
                cpu_alloc_cores=container.cpu_alloc_cores,
                ram_alloc_mb=container.ram_alloc_mb,
            )

        freed_cpu = container.cpu_alloc_cores
        freed_ram = container.ram_alloc_mb
        removed = remove_container(self.world, container_id)
        self.retired_containers.append(removed)
        return TerminateResult(
            ok=True,
            code=TerminateResultCode.OK,
            container_id=container_id,
            ms_id=container.microservice_id,
            server_id=container.server_id,
            cpu_alloc_cores=freed_cpu,
            ram_alloc_mb=freed_ram,
        )

    def apply_actions(
        self,
        actions: list[Any],
        *,
        tau: int | None = None,
        autoscaler_name: str = "",
    ) -> list[ResizeResult | SpawnResult | TerminateResult]:
        """Apply action proposals one-by-one in deterministic order.

        Order lock: terminate → need_horizontal (log only) → resize → spawn;
        then ``ms_id``, then ``container_id``, then ``server_id``.
        """
        ordered = sorted(
            actions,
            key=lambda a: (
                _APPLY_RANK.get(getattr(a, "type", ""), 99),
                getattr(a, "ms_id", ""),
                getattr(a, "container_id", "") or "",
                getattr(a, "server_id", "") or "",
            ),
        )
        results: list[ResizeResult | SpawnResult | TerminateResult] = []
        seen_resize_containers: set[str] = set()
        seen_terminate_containers: set[str] = set()
        seen_spawn_ids: set[str] = set()
        log_tau = self.state.current_tau if tau is None else tau

        for action in ordered:
            action_type = getattr(action, "type", "")
            if action_type in ("need_horizontal", "need_vicinity_help", "need_global_help"):
                self.action_log.append(
                    ActionLogRow(
                        tau=log_tau,
                        autoscaler_name=autoscaler_name,
                        ms_id=getattr(action, "ms_id", ""),
                        action_type=action_type,
                        container_id=getattr(action, "cluster_id", "") or "",
                        reason=getattr(action, "reason", action_type),
                        cpu_old=None,
                        cpu_new=quantize_resource(float(getattr(action, "residual_cpu_cores", 0.0) or 0.0))
                        if getattr(action, "residual_cpu_cores", None) is not None
                        else None,
                        ram_old=None,
                        ram_new=quantize_resource(float(getattr(action, "residual_ram_mb", 0.0) or 0.0))
                        if getattr(action, "residual_ram_mb", None) is not None
                        else None,
                        result_code="LOGGED",
                    )
                )
                continue

            if action_type == "terminate":
                container_id = getattr(action, "container_id", "")
                if container_id in seen_terminate_containers:
                    result = TerminateResult(
                        ok=False,
                        code=TerminateResultCode.DUPLICATE_IN_BATCH,
                        container_id=container_id,
                        ms_id=getattr(action, "ms_id", ""),
                        server_id="",
                        cpu_alloc_cores=0.0,
                        ram_alloc_mb=0.0,
                    )
                    results.append(result)
                    self._log_terminate_attempt(
                        tau=log_tau,
                        autoscaler_name=autoscaler_name,
                        action=action,
                        result=result,
                    )
                    continue
                seen_terminate_containers.add(container_id)
                result = self.request_worker_owner_scale(
                    actor_cluster_id=self._actor_for_action(action),
                    act="terminate",
                    container_id=container_id,
                    ms_id=getattr(action, "ms_id", "") or "",
                    tau=log_tau,
                )
                results.append(result)
                self._log_terminate_attempt(
                    tau=log_tau,
                    autoscaler_name=autoscaler_name,
                    action=action,
                    result=result,
                )
                continue

            if action_type == "resize":
                container_id = action.container_id
                if container_id in seen_resize_containers:
                    result = ResizeResult(
                        ok=False,
                        code=ResizeResultCode.DUPLICATE_IN_BATCH,
                        container_id=container_id,
                        cpu_alloc_cores=self.world.containers[container_id].cpu_alloc_cores
                        if container_id in self.world.containers
                        else 0.0,
                        ram_alloc_mb=self.world.containers[container_id].ram_alloc_mb
                        if container_id in self.world.containers
                        else 0.0,
                    )
                    results.append(result)
                    self._log_resize_attempt(
                        tau=log_tau,
                        autoscaler_name=autoscaler_name,
                        action=action,
                        cpu_old=result.cpu_alloc_cores,
                        ram_old=result.ram_alloc_mb,
                        result=result,
                    )
                    continue

                seen_resize_containers.add(container_id)
                cpu_old = (
                    self.world.containers[container_id].cpu_alloc_cores
                    if container_id in self.world.containers
                    else 0.0
                )
                ram_old = (
                    self.world.containers[container_id].ram_alloc_mb
                    if container_id in self.world.containers
                    else 0.0
                )
                result = self.request_worker_owner_scale(
                    actor_cluster_id=self._actor_for_action(action),
                    act="resize",
                    container_id=container_id,
                    ms_id=getattr(action, "ms_id", "") or "",
                    cpu_alloc_cores=action.cpu_alloc_cores,
                    ram_alloc_mb=action.ram_alloc_mb,
                    tau=log_tau,
                )
                results.append(result)
                self._log_resize_attempt(
                    tau=log_tau,
                    autoscaler_name=autoscaler_name,
                    action=action,
                    cpu_old=cpu_old,
                    ram_old=ram_old,
                    result=result,
                )
                continue

            if action_type == "spawn":
                requested_id = getattr(action, "container_id", "") or ""
                if requested_id and requested_id in seen_spawn_ids:
                    result = SpawnResult(
                        ok=False,
                        code=SpawnResultCode.DUPLICATE_IN_BATCH,
                        container_id=requested_id,
                        ms_id=getattr(action, "ms_id", ""),
                        server_id=getattr(action, "server_id", ""),
                        cpu_alloc_cores=0.0,
                        ram_alloc_mb=0.0,
                    )
                    results.append(result)
                    self._log_spawn_attempt(
                        tau=log_tau,
                        autoscaler_name=autoscaler_name,
                        action=action,
                        result=result,
                    )
                    continue

                result = self.request_worker_owner_scale(
                    actor_cluster_id=self._actor_for_action(action),
                    act="spawn",
                    ms_id=action.ms_id,
                    server_id=action.server_id,
                    cpu_alloc_cores=action.cpu_alloc_cores,
                    ram_alloc_mb=action.ram_alloc_mb,
                    container_id=requested_id,
                    tau=log_tau,
                    loan_tier=getattr(action, "loan_tier", "") or "",
                )
                if requested_id:
                    seen_spawn_ids.add(requested_id)
                elif result.ok:
                    seen_spawn_ids.add(result.container_id)
                results.append(result)
                self._log_spawn_attempt(
                    tau=log_tau,
                    autoscaler_name=autoscaler_name,
                    action=action,
                    result=result,
                )
                continue

        return results

    def _actor_for_action(self, action: Any) -> str:
        explicit = getattr(action, "actor_cluster_id", "") or ""
        if explicit:
            return explicit
        ms_id = getattr(action, "ms_id", "") or ""
        if not ms_id:
            cid = getattr(action, "container_id", "") or ""
            if cid in self.world.containers:
                ms_id = self.world.containers[cid].microservice_id
        if ms_id and ms_id in self.world.microservices:
            return self.get_app_owner_cluster_id(ms_id)
        return ""

    def _allocate_container_id(self, ms_id: str, server_id: str) -> str:
        n = 1
        while True:
            cid = f"c-{ms_id}-{server_id}-{n}"
            if cid not in self.used_container_ids and cid not in self.world.containers:
                return cid
            n += 1

    def _log_seed_containers(self) -> None:
        """Record YAML-placed replicas so actions.csv starts at world init (τ=0)."""
        for cid in sorted(self.world.containers):
            container = self.world.containers[cid]
            self.action_log.append(
                ActionLogRow(
                    tau=0,
                    autoscaler_name="",
                    ms_id=container.microservice_id,
                    action_type="spawn",
                    container_id=container.id,
                    reason="seed",
                    cpu_old=None,
                    cpu_new=container.cpu_alloc_cores,
                    ram_old=None,
                    ram_new=container.ram_alloc_mb,
                    result_code="OK",
                )
            )

    def _log_resize_attempt(
        self,
        *,
        tau: int,
        autoscaler_name: str,
        action: Any,
        cpu_old: float,
        ram_old: float,
        result: ResizeResult,
    ) -> None:
        self.action_log.append(
            ActionLogRow(
                tau=tau,
                autoscaler_name=autoscaler_name,
                ms_id=getattr(action, "ms_id", ""),
                action_type="resize",
                container_id=result.container_id,
                reason=getattr(action, "reason", ""),
                cpu_old=cpu_old,
                cpu_new=result.cpu_alloc_cores,
                ram_old=ram_old,
                ram_new=result.ram_alloc_mb,
                result_code=result.code.value,
            )
        )

    def _log_spawn_attempt(
        self,
        *,
        tau: int,
        autoscaler_name: str,
        action: Any,
        result: SpawnResult,
    ) -> None:
        self.action_log.append(
            ActionLogRow(
                tau=tau,
                autoscaler_name=autoscaler_name,
                ms_id=result.ms_id or getattr(action, "ms_id", ""),
                action_type="spawn",
                container_id=result.container_id,
                reason=getattr(action, "reason", ""),
                cpu_old=None,
                cpu_new=result.cpu_alloc_cores if result.ok else None,
                ram_old=None,
                ram_new=result.ram_alloc_mb if result.ok else None,
                result_code=result.code.value,
            )
        )

    def _log_terminate_attempt(
        self,
        *,
        tau: int,
        autoscaler_name: str,
        action: Any,
        result: TerminateResult,
    ) -> None:
        self.action_log.append(
            ActionLogRow(
                tau=tau,
                autoscaler_name=autoscaler_name,
                ms_id=result.ms_id or getattr(action, "ms_id", ""),
                action_type="terminate",
                container_id=result.container_id,
                reason=getattr(action, "reason", ""),
                cpu_old=result.cpu_alloc_cores if result.ok else None,
                cpu_new=None,
                ram_old=result.ram_alloc_mb if result.ok else None,
                ram_new=None,
                result_code=result.code.value,
            )
        )


def _parse_loan_tier(raw: str) -> LoanTier | None:
    if not raw:
        return None
    try:
        return LoanTier(raw)
    except ValueError:
        return None


def _invoke_autoscaler(env: Env, autoscaler: Any | None, tau: int) -> None:
    if autoscaler is None:
        return
    actions = autoscaler.on_tick_end(env, tau)
    name = getattr(autoscaler, "name", autoscaler.__class__.__name__)
    results = env.apply_actions(actions or [], tau=tau, autoscaler_name=str(name))
    on_applied = getattr(autoscaler, "on_actions_applied", None)
    if callable(on_applied):
        on_applied(results)


def _autoscaler_meta(autoscaler: Any) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "enabled": True,
        "name": getattr(autoscaler, "name", autoscaler.__class__.__name__),
    }
    params = getattr(autoscaler, "params", None)
    if params is not None:
        dumped = _params_to_plain(params)
        if dumped is not None:
            meta["params"] = dumped
    k = getattr(autoscaler, "decision_every_k_ticks", None)
    if k is not None:
        meta["decision_every_k_ticks"] = k
    cycle = getattr(autoscaler, "cycle", None)
    if cycle:
        meta["cycle"] = cycle
    decide = getattr(autoscaler, "decide", None)
    if decide:
        meta["decide"] = decide
    allocate = getattr(autoscaler, "allocate", None)
    if allocate:
        meta["allocate"] = allocate
    return meta


def _params_to_plain(params: Any) -> dict[str, Any] | None:
    if isinstance(params, dict):
        return dict(params)
    if is_dataclass(params):
        return asdict(params)
    if hasattr(params, "__dict__"):
        return {k: v for k, v in vars(params).items() if not k.startswith("_")}
    return None


def _microservice_spec_index(world_spec: WorldSpec) -> dict[str, MicroserviceSpec]:
    index: dict[str, MicroserviceSpec] = {}
    for app in world_spec.apps:
        for ms in app.microservices:
            index[ms.id] = ms
    return index
