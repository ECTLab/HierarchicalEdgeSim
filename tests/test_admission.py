"""Root admission stamp and frozen topology (no T_repart)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from hierarchical_edge_sim.env.admission import (
    admit_application,
    least_loaded_cluster,
    seed_owner_cluster,
    stamp_app_owner,
)
from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.config import (
    AppSpec,
    ClusterSpec,
    ContainerSpec,
    MicroserviceSpec,
    ServerSpec,
    SimConfig,
    WorldSpec,
)
from hierarchical_edge_sim.env.models import App, Microservice
from hierarchical_edge_sim.env.world import build_world


def _two_cluster_spec(*, seed_on: str | None) -> WorldSpec:
    containers = []
    if seed_on == "c1-w1":
        containers = [
            ContainerSpec(
                id="c-api-1",
                server_id="c1-w1",
                cpu_alloc_cores=7.5,
                ram_alloc_mb=1024.0,
            )
        ]
    return WorldSpec(
        sim=SimConfig(tick_sec=1.0, results_dir="results/", seed=1),
        traces_dir="unused/",
        clusters=[
            ClusterSpec(
                id="c1",
                servers=[ServerSpec(id="c1-w1", cpu_cap_cores=8.0, ram_cap_mb=8192.0)],
                coords=(0.0, 0.0),
            ),
            ClusterSpec(
                id="c2",
                servers=[ServerSpec(id="c2-w1", cpu_cap_cores=4.0, ram_cap_mb=8192.0)],
                coords=(1.0, 0.0),
            ),
        ],
        apps=[
            AppSpec(
                id="demo_app",
                microservices=[
                    MicroserviceSpec(
                        id="api",
                        cpu_min_cores=0.5,
                        cpu_max_cores=4.0,
                        ram_min_mb=256.0,
                        ram_max_mb=4096.0,
                        cpu_per_request_cores=0.01,
                        ram_per_request_mb=0.5,
                        trace_file="unused.csv",
                        containers=containers,
                    )
                ],
            )
        ],
        source_path=Path("unused/config.yaml"),
    )


def test_least_loaded_prefers_more_free_cpu():
    world = build_world(_two_cluster_spec(seed_on="c1-w1"))
    assert least_loaded_cluster(world) == "c2"


def test_seed_replicas_keep_their_cluster_as_owner():
    world = build_world(_two_cluster_spec(seed_on="c1-w1"))
    app = world.apps["demo_app"]
    assert seed_owner_cluster(world, app) == "c1"
    assert app.owner_cluster_id == "c1"
    assert admit_application(world, "demo_app") == "c1"


def test_app_without_seed_is_stamped_least_loaded():
    world = build_world(_two_cluster_spec(seed_on="c1-w1"))
    world.apps["new_app"] = App(id="new_app")
    world.microservices["other"] = Microservice(id="other", app_id="new_app")
    world.apps["new_app"].microservice_ids.append("other")
    assert stamp_app_owner(world, world.apps["new_app"]) == "c2"
    assert world.apps["new_app"].owner_cluster_id == "c2"


def test_empty_world_least_loaded_is_smallest_id():
    spec = _two_cluster_spec(seed_on=None)
    world = build_world(spec)
    # Both empty: more free is c1 (8 vs 4). Seed-less app still stamps least-loaded.
    assert world.apps["demo_app"].owner_cluster_id == "c1"
    assert least_loaded_cluster(world) == "c1"


VALID_TRACE = "time_unit,requests\n1,0\n2,25\n3,80\n4,120\n5,50\n"


def _write_coords_world(tmp_path: Path) -> Path:
    cfg: dict[str, Any] = {
        "sim": {"tick_sec": 1.0, "results_dir": str(tmp_path / "results"), "seed": 1},
        "traces_dir": "traces/demo/",
        "topology": {
            "clusters": [
                {
                    "id": "c1",
                    "coords": [0.0, 0.0],
                    "servers": [{"id": "c1-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 16384}],
                },
                {
                    "id": "c2",
                    "coords": [1.0, 0.0],
                    "servers": [{"id": "c2-w1", "cpu_cap_cores": 4.0, "ram_cap_mb": 8192}],
                },
            ]
        },
        "apps": [
            {
                "id": "demo_app",
                "microservices": [
                    {
                        "id": "api",
                        "cpu_min_cores": 0.5,
                        "cpu_max_cores": 4.0,
                        "ram_min_mb": 256,
                        "ram_max_mb": 4096,
                        "cpu_per_request_cores": 0.01,
                        "ram_per_request_mb": 0.5,
                        "trace_file": "api.csv",
                        "containers": [
                            {
                                "id": "c-api-1",
                                "server_id": "c1-w1",
                                "cpu_alloc_cores": 1.0,
                                "ram_alloc_mb": 512,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    tdir = tmp_path / "traces" / "demo"
    tdir.mkdir(parents=True)
    (tdir / "api.csv").write_text(VALID_TRACE, encoding="utf-8")
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def test_vicinities_clusters_and_workers_stay_static_after_run(tmp_path: Path):
    env = Env.from_config(_write_coords_world(tmp_path))
    assert env.root is not None
    before_v = {
        vid: (tuple(env.list_vicinity_members(vid)), env.leader_of(vid))
        for vid in env.list_vicinities()
    }
    before_clusters = set(env.world.clusters)
    before_servers = {sid: env.get_server(sid).cluster_id for sid in env.world.servers}
    env.run(max_ticks=5)
    after_v = {
        vid: (tuple(env.list_vicinity_members(vid)), env.leader_of(vid))
        for vid in env.list_vicinities()
    }
    assert after_v == before_v
    assert set(env.world.clusters) == before_clusters
    assert {sid: env.get_server(sid).cluster_id for sid in env.world.servers} == before_servers
    assert env.get_app("demo_app").owner_cluster_id == "c1"
