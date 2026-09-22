"""Home-cluster Kubernetes HPA: replica formula, no vertical, no vicinity loans."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.autoscaler.reactive_local.horizontal import (
    home_cluster_id,
    rank_servers_for_spawn,
)
from hierarchical_edge_sim.env.api import Env, SpawnAction, TerminateAction, UnmetDemandAction
from hierarchical_edge_sim.env.config import EPS

from .formula import apply_scale_up_limit, desired_replicas
from .params import KubernetesHpaParams, validate_params


@dataclass(slots=True)
class KubernetesHpaAutoscaler:
    name: str = "kubernetes_hpa"
    params: KubernetesHpaParams = field(default_factory=KubernetesHpaParams)
    decision_every_k_ticks: int = 1
    _desired_hist: dict[str, deque[int]] = field(default_factory=dict)

    def on_tick_end(self, env: Env, tau: int) -> list[Any]:
        if tau % self.decision_every_k_ticks != 0:
            return []
        actions: list[Any] = []
        for ms_id in env.list_microservices():
            actions.extend(self._decide_ms(env, ms_id, tau))
        return actions

    def on_actions_applied(self, results: list) -> None:
        return None

    def _decide_ms(self, env: Env, ms_id: str, tau: int) -> list[Any]:
        live_ids = sorted(env.get_microservice(ms_id).container_ids)
        current = len(live_ids)
        util = _average_cpu_util(env, live_ids, tau)
        raw = desired_replicas(
            current,
            util,
            target=self.params.target_util,
            tolerance=self.params.tolerance,
            min_replicas=self.params.min_replicas,
            max_replicas=self.params.max_replicas,
        )
        hist = self._desired_hist.setdefault(
            ms_id, deque(maxlen=self.params.scale_down_window)
        )
        hist.append(raw)
        if raw > current:
            target_n = apply_scale_up_limit(
                current,
                raw,
                scale_up_pods=self.params.scale_up_pods,
                scale_up_percent=self.params.scale_up_percent,
            )
            return _spawn_home(env, ms_id, tau, n_add=target_n - current)
        conservative = max(hist)
        if conservative < current:
            n_kill = current - max(conservative, self.params.min_replicas)
            return _terminate_extras(env, ms_id, tau, n_kill=n_kill)
        return []


def build(params: dict, decision_every_k_ticks: int = 1) -> KubernetesHpaAutoscaler:
    return KubernetesHpaAutoscaler(
        params=validate_params(params),
        decision_every_k_ticks=decision_every_k_ticks,
    )


def _average_cpu_util(env: Env, container_ids: list[str], tau: int) -> float:
    """Mean usage/request across ready replicas (Kubernetes CPU metric)."""
    if not container_ids:
        return 0.0
    total = 0.0
    n = 0
    for cid in container_ids:
        container = env.get_container(cid)
        try:
            rec = container.history_at(tau)
        except KeyError:
            continue
        alloc = rec.cpu_alloc_cores if rec.cpu_alloc_cores > EPS else container.cpu_alloc_cores
        if alloc <= EPS:
            continue
        total += rec.cpu_usage_cores / alloc
        n += 1
    return total / n if n else 0.0


def _template_size(env: Env, ms_id: str) -> tuple[float, float]:
    """Deployment-like size: the seed's initial alloc, clamped to MS max."""
    spec = env.get_ms_spec(ms_id)
    seed = env.get_container(sorted(env.get_microservice(ms_id).container_ids)[0])
    cpu = seed.initial_cpu_alloc_cores if seed.initial_cpu_alloc_cores is not None else seed.cpu_alloc_cores
    ram = seed.initial_ram_alloc_mb if seed.initial_ram_alloc_mb is not None else seed.ram_alloc_mb
    cpu = min(float(cpu), spec.cpu_max_cores)
    ram = min(float(ram), spec.ram_max_mb)
    return cpu, ram


def _spawn_home(env: Env, ms_id: str, tau: int, n_add: int) -> list[Any]:
    if n_add <= 0:
        return []
    home = home_cluster_id(env, ms_id)
    cpu, ram = _template_size(env, ms_id)
    free_cpu: dict[str, float] = {}
    free_ram: dict[str, float] = {}
    for sid in env.get_cluster(home).server_ids:
        fc, fr = env.get_server_free(sid)
        free_cpu[sid] = fc
        free_ram[sid] = fr
    ranked = rank_servers_for_spawn(env, ms_id, home)
    actions: list[Any] = []
    placed = 0
    for _ in range(n_add):
        sid = _first_fit(ranked, free_cpu, free_ram, cpu, ram)
        if sid is None:
            remain = n_add - placed
            actions.append(
                UnmetDemandAction(
                    type="unmet_demand",
                    ms_id=ms_id,
                    reason="unmet_demand",
                    tau=tau,
                    residual_cpu_cores=remain * cpu,
                    residual_ram_mb=remain * ram,
                    cluster_id=home,
                )
            )
            break
        actions.append(
            SpawnAction(
                type="spawn",
                ms_id=ms_id,
                server_id=sid,
                cpu_alloc_cores=cpu,
                ram_alloc_mb=ram,
                reason="horizontal_spawn",
                tau=tau,
            )
        )
        free_cpu[sid] -= cpu
        free_ram[sid] -= ram
        placed += 1
    return actions


def _first_fit(
    ranked: list[str],
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
    cpu: float,
    ram: float,
) -> str | None:
    for sid in ranked:
        if free_cpu[sid] + EPS >= cpu and free_ram[sid] + EPS >= ram:
            return sid
    return None


def _terminate_extras(env: Env, ms_id: str, tau: int, n_kill: int) -> list[TerminateAction]:
    if n_kill <= 0:
        return []
    live = sorted(env.get_microservice(ms_id).container_ids)
    keep = max(1, len(live) - n_kill)
    # Newest ids first (spawned extras like c-ms150-c1-w1-1); seeds keep simpler ids.
    victims = list(reversed(live))[: len(live) - keep]
    return [
        TerminateAction(
            type="terminate",
            ms_id=ms_id,
            container_id=cid,
            reason="horizontal_terminate",
            tau=tau,
        )
        for cid in victims
    ]
