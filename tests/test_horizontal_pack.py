"""HorizontalScaling packs leftover above minima; VerticalScaling will not grow a replica that still has μ=0."""

from __future__ import annotations

from hierarchical_edge_sim.autoscaler.common.distribute import ReplicaView, distribute_up
from hierarchical_edge_sim.autoscaler.reactive_local.horizontal import packed_spawn_size
from hierarchical_edge_sim.autoscaler.reactive_local.params import ReactiveLocalParams
from hierarchical_edge_sim.env.config import MicroserviceSpec


def _spec() -> MicroserviceSpec:
    return MicroserviceSpec(
        id="api",
        cpu_min_cores=0.5,
        cpu_max_cores=4.0,
        ram_min_mb=256.0,
        ram_max_mb=4096.0,
        cpu_per_request_cores=0.0004,
        ram_per_request_mb=0.02,
        trace_file="",
        containers=[],
    )


def test_packed_spawn_uses_leftover_headroom():
    out = packed_spawn_size(
        remain_cpu=0.2,
        remain_ram=128.0,
        spec=_spec(),
        free_cpu=8.0,
        free_ram=4096.0,
        min_head_cpu=0.25,
        min_head_ram=128.0,
    )
    assert out == (0.7, 266.0, 0.2, 10.0)


def test_packed_spawn_adds_sliver_on_the_other_resource():
    out = packed_spawn_size(
        remain_cpu=0.4,
        remain_ram=0.0,
        spec=_spec(),
        free_cpu=8.0,
        free_ram=4096.0,
        min_head_cpu=0.25,
        min_head_ram=128.0,
    )
    assert out is not None
    cpu, ram, head_cpu, head_ram = out
    assert cpu == 0.9
    assert ram == 276.0
    assert head_cpu == 0.4
    assert head_ram == 20.0


def test_packed_spawn_refuses_floor_only_server():
    assert (
        packed_spawn_size(
            remain_cpu=0.4,
            remain_ram=128.0,
            spec=_spec(),
            free_cpu=0.5,
            free_ram=256.0,
            min_head_cpu=0.25,
            min_head_ram=128.0,
        )
        is None
    )


def test_distribute_up_skips_cpu_only_grow_on_ram_floor():
    params = ReactiveLocalParams()
    actions = distribute_up(
        env=None,  # type: ignore[arg-type]
        ms_id="api",
        spec=_spec(),
        params=params,
        replicas=[
            ReplicaView(
                container_id="c-api-1",
                drop=10.0,
                q=1.0,
                slack=0.0,
                cpu_alloc=3.19,
                ram_alloc=256.0,
                room_up_cpu=0.81,
                room_up_ram=3840.0,
                room_down_cpu=2.69,
                room_down_ram=0.0,
            )
        ],
        delta_cpu=0.5,
        delta_ram=0.0,
        tau=300,
        reason="vertical_up",
    )
    resizes = [a for a in actions if getattr(a, "type", "") == "resize"]
    assert resizes == []
    leftover = [a for a in actions if getattr(a, "type", "") == "need_horizontal"]
    assert leftover and leftover[0].residual_cpu_cores == 0.5


def test_distribute_up_grows_ram_when_that_is_the_dead_resource():
    params = ReactiveLocalParams()
    actions = distribute_up(
        env=None,  # type: ignore[arg-type]
        ms_id="api",
        spec=_spec(),
        params=params,
        replicas=[
            ReplicaView(
                container_id="c-api-1",
                drop=10.0,
                q=1.0,
                slack=0.0,
                cpu_alloc=3.19,
                ram_alloc=256.0,
                room_up_cpu=0.81,
                room_up_ram=3840.0,
                room_down_cpu=2.69,
                room_down_ram=0.0,
            )
        ],
        delta_cpu=0.5,
        delta_ram=128.0,
        tau=300,
        reason="vertical_up",
    )
    resizes = [a for a in actions if getattr(a, "type", "") == "resize"]
    assert len(resizes) == 1
    assert resizes[0].cpu_alloc_cores == 3.19
    assert resizes[0].ram_alloc_mb == 281.0
