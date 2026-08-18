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
