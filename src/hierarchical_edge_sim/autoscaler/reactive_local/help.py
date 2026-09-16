"""Leftover scale-up demand after local allocate (VicinityRound payload ρ)."""

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


def help_fcfs_key(req: HelpRequest) -> tuple[int, str]:
    """Clarification 2: FCFS by detection time, then microservice id.

    In this discrete env ``t_det`` is the window index ``τ`` (no wall-clock
    ``now()`` inside a tick), so the key is ``(τ, ms_id)``.
    """
    det = req.t_det if req.t_det is not None else req.tau
    return (det, req.ms_id)
