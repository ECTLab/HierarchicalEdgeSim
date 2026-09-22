"""Kubernetes HPA replica-count baseline (home cluster only)."""

from .formula import apply_scale_up_limit, desired_replicas
from .params import KubernetesHpaParams, validate_params
from .policy import KubernetesHpaAutoscaler, build

__all__ = [
    "KubernetesHpaAutoscaler",
    "KubernetesHpaParams",
    "apply_scale_up_limit",
    "build",
    "desired_replicas",
    "validate_params",
]
