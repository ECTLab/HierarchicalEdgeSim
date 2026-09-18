"""VicinityRound payloads: leftover ρ (Up) and release intent ξ (Down)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HelpRequest:
    """Paper ρ after AllocateResources (leftover Up residual).

    Reserve_c sums these leftovers (Eq. reserve); hats are not required.
    ``t_det`` is Algorithm 2 FCFS.
    """

    seq: int
    tau: int
    ms_id: str
    home_cluster_id: str
    remain_cpu: float
    remain_ram: float
    cpu_min: float
    ram_min: float
    min_mu_step: float = 25.0
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
    evict_container_id: str = ""
    evict_server_id: str = ""


def help_fcfs_key(req: HelpRequest | ReleaseIntent) -> tuple[int, str]:
    """Clarification 2: FCFS by detection time, then microservice id.

    In this discrete env ``t_det`` is the window index ``τ`` (no wall-clock
    ``now()`` inside a tick), so the key is ``(τ, ms_id)``.
    """
    det = req.t_det if req.t_det is not None else req.tau
    return (det, req.ms_id)
