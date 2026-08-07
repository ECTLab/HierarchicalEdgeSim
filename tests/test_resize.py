"""Tests for Env.resize (Step 1)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from hierarchical_edge_sim.env.api import Env, ResizeResultCode
from hierarchical_edge_sim.env.config import EPS


def test_resize_cpu_up_ok(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    result = env.resize("c-api-1", cpu_alloc_cores=1.5)
    assert result.ok
    assert result.code == ResizeResultCode.OK
    assert env.get_container("c-api-1").cpu_alloc_cores == 1.5
    assert env.get_container("c-api-1").ram_alloc_mb == 512.0


def test_resize_rejects_above_ms_max(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    before = env.get_container("c-api-1").cpu_alloc_cores
    result = env.resize("c-api-1", cpu_alloc_cores=9.0)
    assert not result.ok
    assert result.code == ResizeResultCode.ABOVE_MS_MAX
    assert env.get_container("c-api-1").cpu_alloc_cores == before


def test_resize_rejects_server_packing(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    # tiny: c1-w1 has 8 cores, c-api-1 uses 1.0; asking for 8.1 exceeds server.
    result = env.resize("c-api-1", cpu_alloc_cores=8.1)
    # Also above ms max 4.0 — ABOVE_MS_MAX checked first.
    assert result.code == ResizeResultCode.ABOVE_MS_MAX

    # Within MS max but packing: put a second container conceptually by resizing to fill.
    # On tiny only one container on c1-w1; cpu_max is 4.0 so packing alone needs shared server.
    # Use resize to 4.0 (ok), then we can't exceed server with one container under ms max on 8-core.
    # Dedicated packing case: lower free by using get_server — for single container on 8-core
    # with max 4.0, SERVER_CPU cannot fire. Force via temporary cap trick on world:
    env.world.servers["c1-w1"].cpu_cap_cores = 1.2
    result = env.resize("c-api-1", cpu_alloc_cores=1.5)
    assert not result.ok
    assert result.code == ResizeResultCode.SERVER_CPU_EXCEEDED
    assert env.get_container("c-api-1").cpu_alloc_cores == 1.0


def test_resize_ram_only_keeps_cpu(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    result = env.resize("c-api-1", ram_alloc_mb=768.0)
    assert result.ok
    assert env.get_container("c-api-1").cpu_alloc_cores == 1.0
    assert env.get_container("c-api-1").ram_alloc_mb == 768.0


def test_resize_noop_within_eps(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    result = env.resize("c-api-1", cpu_alloc_cores=1.0 + EPS / 2)
    assert not result.ok
    assert result.code == ResizeResultCode.NO_CHANGE


def test_resize_unknown_container(tiny_config_path):
    env = Env.from_config(tiny_config_path)
    result = env.resize("missing", cpu_alloc_cores=1.5)
    assert not result.ok
    assert result.code == ResizeResultCode.UNKNOWN_CONTAINER


def test_meta_initial_alloc_survives_resize(tiny_config_path, tmp_path):
    env = Env.from_config(tiny_config_path)
    from dataclasses import replace

    env.world_spec = replace(env.world_spec, sim=replace(env.world_spec.sim, results_dir=str(tmp_path / "results")))

    assert env.get_container("c-api-1").initial_cpu_alloc_cores == 1.0
    env.resize("c-api-1", cpu_alloc_cores=2.0)
    assert env.get_container("c-api-1").cpu_alloc_cores == 2.0
    assert env.get_container("c-api-1").initial_cpu_alloc_cores == 1.0

    run_dir = env.run(now_utc=datetime(2026, 1, 1, tzinfo=UTC))
    meta_path = run_dir / "apps" / "demo_app" / "api" / "c-api-1.meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["initial_cpu_alloc_cores"] == 1.0
    assert meta["final_cpu_alloc_cores"] == 2.0
