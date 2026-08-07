"""Allocate proactive residuals via common.distribute (paired CPU/RAM)."""

from __future__ import annotations

from typing import Any

from hierarchical_edge_sim.autoscaler.common.distribute import (
    DistributeParams,
    distribute_down,
    distribute_up,
)
from hierarchical_edge_sim.autoscaler.common.snapshot import MsSnapshot
from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.config import EPS

from .decide import DecideResult, Direction


def allocate_vertical(
    env: Env,
    *,
    snap: MsSnapshot,
    tau: int,
    decision: DecideResult,
    params: DistributeParams,
) -> list[Any]:
    if decision.direction is Direction.NONE:
        return []
    if decision.direction is Direction.UP:
        if decision.delta_cpu <= EPS and decision.delta_ram <= EPS:
            return []
        return distribute_up(
            env=env,
            ms_id=snap.ms_id,
            spec=snap.spec,
            params=params,
            replicas=snap.replicas,
            delta_cpu=decision.delta_cpu,
            delta_ram=decision.delta_ram,
            tau=tau,
            reason="proactive_up",
        )

    # DOWN — distribute expects non-negative magnitudes
    delta_cpu = abs(decision.delta_cpu)
    delta_ram = abs(decision.delta_ram)
    if delta_cpu <= EPS and delta_ram <= EPS:
        return []
    return distribute_down(
        env=env,
        ms_id=snap.ms_id,
        spec=snap.spec,
        params=params,
        replicas=snap.replicas,
        delta_cpu=delta_cpu,
        delta_ram=delta_ram,
        tau=tau,
        reason="proactive_down",
    )
