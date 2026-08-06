"""Common YAML wrapper for selecting an autoscaler."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class AutoscalerWrapper:
    enabled: bool
    name: str | None
    params: dict[str, Any]
    decision_every_k_ticks: int = 1


def parse_wrapper(data: dict[str, Any] | None) -> AutoscalerWrapper | None:
    """Parse top-level autoscaler block. None means disabled / absent."""
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ValueError("autoscaler block must be a mapping")
    enabled = bool(data.get("enabled", True))
    if not enabled:
        return AutoscalerWrapper(enabled=False, name=None, params={})
    name = data.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("autoscaler.enabled requires a string 'name'")
    params = data.get("params", {})
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ValueError("autoscaler.params must be a mapping")
    k = data.get("decision_every_k_ticks", 1)
    if not isinstance(k, int) or k < 1:
        raise ValueError("autoscaler.decision_every_k_ticks must be an int >= 1")
    return AutoscalerWrapper(enabled=True, name=name, params=dict(params), decision_every_k_ticks=k)
