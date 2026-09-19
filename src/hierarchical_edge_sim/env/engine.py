"""Tick engine for Part A (in-memory only)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .config import DEFAULT_SLA_TIMEOUT_SEC, MicroserviceSpec, WorldSpec
from .latency import origin_to_replica_delay_sec
from .routing import distribute
from .traces import TraceStore
from .usage import apply_tick, serving_capacity
from .world import World


@dataclass(slots=True)
class EngineState:
    current_tau: int = 0


def run_ticks(
    world: World,
    traces: TraceStore,
    world_spec: WorldSpec,
    state: EngineState | None = None,
    *,
    on_after_tick: Callable[[int], None] | None = None,
) -> int:
    """Run the full tick horizon and update container histories.

    Args:
        on_after_tick: Optional callback invoked after each tick's physics with
            ``tau`` already reflected in ``state.current_tau``.

    Returns:
        int: Number of ticks executed.
    """
    if state is None:
        state = EngineState()

    ms_specs = _microservice_spec_index(world_spec)
    horizon = traces.horizon
    tick_sec = float(world_spec.sim.tick_sec)
    sla_timeout_sec = float(world_spec.sim.sla_timeout_sec)
    theta_route = float(world_spec.sim.theta_route)

    for tau in range(1, horizon + 1):
        tick(
            world=world,
            traces=traces,
            ms_specs=ms_specs,
            tau=tau,
            tick_sec=tick_sec,
            sla_timeout_sec=sla_timeout_sec,
            theta_route=theta_route,
        )
        state.current_tau = tau
        if on_after_tick is not None:
            on_after_tick(tau)

    return horizon


def tick(
    world: World,
    traces: TraceStore,
    ms_specs: dict[str, MicroserviceSpec],
    tau: int,
    *,
    tick_sec: float = 1.0,
    sla_timeout_sec: float = DEFAULT_SLA_TIMEOUT_SEC,
    theta_route: float = 1.0,
) -> None:
    """Execute one tick for all microservices in deterministic id order."""
    for ms in sorted(world.microservices.values(), key=lambda item: item.id):
        containers = [world.containers[cid] for cid in ms.container_ids]
        spec = ms_specs[ms.id]
        offer_lambda = traces.get(ms.id, tau)
        owner = world.apps[ms.app_id].owner_cluster_id
        mu = {c.id: serving_capacity(c, spec) for c in containers}
        home_ids = {
            c.id
            for c in containers
            if owner and world.servers[c.server_id].cluster_id == owner
        }
        shares = distribute(
            offer_lambda=offer_lambda,
            containers=containers,
            cpu_min_cores=spec.cpu_min_cores,
            home_ids=home_ids or None,
            mu=mu,
            theta_route=theta_route,
        )
        for container in containers:
            replica_cluster = world.servers[container.server_id].cluster_id
            t_net = origin_to_replica_delay_sec(world, owner, replica_cluster)
            apply_tick(
                container=container,
                lambda_in=shares[container.id],
                spec=spec,
                tau=tau,
                tick_sec=tick_sec,
                sla_timeout_sec=sla_timeout_sec,
                t_net_sec=t_net,
            )


def _microservice_spec_index(world_spec: WorldSpec) -> dict[str, MicroserviceSpec]:
    index: dict[str, MicroserviceSpec] = {}
    for app in world_spec.apps:
        for ms in app.microservices:
            index[ms.id] = ms
    return index
