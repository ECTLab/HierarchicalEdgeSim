"""Load autoscaler from YAML config path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .params_base import AutoscalerWrapper, parse_wrapper
from .supported import SUPPORTED_AUTOSCALERS


class AutoscalerLoadError(ValueError):
    """Invalid autoscaler config selection or params."""


def load_autoscaler_from_yaml(config_path: str | Path) -> Any | None:
    """Parse optional top-level autoscaler: block and build the selected scaler.

    Returns None if the block is missing or enabled: false.
    """
    path = Path(config_path).expanduser().resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise AutoscalerLoadError("config root must be a mapping")
    return build_from_wrapper(parse_wrapper(raw.get("autoscaler")))


def build_from_wrapper(wrapper: AutoscalerWrapper | None) -> Any | None:
    if wrapper is None or not wrapper.enabled:
        return None
    assert wrapper.name is not None
    if wrapper.name not in SUPPORTED_AUTOSCALERS:
        raise AutoscalerLoadError(
            f"unknown autoscaler name '{wrapper.name}'; "
            f"supported: {SUPPORTED_AUTOSCALERS}"
        )
    if wrapper.name == "reactive_vertical":
        from hierarchical_edge_sim.autoscaler.reactive_vertical import build

        return build(wrapper.params, decision_every_k_ticks=wrapper.decision_every_k_ticks)
    raise AutoscalerLoadError(f"no builder registered for '{wrapper.name}'")
