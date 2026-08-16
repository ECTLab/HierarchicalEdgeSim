"""Last serving replica must keep μ>0 under proactive BEV-down / BEH-down."""

from __future__ import annotations

from hierarchical_edge_sim.autoscaler.common.distribute import ReplicaView, distribute_down
from hierarchical_edge_sim.autoscaler.reactive_local.beh import beh_down
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


def _view(
    cid: str,
    *,
    cpu: float,
    ram: float,
    cpu_min: float = 0.5,
    ram_min: float = 256.0,
    slack: float = 0.9,
    drop: float = 0.0,
) -> ReplicaView:
    return ReplicaView(
        container_id=cid,
        drop=drop,
        q=1.0 - slack,
        slack=slack,
        cpu_alloc=cpu,
        ram_alloc=ram,
        room_up_cpu=max(0.0, 4.0 - cpu),
        room_up_ram=max(0.0, 4096.0 - ram),
        room_down_cpu=max(0.0, cpu - cpu_min),
        room_down_ram=max(0.0, ram - ram_min),
        server_id="c1-w1",
    )


def test_distribute_down_refuses_floor_on_last_serving():
    params = ReactiveLocalParams(prefer_consolidate_down=True, theta_free=0.0)
    actions = distribute_down(
        env=None,  # type: ignore[arg-type]
        ms_id="api",
        spec=_spec(),
        params=params,
        replicas=[_view("c-api-1", cpu=0.56, ram=312.0)],
        delta_cpu=1.0,
        delta_ram=200.0,
        tau=180,
        reason="bev_down",
        protect_last_serving=True,
    )
    assert actions == []


def test_distribute_down_still_shrinks_above_floor():
    params = ReactiveLocalParams(prefer_consolidate_down=True, theta_free=0.0)
    actions = distribute_down(
        env=None,  # type: ignore[arg-type]
        ms_id="api",
        spec=_spec(),
        params=params,
        replicas=[_view("c-api-1", cpu=4.0, ram=1280.0)],
        delta_cpu=0.4,
        delta_ram=128.0,
        tau=159,
        reason="bev_down",
        protect_last_serving=True,
    )
    assert len(actions) == 1
    assert actions[0].cpu_alloc_cores == 3.6
    assert actions[0].ram_alloc_mb == 1152.0


def test_distribute_down_refuses_ram_floor_while_cpu_headroom_remains():
    """Routing is CPU-weighted; RAM-at-floor + CPU>min steals load and drops it."""
    params = ReactiveLocalParams(prefer_consolidate_down=True, theta_free=0.0)
    actions = distribute_down(
        env=None,  # type: ignore[arg-type]
        ms_id="api",
        spec=_spec(),
        params=params,
        replicas=[
            _view("c-api-1", cpu=4.0, ram=1280.0),
            _view("c-other", cpu=4.0, ram=384.0, slack=1.0),
        ],
        delta_cpu=1.0,
        delta_ram=200.0,
        tau=171,
        reason="bev_down",
        protect_last_serving=True,
    )
    assert actions
    for action in actions:
        assert action.ram_alloc_mb > 256.0
        assert action.cpu_alloc_cores > 0.5


def test_distribute_down_unprotected_may_hit_floor():
    params = ReactiveLocalParams(prefer_consolidate_down=True, theta_free=0.0)
    actions = distribute_down(
        env=None,  # type: ignore[arg-type]
        ms_id="api",
        spec=_spec(),
        params=params,
        replicas=[_view("c-api-1", cpu=0.56, ram=312.0)],
        delta_cpu=1.0,
        delta_ram=200.0,
        tau=180,
        reason="bev_down",
        protect_last_serving=False,
    )
    assert len(actions) == 1
    assert actions[0].cpu_alloc_cores == 0.5
    assert actions[0].ram_alloc_mb == 256.0


class _Srv:
    cluster_id = "c1"


class _Env:
    def get_server(self, sid: str) -> _Srv:
        _ = sid
        return _Srv()


def test_beh_down_skips_last_serving_when_others_are_at_floor():
    spec = _spec()
    serving = _view("c-api-1", cpu=3.19, ram=400.0, slack=1.0, drop=0.0)
    idle = _view("c-api-2", cpu=0.5, ram=256.0, slack=1.0, drop=0.0)
    terms = beh_down(
        env=_Env(),  # type: ignore[arg-type]
        replicas=[serving, idle],
        ms_id="api",
        owner_cluster_id="c1",
        remain_cpu=4.0,
        remain_ram=1024.0,
        ram_modeled=True,
        skip_ids=set(),
        tau=300,
        spec=spec,
        protect_last_serving=True,
    )
    assert [a.container_id for a in terms] == ["c-api-2"]
