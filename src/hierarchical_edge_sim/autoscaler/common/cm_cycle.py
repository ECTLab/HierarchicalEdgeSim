"""ClusterManagerCycle (paper Algorithm cmcycle).

Shared by reactive_local and proactive_auto_scaler. The cycle is only the
window orchestrator: callers plug in decide, AllocateResources, and help.
This module must not import those packages (common stays algorithm-light).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hierarchical_edge_sim.env.api import Env


@dataclass(frozen=True, slots=True)
class CycleIntent:
    """One Q_c entry after PredictAndDecide / reactive streaks (Δ ≠ None)."""

    ms_id: str
    cluster_id: str
    t_det: int
    kind: str
    need_cpu: float
    need_ram: float
    sustained: bool = False
    window_index: int | None = None


def cluster_manager_cycle(
    env: Env,
    tau: int,
    *,
    scan_ms: Callable[[str], CycleIntent | None],
    allocate: Callable[[CycleIntent], tuple[list[Any], Any]],
    resolve_help: Callable[..., list[Any]],
) -> list[Any]:
    """Run Algorithm 2 for window ``tau``.

    ``scan_ms`` is CollectServiceMetrics + decide for one MS (or None to skip).
    Cooldown/streak bookkeeping belongs in the caller so every tick still
    observes, matching the sim's stronger InCooldown rule.

    ``allocate`` is AllocateResources (Vertical then Horizontal). Leftover ρ is merged
    FCFS with leftover ξ (release intents) and passed to ``resolve_help``
    (VicinityRound: every member reports, only ℓ(V) computes Π).
    Same-window packing: Q_c is Decrease before Increase, then microservice id.
    Mapping: ``docs/allocate-resources.md``.
    """
    by_cluster: dict[str, list[str]] = {}
    for ms_id in env.list_microservices():
        cid = env.get_app_owner_cluster_id(ms_id)
        by_cluster.setdefault(cid, []).append(ms_id)

    actions: list[Any] = []
    help_q: list[Any] = []
    release_q: list[Any] = []
    for cid in sorted(by_cluster):
        intents: list[CycleIntent] = []
        for ms_id in sorted(by_cluster[cid]):
            intent = scan_ms(ms_id)
            if intent is None:
                continue
            if intent.cluster_id != cid:
                raise ValueError(
                    f"CycleIntent cluster_id {intent.cluster_id!r} != owner {cid!r} for {ms_id}"
                )
            intents.append(intent)
        intents.sort(key=lambda item: (item.t_det, 0 if item.kind == "down" else 1, item.ms_id))
        cluster_releases: list[Any] = []
        for intent in intents:
            ms_actions, leftover = allocate(intent, cluster_releases)
            actions.extend(ms_actions)
            for item in _as_leftovers(leftover):
                item.t_det = intent.t_det if getattr(item, "t_det", None) is None else item.t_det
                item.tau = tau
                if getattr(item, "kind", "rho") == "rho":
                    help_q.append(item)
                else:
                    cluster_releases.append(item)
                    release_q.append(item)

    help_q.sort(key=_help_fcfs_key)
    for seq, req in enumerate(help_q):
        req.seq = seq
    release_q.sort(key=_help_fcfs_key)
    for seq, req in enumerate(release_q):
        req.seq = seq
    actions.extend(resolve_help(env, help_q, actions, tau, release_q))
    return actions


def _as_leftovers(leftover: Any) -> list[Any]:
    if leftover is None:
        return []
    if isinstance(leftover, list):
        return leftover
    return [leftover]


def _help_fcfs_key(req: Any) -> tuple[int, str]:
    det = req.t_det if getattr(req, "t_det", None) is not None else req.tau
    return (det, req.ms_id)
