from __future__ import annotations

import pytest

from hierarchical_edge_sim.env.api import Env
from hierarchical_edge_sim.env.validate import ConfigError


def test_from_config_invalid_raises(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
sim:
  tick_sec: 0
  results_dir: results/
  seed: 42
traces_dir: traces/demo/
topology:
  clusters: []
apps: []
""".strip()
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        Env.from_config(bad)


def test_get_time_after_partial_run(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    assert env.get_time() == 0
    env.run(max_ticks=3)
    assert env.get_time() == 3


def test_list_containers_includes_c_api_1(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    assert env.list_containers() == ["c-api-1"]
    assert env.list_apps() == ["demo_app"]
    assert env.list_microservices() == ["api"]
    assert env.list_servers() == ["c1-w1", "c1-w2"]
    assert env.list_clusters() == ["c1"]
