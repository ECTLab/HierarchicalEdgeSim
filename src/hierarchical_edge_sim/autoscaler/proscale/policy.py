"""Reduced ProScale: SMA replica count, fixed size, greedy home then neighbor.

Not the TPDS system. No call-graph makespan, no device-speed heterogeneity,
and no cloud offload. Overflow that does not fit in the vicinity is unmet.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from hierarchical_edge_sim.autoscaler.common.distribute import alloc_mu
from hierarchical_edge_sim.autoscaler.reactive_local.horizontal import home_cluster_id
from hierarchical_edge_sim.env.api import Env, SpawnAction, TerminateAction, UnmetDemandAction
from hierarchical_edge_sim.env.config import EPS

from .formula import desired_instances, moving_average
from .params import ProscaleParams, validate_params


@dataclass(slots=True)
class ProscaleAutoscaler:
    name: str = "proscale"
    params: ProscaleParams = field(default_factory=ProscaleParams)
    decision_every_k_ticks: int = 1
    _incoming: dict[str, deque[float]] = field(default_factory=dict)

    def on_tick_end(self, env: Env, tau: int) -> list[Any]:
        if tau % self.decision_every_k_ticks != 0:
            return []
        free_cpu, free_ram = _free_maps(env)
        actions: list[Any] = []
        # Sorted ids: no lender reserve, so an earlier microservice sees the
        # raw free pool and can take it before a later one.
        for ms_id in sorted(env.list_microservices()):
            actions.extend(self._decide_ms(env, ms_id, tau, free_cpu, free_ram))
        return actions

    def on_actions_applied(self, results: list) -> None:
        return None

    def _decide_ms(
        self,
        env: Env,
        ms_id: str,
        tau: int,
        free_cpu: dict[str, float],
        free_ram: dict[str, float],
    ) -> list[Any]:
        observed = _offered_load(env, ms_id, tau)
        hist = self._incoming.setdefault(ms_id, deque(maxlen=self.params.sma_window))
        hist.append(observed)
        cpu, ram = _template_size(env, ms_id)
        spec = env.get_ms_spec(ms_id)
        mu = alloc_mu(cpu, ram, spec, ram_modeled=spec.ram_per_request_mb > EPS)
        desired = desired_instances(
            moving_average(list(hist), self.params.sma_window),
            mu,
            min_replicas=self.params.min_replicas,
            max_replicas=self.params.max_replicas,
        )
        live = list(env.get_microservice(ms_id).container_ids)
        if desired < len(live):
            return _terminate_extras(
                env,
                ms_id,
                tau,
                n_kill=len(live) - desired,
                free_cpu=free_cpu,
                free_ram=free_ram,
            )
        if desired > len(live):
            return _spawn_greedy(
                env,
                ms_id,
                tau,
                n_add=desired - len(live),
                cpu=cpu,
                ram=ram,
                free_cpu=free_cpu,
                free_ram=free_ram,
            )
        return []


def build(params: dict, decision_every_k_ticks: int = 1) -> ProscaleAutoscaler:
    return ProscaleAutoscaler(
        params=validate_params(params),
        decision_every_k_ticks=decision_every_k_ticks,
    )


def _offered_load(env: Env, ms_id: str, tau: int) -> float:
    total = 0.0
    for cid in env.get_microservice(ms_id).container_ids:
        try:
            total += env.get_container(cid).history_at(tau).lambda_in
        except KeyError:
            continue
    return total


def _template_size(env: Env, ms_id: str) -> tuple[float, float]:
    """Fixed instance size: the seed alloc, clamped to the microservice max."""
    spec = env.get_ms_spec(ms_id)
    seed = env.get_container(sorted(env.get_microservice(ms_id).container_ids)[0])
    cpu = seed.initial_cpu_alloc_cores if seed.initial_cpu_alloc_cores is not None else seed.cpu_alloc_cores
    ram = seed.initial_ram_alloc_mb if seed.initial_ram_alloc_mb is not None else seed.ram_alloc_mb
    return min(float(cpu), spec.cpu_max_cores), min(float(ram), spec.ram_max_mb)


def _placement_clusters(env: Env, ms_id: str) -> list[str]:
    home = home_cluster_id(env, ms_id)
    try:
        members = env.list_vicinity_members(env.vicinity_of(home))
    except RuntimeError:
        return [home]
    return [home] + [cluster_id for cluster_id in members if cluster_id != home]


def _ranked_servers(env: Env, ms_id: str) -> list[str]:
    ranked: list[str] = []
    for cluster_id in _placement_clusters(env, ms_id):
        ranked.extend(sorted(env.get_cluster(cluster_id).server_ids))
    return ranked


def _free_maps(env: Env) -> tuple[dict[str, float], dict[str, float]]:
    free_cpu: dict[str, float] = {}
    free_ram: dict[str, float] = {}
    for server_id in env.list_servers():
        cpu, ram = env.get_server_free(server_id)
        free_cpu[server_id] = cpu
        free_ram[server_id] = ram
    return free_cpu, free_ram


def _first_fit(
    ranked: list[str],
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
    cpu: float,
    ram: float,
) -> str | None:
    for sid in ranked:
        if free_cpu.get(sid, 0.0) + EPS >= cpu and free_ram.get(sid, 0.0) + EPS >= ram:
            return sid
    return None


def _spawn_greedy(
    env: Env,
    ms_id: str,
    tau: int,
    *,
    n_add: int,
    cpu: float,
    ram: float,
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
) -> list[Any]:
    if n_add <= 0:
        return []
    home = home_cluster_id(env, ms_id)
    ranked = _ranked_servers(env, ms_id)
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
        on_home = env.get_server(sid).cluster_id == home
        actions.append(
            SpawnAction(
                type="spawn",
                ms_id=ms_id,
                server_id=sid,
                cpu_alloc_cores=cpu,
                ram_alloc_mb=ram,
                reason="horizontal_spawn" if on_home else "vicinity_spawn",
                tau=tau,
                loan_tier="" if on_home else "vicinity",
            )
        )
        free_cpu[sid] -= cpu
        free_ram[sid] -= ram
        placed += 1
    return actions


def _terminate_extras(
    env: Env,
    ms_id: str,
    tau: int,
    *,
    n_kill: int,
    free_cpu: dict[str, float],
    free_ram: dict[str, float],
) -> list[TerminateAction]:
    if n_kill <= 0:
        return []
    home = home_cluster_id(env, ms_id)
    live = list(env.get_microservice(ms_id).container_ids)

    def _release_first(cid: str) -> tuple[int, str]:
        container = env.get_container(cid)
        remote = 0 if env.get_server(container.server_id).cluster_id == home else 1
        return (remote, cid)

    victims = sorted(live, key=_release_first, reverse=True)[:n_kill]
    actions: list[TerminateAction] = []
    for cid in victims:
        container = env.get_container(cid)
        free_cpu[container.server_id] = free_cpu.get(container.server_id, 0.0) + container.cpu_alloc_cores
        free_ram[container.server_id] = free_ram.get(container.server_id, 0.0) + container.ram_alloc_mb
        on_home = env.get_server(container.server_id).cluster_id == home
        actions.append(
            TerminateAction(
                type="terminate",
                ms_id=ms_id,
                container_id=cid,
                reason="horizontal_terminate" if on_home else "vicinity_terminate",
                tau=tau,
            )
        )
    return actions
