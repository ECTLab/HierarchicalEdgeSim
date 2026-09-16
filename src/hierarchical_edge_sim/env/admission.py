"""Root application admission: least-loaded cluster stamp (paper § Cloud layer).

Clusters, workers, and vicinities are static for a run. Admission is a
pre-run stamp at world build — not a live join path and not T_repart.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import App
    from .world import World


def least_loaded_cluster(world: World) -> str:
    """Cluster currently carrying the least load (most free CPU, then RAM, then id)."""
    from .world import server_free_cpu_cores, server_free_ram_mb

    if not world.clusters:
        raise RuntimeError("no clusters to admit onto")

    def key(cluster_id: str) -> tuple[float, float, str]:
        sids = world.clusters[cluster_id].server_ids
        free_cpu = sum(server_free_cpu_cores(world, sid) for sid in sids)
        free_ram = sum(server_free_ram_mb(world, sid) for sid in sids)
        return (-free_cpu, -free_ram, cluster_id)

    return min(world.clusters, key=key)


def seed_owner_cluster(world: World, app: App) -> str | None:
    """Destination already chosen by YAML seed replicas, if any."""
    for ms_id in app.microservice_ids:
        ms = world.microservices[ms_id]
        if not ms.container_ids:
            continue
        first = sorted(ms.container_ids)[0]
        return world.servers[world.containers[first].server_id].cluster_id
    return None


def stamp_app_owner(world: World, app: App) -> str:
    """Paper stamp: seed placement if present, otherwise least-loaded cluster."""
    dest = seed_owner_cluster(world, app) or least_loaded_cluster(world)
    app.owner_cluster_id = dest
    return dest


def admit_application(world: World, app_id: str) -> str:
    """Root admission duty for one app. Does not add or move workers."""
    return stamp_app_owner(world, world.apps[app_id])
