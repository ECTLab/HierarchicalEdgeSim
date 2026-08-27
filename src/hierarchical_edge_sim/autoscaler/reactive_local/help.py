"""Leftover scale-up demand after a ladder rung (vicinity help, then BEG)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HelpRequest:
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
