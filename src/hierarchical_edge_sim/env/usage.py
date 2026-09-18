"""Per-tick usage formulas for Part A."""

from __future__ import annotations

from .config import DEFAULT_SLA_TIMEOUT_SEC, EPS, MicroserviceSpec, quantize_resource
from .latency import offered_delay
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
    *,
    tick_sec: float = 1.0,
    sla_timeout_sec: float = DEFAULT_SLA_TIMEOUT_SEC,
    t_net_sec: float = 0.0,
) -> ContainerTickRecord:
    """Apply one tick of incoming load to a container and append history."""
    cpu_serve_cores = max(0.0, container.cpu_alloc_cores - spec.cpu_min_cores)
    ram_serve_mb = max(0.0, container.ram_alloc_mb - spec.ram_min_mb)
    mu = serving_capacity(container, spec)

    lambda_served = min(lambda_in, mu)
    lambda_dropped = lambda_in - lambda_served
    delay = offered_delay(
        lambda_in=lambda_in,
        mu=mu,
        tick_sec=tick_sec,
        sla_timeout_sec=sla_timeout_sec,
        t_net_sec=t_net_sec,
    )

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
        t_net_sec=delay.t_net_sec,
        t_mean_offered_sec=delay.t_mean_offered_sec,
        t_p95_offered_sec=delay.t_p95_offered_sec,
        t_p99_offered_sec=delay.t_p99_offered_sec,
        sla_miss_requests=delay.sla_miss_requests,
        t_wait_sec=delay.t_wait_sec,
    )
    container.append_history(record)
    return record
