"""World builder and topology registries for Part A."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import AppSpec, ClusterSpec, ContainerSpec, MicroserviceSpec, VicinitySpec, WorldSpec
from .models import App, Cluster, Container, Microservice, Server, Vicinity
from .root import RootOrchestrator


@dataclass(slots=True)
class World:
    apps: dict[str, App] = field(default_factory=dict)
    clusters: dict[str, Cluster] = field(default_factory=dict)
    servers: dict[str, Server] = field(default_factory=dict)
    microservices: dict[str, Microservice] = field(default_factory=dict)
    containers: dict[str, Container] = field(default_factory=dict)
    root: RootOrchestrator | None = None


def build_world(spec: WorldSpec) -> World:
    """Build runtime world registries from validated world spec."""
    world = World()

    for cluster_spec in spec.clusters:
        _register_cluster(world, cluster_spec)

    for app_spec in spec.apps:
        _register_app(world, app_spec)

    world.root = _build_root(spec.vicinities) if spec.vicinities else None
    if world.root is not None:
        _apply_vicinity_mirrors(world)

    return world


def _build_root(vicinity_specs: list[VicinitySpec]) -> RootOrchestrator:
    vicinities = [
        Vicinity(
            id=vspec.id,
            member_cluster_ids=list(vspec.members),
            leader_cluster_id=vspec.leader,
        )
        for vspec in vicinity_specs
    ]
    return RootOrchestrator.from_vicinities(vicinities)


def _apply_vicinity_mirrors(world: World) -> None:
    assert world.root is not None
    for cluster in world.clusters.values():
        vicinity_id = world.root.vicinity_of(cluster.id)
        cluster.vicinity_id = vicinity_id
        cluster.is_vicinity_leader = world.root.is_leader(cluster.id)


def place_container(
    world: World,
    server: Server,
    app: App,
    microservice: Microservice,
    spec: ContainerSpec,
) -> Container:
    """Create and register a container, then wire parent indexes."""
    container = Container(
        id=spec.id,
        app_id=app.id,
        server_id=server.id,
        microservice_id=microservice.id,
        cpu_alloc_cores=spec.cpu_alloc_cores,
        ram_alloc_mb=spec.ram_alloc_mb,
        initial_cpu_alloc_cores=spec.cpu_alloc_cores,
        initial_ram_alloc_mb=spec.ram_alloc_mb,
    )
    world.containers[container.id] = container
    server.container_ids.append(container.id)
    microservice.container_ids.append(container.id)
    return container


def server_free_cpu_cores(world: World, server_id: str) -> float:
    """Return free CPU capacity based on allocated container resources."""
    server = world.servers[server_id]
    used = sum(world.containers[cid].cpu_alloc_cores for cid in server.container_ids)
    return server.cpu_cap_cores - used


def server_free_ram_mb(world: World, server_id: str) -> float:
    """Return free RAM capacity based on allocated container resources."""
    server = world.servers[server_id]
    used = sum(world.containers[cid].ram_alloc_mb for cid in server.container_ids)
    return server.ram_cap_mb - used


def _register_cluster(world: World, cluster_spec: ClusterSpec) -> None:
    cluster = Cluster(id=cluster_spec.id)
    world.clusters[cluster.id] = cluster
    for server_spec in cluster_spec.servers:
        server = Server(
            id=server_spec.id,
            cluster_id=cluster.id,
            cpu_cap_cores=server_spec.cpu_cap_cores,
            ram_cap_mb=server_spec.ram_cap_mb,
        )
        world.servers[server.id] = server
        cluster.server_ids.append(server.id)


def _register_app(world: World, app_spec: AppSpec) -> None:
    app = App(id=app_spec.id)
    world.apps[app.id] = app
    for ms_spec in app_spec.microservices:
        microservice = Microservice(id=ms_spec.id, app_id=app.id)
        world.microservices[microservice.id] = microservice
        app.microservice_ids.append(microservice.id)
        _register_microservice_containers(world, app, microservice, ms_spec)


def _register_microservice_containers(
    world: World,
    app: App,
    microservice: Microservice,
    ms_spec: MicroserviceSpec,
) -> None:
    for container_spec in ms_spec.containers:
        server = world.servers[container_spec.server_id]
        place_container(
            world=world,
            server=server,
            app=app,
            microservice=microservice,
            spec=container_spec,
        )
