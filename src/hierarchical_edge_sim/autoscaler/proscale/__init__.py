"""Reduced ProScale clone: SMA, fixed-size replicas, greedy home-then-neighbor."""

from .formula import desired_instances, moving_average
from .params import ProscaleParams, validate_params
from .policy import ProscaleAutoscaler, build

__all__ = [
    "ProscaleAutoscaler",
    "ProscaleParams",
    "build",
    "desired_instances",
    "moving_average",
    "validate_params",
]
