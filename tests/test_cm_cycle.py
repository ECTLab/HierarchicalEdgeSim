"""ClusterManagerCycle: per-cluster Q_c then FCFS help merge."""

from __future__ import annotations

from types import SimpleNamespace

from hierarchical_edge_sim.autoscaler.common.cm_cycle import CycleIntent, cluster_manager_cycle
from hierarchical_edge_sim.autoscaler.reactive_local.allocate import resolve_help
from hierarchical_edge_sim.autoscaler.reactive_local.help import HelpRequest, help_fcfs_key
from hierarchical_edge_sim.env.api import NeedVicinityHelpAction


class _FakeEnv:
    root = None

    def __init__(self, owners: dict[str, str], ms_order: list[str]) -> None:
        self._owners = owners
        self._ms_order = ms_order

    def list_microservices(self) -> list[str]:
        return list(self._ms_order)

    def get_app_owner_cluster_id(self, ms_id: str) -> str:
        return self._owners[ms_id]


def test_help_fcfs_key_uses_t_det_then_tau():
    req = HelpRequest(
        seq=3,
        tau=9,
        ms_id="api",
        home_cluster_id="c1",
        remain_cpu=1.0,
        remain_ram=1.0,
        cpu_min=0.5,
        ram_min=1.0,
        t_det=4,
    )
    assert help_fcfs_key(req) == (4, "api")
    req.t_det = None
    assert help_fcfs_key(req) == (9, "api")


def test_cycle_allocates_per_cluster_then_merges_help_by_ms_id():
    env = _FakeEnv(
        owners={"zed": "c1", "api": "c2"},
        ms_order=["zed", "api"],
    )
    allocate_order: list[str] = []

    def scan_ms(ms_id: str) -> CycleIntent:
        return CycleIntent(
            ms_id=ms_id,
            cluster_id=env.get_app_owner_cluster_id(ms_id),
            t_det=1,
            kind="up",
            need_cpu=1.0,
            need_ram=1.0,
        )

    def allocate(intent: CycleIntent):
        allocate_order.append(intent.ms_id)
        leftover = HelpRequest(
            seq=0,
            tau=1,
            ms_id=intent.ms_id,
            home_cluster_id=intent.cluster_id,
            remain_cpu=1.0,
            remain_ram=1.0,
            cpu_min=0.5,
            ram_min=1.0,
            t_det=intent.t_det,
        )
        return [], leftover

    actions = cluster_manager_cycle(
        env, 1, scan_ms=scan_ms, allocate=allocate, resolve_help=resolve_help
    )
    # Local AllocateResources: owner-cluster id order (c1 then c2), not scan order.
    assert allocate_order == ["zed", "api"]
    helps = [a for a in actions if isinstance(a, NeedVicinityHelpAction)]
    # Leader merge is FCFS (t_det, ms_id): api before zed.
    assert [a.ms_id for a in helps] == ["api", "zed"]


def test_cycle_same_cluster_fcfs_by_ms_id():
    env = _FakeEnv(
        owners={"web": "c1", "api": "c1"},
        ms_order=["web", "api"],
    )
    allocate_order: list[str] = []

    def scan_ms(ms_id: str) -> CycleIntent:
        return CycleIntent(
            ms_id=ms_id,
            cluster_id="c1",
            t_det=7,
            kind="up",
            need_cpu=1.0,
            need_ram=0.0,
        )

    def allocate(intent: CycleIntent):
        allocate_order.append(intent.ms_id)
        return [SimpleNamespace(type="resize", ms_id=intent.ms_id)], None

    actions = cluster_manager_cycle(
        env,
        7,
        scan_ms=scan_ms,
        allocate=allocate,
        resolve_help=lambda *_args, **_kwargs: [],
    )
    assert allocate_order == ["api", "web"]
    assert [a.ms_id for a in actions] == ["api", "web"]
