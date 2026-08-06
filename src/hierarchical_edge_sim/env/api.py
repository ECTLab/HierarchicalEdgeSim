"""Env facade for Part A workflow and read/write APIs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .config import EPS, MicroserviceSpec, WorldSpec, load_yaml
from .engine import EngineState, run_ticks, tick
from .metrics_log import make_run_id, write_run_outputs
from .models import App, Cluster, Container, Microservice, Server, Vicinity
from .root import RootOrchestrator
from .traces import TraceStore, load_traces
from .validate import validate_or_raise
from .world import World, build_world, server_free_cpu_cores, server_free_ram_mb


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


@dataclass(frozen=True, slots=True)
class ResizeResult:
    ok: bool
    code: ResizeResultCode
    container_id: str
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
        new_cpu = container.cpu_alloc_cores if cpu_alloc_cores is None else float(cpu_alloc_cores)
        new_ram = container.ram_alloc_mb if ram_alloc_mb is None else float(ram_alloc_mb)

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

    def apply_actions(
        self,
        actions: list[Any],
        *,
        tau: int | None = None,
        autoscaler_name: str = "",
    ) -> list[ResizeResult]:
        """Apply action proposals one-by-one in deterministic order."""
        ordered = sorted(
            actions,
            key=lambda a: (
                getattr(a, "type", ""),
                getattr(a, "ms_id", ""),
                getattr(a, "container_id", "") or "",
            ),
        )
        results: list[ResizeResult] = []
        seen_resize_containers: set[str] = set()
        log_tau = self.state.current_tau if tau is None else tau

        for action in ordered:
            action_type = getattr(action, "type", "")
            if action_type == "need_horizontal":
                self.action_log.append(
                    ActionLogRow(
                        tau=log_tau,
                        autoscaler_name=autoscaler_name,
                        ms_id=getattr(action, "ms_id", ""),
                        action_type="need_horizontal",
                        container_id="",
                        reason=getattr(action, "reason", "need_horizontal"),
                        cpu_old=None,
                        cpu_new=getattr(action, "residual_cpu_cores", None),
                        ram_old=None,
                        ram_new=getattr(action, "residual_ram_mb", None),
                        result_code="LOGGED",
                    )
                )
                continue

            if action_type != "resize":
                continue

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
            result = self.resize(
                container_id=container_id,
                cpu_alloc_cores=action.cpu_alloc_cores,
                ram_alloc_mb=action.ram_alloc_mb,
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
        return results

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

    # Write APIs (stubs for horizontal)
    def spawn(self, *args, **kwargs):
        raise NotImplementedError(RejectReason.NOT_IMPLEMENTED_IN_PART_A.value)

    def terminate(self, *args, **kwargs):
        raise NotImplementedError(RejectReason.NOT_IMPLEMENTED_IN_PART_A.value)


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
        if hasattr(params, "__dict__"):
            meta["params"] = {
                k: v for k, v in vars(params).items() if not k.startswith("_")
            }
        elif isinstance(params, dict):
            meta["params"] = dict(params)
    k = getattr(autoscaler, "decision_every_k_ticks", None)
    if k is not None:
        meta["decision_every_k_ticks"] = k
    return meta


def _microservice_spec_index(world_spec: WorldSpec) -> dict[str, MicroserviceSpec]:
    index: dict[str, MicroserviceSpec] = {}
    for app in world_spec.apps:
        for ms in app.microservices:
            index[ms.id] = ms
    return index
