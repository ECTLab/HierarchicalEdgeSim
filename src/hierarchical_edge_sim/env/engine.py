"""Tick engine for Part A (in-memory only)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .config import MicroserviceSpec, WorldSpec
from .routing import distribute
from .traces import TraceStore
from .usage import apply_tick
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

    for tau in range(1, horizon + 1):
        tick(world=world, traces=traces, ms_specs=ms_specs, tau=tau)
        state.current_tau = tau
        if on_after_tick is not None:
            on_after_tick(tau)

    return horizon


def tick(world: World, traces: TraceStore, ms_specs: dict[str, MicroserviceSpec], tau: int) -> None:
    """Execute one tick for all microservices in deterministic id order."""
    for ms in sorted(world.microservices.values(), key=lambda item: item.id):
        containers = [world.containers[cid] for cid in ms.container_ids]
        spec = ms_specs[ms.id]
        offer_lambda = traces.get(ms.id, tau)
        shares = distribute(offer_lambda=offer_lambda, containers=containers, cpu_min_cores=spec.cpu_min_cores)
        for container in containers:
            apply_tick(container=container, lambda_in=shares[container.id], spec=spec, tau=tau)


def _microservice_spec_index(world_spec: WorldSpec) -> dict[str, MicroserviceSpec]:
    index: dict[str, MicroserviceSpec] = {}
    for app in world_spec.apps:
        for ms in app.microservices:
            index[ms.id] = ms
    return index
