"""Per-tick usage formulas for Part A."""

from __future__ import annotations

from .config import EPS, MicroserviceSpec, quantize_resource
from .models import Container, ContainerTickRecord


def serving_capacity(container: Container, spec: MicroserviceSpec) -> float:
    """Compute per-tick service capacity μ for one container."""
    cpu_serve_cores = max(0.0, container.cpu_alloc_cores - spec.cpu_min_cores)
    ram_serve_mb = max(0.0, container.ram_alloc_mb - spec.ram_min_mb)

    mu_cpu = cpu_serve_cores / spec.cpu_per_request_cores
    mu_ram = ram_serve_mb / spec.ram_per_request_mb if spec.ram_per_request_mb > EPS else float("inf")
    return min(mu_cpu, mu_ram)


def apply_tick(
    container: Container,
    lambda_in: float,
    spec: MicroserviceSpec,
    tau: int,
) -> ContainerTickRecord:
    """Apply one tick of incoming load to a container and append history."""
    cpu_serve_cores = max(0.0, container.cpu_alloc_cores - spec.cpu_min_cores)
    ram_serve_mb = max(0.0, container.ram_alloc_mb - spec.ram_min_mb)
    mu = serving_capacity(container, spec)

    lambda_served = min(lambda_in, mu)
    lambda_dropped = lambda_in - lambda_served

    cpu_usage_cores = quantize_resource(
        min(
            container.cpu_alloc_cores,
            spec.cpu_min_cores + lambda_served * spec.cpu_per_request_cores,
        )
    )
    ram_usage_mb = quantize_resource(
        min(
            container.ram_alloc_mb,
            spec.ram_min_mb + lambda_served * spec.ram_per_request_mb,
        )
    )

    q_cpu = (lambda_served * spec.cpu_per_request_cores) / max(cpu_serve_cores, EPS)
    q_ram = (lambda_served * spec.ram_per_request_mb) / max(ram_serve_mb, EPS)

    record = ContainerTickRecord(
        tau=tau,
        lambda_in=lambda_in,
        lambda_served=lambda_served,
        lambda_dropped=lambda_dropped,
        cpu_usage_cores=cpu_usage_cores,
        ram_usage_mb=ram_usage_mb,
        cpu_alloc_cores=container.cpu_alloc_cores,
        ram_alloc_mb=container.ram_alloc_mb,
        q_cpu=q_cpu,
        q_ram=q_ram,
    )
    container.append_history(record)
    return record
