from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from hierarchical_edge_sim.env.config import load_yaml, quantize_resource, to_world_spec

_MINIMAL_CONFIG = {
    "sim": {"tick_sec": 1.0, "results_dir": "results/", "seed": 42},
    "traces_dir": "traces/demo/",
    "topology": {
        "clusters": [
            {
                "id": "c1",
                "servers": [{"id": "c1-w1", "cpu_cap_cores": 8.0, "ram_cap_mb": 16384}],
            }
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


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_load_tiny_yaml_parses(tiny_config_path):
    config = load_yaml(tiny_config_path)

    assert config.sim.tick_sec == 1.0
    assert config.sim.results_dir == "results/"
    assert config.sim.seed == 42
    assert config.traces_dir == "traces/demo/"

    assert len(config.topology) == 1
    cluster = config.topology[0]
    assert cluster.id == "c1"
    assert [server.id for server in cluster.servers] == ["c1-w1", "c1-w2"]
    assert cluster.servers[0].cpu_cap_cores == 8.0
    assert cluster.servers[0].ram_cap_mb == 16384.0

    assert len(config.apps) == 1
    app = config.apps[0]
    assert app.id == "demo_app"
    assert len(app.microservices) == 1

    api = app.microservices[0]
    assert api.id == "api"
    assert api.cpu_min_cores == 0.5
    assert api.cpu_max_cores == 4.0
    assert api.ram_min_mb == 256.0
    assert api.ram_max_mb == 4096.0
    assert api.cpu_per_request_cores == 0.01
    assert api.ram_per_request_mb == 0.5
    assert api.trace_file == "api.csv"

    assert len(api.containers) == 1
    c = api.containers[0]
    assert c.id == "c-api-1"
    assert c.server_id == "c1-w1"
    assert c.cpu_alloc_cores == 1.0
    assert c.ram_alloc_mb == 512.0


def test_world_spec_roundtrip_fields(tiny_config_path):
    raw = load_yaml(tiny_config_path)
    world = to_world_spec(raw)

    cluster_count = len(world.clusters)
    server_count = sum(len(cluster.servers) for cluster in world.clusters)
    app_count = len(world.apps)
    ms_count = sum(len(app.microservices) for app in world.apps)
    container_count = sum(
        len(ms.containers) for app in world.apps for ms in app.microservices
    )

    assert cluster_count == 1
    assert server_count == 2
    assert app_count == 1
    assert ms_count == 1
    assert container_count == 1


def test_load_yaml_rejects_bool_for_numeric_field(tmp_path):
    # bool is a subclass of int in Python; a stray `true`/`false` in a numeric
    # field must not be silently coerced into 1.0/0.0.
    data = deepcopy(_MINIMAL_CONFIG)
    data["sim"]["tick_sec"] = True
    with pytest.raises(ValueError, match="tick_sec"):
        load_yaml(_write_yaml(tmp_path, data))


def test_load_yaml_rejects_bool_for_seed(tmp_path):
    data = deepcopy(_MINIMAL_CONFIG)
    data["sim"]["seed"] = True
    with pytest.raises(ValueError, match="seed"):
        load_yaml(_write_yaml(tmp_path, data))


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_load_yaml_rejects_non_finite_numeric_field(tmp_path, bad_value):
    data = deepcopy(_MINIMAL_CONFIG)
    data["topology"]["clusters"][0]["servers"][0]["cpu_cap_cores"] = bad_value
    path = tmp_path / "config.yaml"
    # yaml.safe_dump renders nan/inf using YAML 1.1 tags; write raw text instead
    # so the loader sees the exact non-finite float regardless of dumper support.
    text = yaml.safe_dump(data, sort_keys=False)
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="finite"):
        load_yaml(path)


def test_quantize_resource_two_decimals():
    assert quantize_resource(0.5769230769230769) == 0.58
    assert quantize_resource(0.5) == 0.5
    assert quantize_resource(512) == 512.0
    assert quantize_resource(0.001) == 0.0
