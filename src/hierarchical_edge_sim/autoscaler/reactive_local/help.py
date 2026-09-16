"""VicinityRound payloads: leftover ρ (Up) and release intent ξ (Down)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HelpRequest:
    """Paper ρ after AllocateResources (leftover Up residual).

    Tex also carries forecast hats for lender Reserve; this env has no
    Reserve/safe_j, so hats are omitted. ``t_det`` is Algorithm 2 FCFS.
    """

    seq: int
    tau: int
    ms_id: str
    home_cluster_id: str
    remain_cpu: float
    remain_ram: float
    cpu_min: float
    ram_min: float
    min_head_cpu: float = 0.25
    min_head_ram: float = 128.0
    t_det: int | None = None
    kind: str = "rho"


@dataclass(slots=True)
class ReleaseIntent:
    """Paper ξ after AllocateResources (Eq. split: remote share of a Decrease).

    Local Vertical/Horizontal never see borrowed nodes. The leader's
    ScheduleReleases consumes this intent: farthest lenders first, then shrink.
    """

    seq: int
    tau: int
    ms_id: str
    home_cluster_id: str
    remain_cpu: float
    remain_ram: float
    t_det: int | None = None
    mu_tgt: float | None = None
    kind: str = "release"


def help_fcfs_key(req: HelpRequest | ReleaseIntent) -> tuple[int, str]:
    """Clarification 2: FCFS by detection time, then microservice id.

    In this discrete env ``t_det`` is the window index ``τ`` (no wall-clock
    ``now()`` inside a tick), so the key is ``(τ, ms_id)``.
    """
    det = req.t_det if req.t_det is not None else req.tau
    return (det, req.ms_id)
