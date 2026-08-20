"""BEH-down prefers μ=0 extras; never the last replica."""

from __future__ import annotations

from hierarchical_edge_sim.autoscaler.common.distribute import ReplicaView, distribute_down
from hierarchical_edge_sim.autoscaler.reactive_local.beh import beh_down
from hierarchical_edge_sim.autoscaler.reactive_local.params import ReactiveLocalParams
from hierarchical_edge_sim.env.config import MicroserviceSpec
from hierarchical_edge_sim.env.models import LoanRecord, LoanTier


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
    server_id: str = "c1-w1",
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
        server_id=server_id,
    )


def test_distribute_down_shrinks_above_floor():
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
    )
    assert len(actions) == 1
    assert actions[0].cpu_alloc_cores == 3.6
    assert actions[0].ram_alloc_mb == 1152.0


def test_distribute_down_may_hit_floor_when_delta_exceeds_room():
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
    )
    assert len(actions) == 1
    assert actions[0].cpu_alloc_cores == 0.5
    assert actions[0].ram_alloc_mb == 256.0


def test_distribute_down_skips_ram_only_shrink_that_does_not_cut_mu():
    """CPU already at the 0.01 quantum vs target; 0.15 MB RAM dust must not chatter."""
    params = ReactiveLocalParams(prefer_consolidate_down=True, theta_free=0.0)
    actions = distribute_down(
        env=None,  # type: ignore[arg-type]
        ms_id="api",
        spec=_spec(),
        params=params,
        replicas=[_view("c-api-1", cpu=0.58, ram=490.88)],
        delta_cpu=0.003,
        delta_ram=0.15,
        tau=334,
        reason="bev_down",
    )
    assert actions == []


def test_distribute_down_trims_idle_ram_in_delta_min_chunks():
    params = ReactiveLocalParams(prefer_consolidate_down=True, theta_free=0.35)
    actions = distribute_down(
        env=None,  # type: ignore[arg-type]
        ms_id="api",
        spec=_spec(),
        params=params,
        replicas=[_view("c-api-1", cpu=0.58, ram=490.88)],
        delta_cpu=0.0,
        delta_ram=128.0,
        tau=334,
        reason="bev_down",
        mu_tgt=7.69,
    )
    assert len(actions) == 1
    assert actions[0].cpu_alloc_cores == 0.58
    assert actions[0].ram_alloc_mb == 362.88


class _Srv:
    cluster_id = "c1"


class _Env:
    def get_server(self, sid: str) -> _Srv:
        _ = sid
        return _Srv()


def test_beh_down_terminates_floor_extra_before_serving():
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
        mu_tgt=1.0,
    )
    assert [a.container_id for a in terms] == ["c-api-2"]
    assert terms[0].reason == "beh_terminate"


class _LoanSrv:
    def __init__(self, cluster_id: str, loans: list[LoanRecord] | None = None) -> None:
        self.cluster_id = cluster_id
        self.loans = list(loans or [])


class _TieredEnv:
    def __init__(self) -> None:
        self._servers = {
            "c1-w1": _LoanSrv("c1"),
            "c2-w1": _LoanSrv(
                "c2",
                [LoanRecord(borrower_cluster_id="c1", ms_id="api", tier=LoanTier.VICINITY, ts=1)],
            ),
            "c3-w1": _LoanSrv(
                "c3",
                [LoanRecord(borrower_cluster_id="c1", ms_id="api", tier=LoanTier.GLOBAL, ts=1)],
            ),
        }

    def get_server(self, sid: str) -> _LoanSrv:
        return self._servers[sid]


def test_beh_down_reason_follows_loan_tier():
    spec = _spec()
    terms = beh_down(
        env=_TieredEnv(),  # type: ignore[arg-type]
        replicas=[
            _view("c-api-1", cpu=1.0, ram=512.0, server_id="c1-w1"),
            _view("c-api-2", cpu=0.5, ram=256.0, server_id="c2-w1"),
            _view("c-api-3", cpu=0.5, ram=256.0, server_id="c3-w1"),
        ],
        ms_id="api",
        owner_cluster_id="c1",
        remain_cpu=8.0,
        remain_ram=2048.0,
        ram_modeled=True,
        skip_ids=set(),
        tau=10,
        spec=spec,
        mu_tgt=1.0,
    )
    assert [(a.container_id, a.reason) for a in terms] == [
        ("c-api-3", "beg_terminate"),
        ("c-api-2", "vicinity_terminate"),
    ]
