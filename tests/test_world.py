from hierarchical_edge_sim.env.config import load_yaml
from hierarchical_edge_sim.env.validate import validate_or_raise
from hierarchical_edge_sim.env.world import build_world, server_free_cpu_cores, server_free_ram_mb


def _build_tiny_world(tiny_config_path):
    raw = load_yaml(tiny_config_path)
    spec = validate_or_raise(raw)
    return build_world(spec)


def test_build_world_tiny_topology(tiny_config_path):
    world = _build_tiny_world(tiny_config_path)
    assert len(world.clusters) == 1
    assert len(world.servers) == 2
    assert len(world.apps) == 1
    assert len(world.microservices) == 1
    assert len(world.containers) == 1


def test_server_container_ids(tiny_config_path):
    world = _build_tiny_world(tiny_config_path)
    assert world.servers["c1-w1"].container_ids == ["c-api-1"]
    assert world.servers["c1-w2"].container_ids == []


def test_server_free_capacity_tiny(tiny_config_path):
    world = _build_tiny_world(tiny_config_path)
    assert server_free_cpu_cores(world, "c1-w1") == 7.0
    assert server_free_ram_mb(world, "c1-w1") == 15872.0
    assert server_free_cpu_cores(world, "c1-w2") == 8.0
    assert server_free_ram_mb(world, "c1-w2") == 16384.0


def test_cluster_server_backpointer(tiny_config_path):
    world = _build_tiny_world(tiny_config_path)
    assert world.servers["c1-w1"].cluster_id == "c1"
    assert world.servers["c1-w2"].cluster_id == "c1"
    assert world.clusters["c1"].server_ids == ["c1-w1", "c1-w2"]
