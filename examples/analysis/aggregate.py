"""Aggregation helpers for multi-container / multi-app analysis."""

from __future__ import annotations

from collections import defaultdict

from dataclasses import dataclass
from math import ceil

from .io import ActionRow, ContainerSeries


def sum_series(series_list: list[list[float]]) -> list[float]:
    if not series_list:
        return []
    n = len(series_list[0])
    return [sum(series[i] for series in series_list) for i in range(n)]


def series_on_tau(
    tau_full: list[int],
    tau: list[int],
    values: list[float],
    *,
    fill: float = 0.0,
) -> list[float]:
    """Map a (possibly partial) container series onto the full tick axis."""
    by_t = dict(zip(tau, values))
    return [float(by_t.get(t, fill)) for t in tau_full]


def sum_tau_window(
    tau: list[int],
    values: list[float],
    *,
    start: int,
    end: int,
) -> float:
    """Sum ``values`` on ticks in ``[start, end]`` inclusive."""
    return float(sum(v for t, v in zip(tau, values) if start <= t <= end))


def sum_aligned(
    tau_full: list[int],
    containers: list[ContainerSeries],
    attr: str,
) -> list[float]:
    parts = [
        series_on_tau(tau_full, c.tau, getattr(c, attr))
        for c in containers
    ]
    if not parts:
        return [0.0] * len(tau_full)
    return sum_series(parts)


def demand_weighted_aligned(
    tau_full: list[int],
    containers: list[ContainerSeries],
    value_attr: str,
    weight_attr: str = "incoming",
) -> list[float]:
    """Per-tick demand-weighted mean of ``value_attr`` (0 when no weight)."""
    out: list[float] = []
    for t in tau_full:
        num = 0.0
        den = 0.0
        for c in containers:
            by_v = dict(zip(c.tau, getattr(c, value_attr)))
            by_w = dict(zip(c.tau, getattr(c, weight_attr)))
            w = float(by_w.get(t, 0.0))
            if w <= 0.0:
                continue
            num += w * float(by_v.get(t, 0.0))
            den += w
        out.append(num / den if den > 0.0 else 0.0)
    return out


def mix_quantile_aligned(
    tau_full: list[int],
    containers: list[ContainerSeries],
    q: float,
    sla_timeout_sec: float,
) -> list[float]:
    """Per-tick completed-sojourn quantile across replicas (timeouts excluded)."""
    from hierarchical_edge_sim.env.latency import DelayPart, mix_offered_quantile

    del sla_timeout_sec
    out: list[float] = []
    for t in tau_full:
        parts: list[DelayPart] = []
        for c in containers:
            by_tau = dict(zip(c.tau, zip(
                c.served,
                c.t_net_sec,
                c.t_svc_sec if c.t_svc_sec else [0.0] * len(c.tau),
                c.t_wait_lo_sec if c.t_wait_lo_sec else [0.0] * len(c.tau),
                c.t_wait_hi_sec if c.t_wait_hi_sec else [0.0] * len(c.tau),
            )))
            row = by_tau.get(t)
            if row is None:
                continue
            served, t_net, t_svc, wait_lo, wait_hi = row
            if float(served) <= 0.0:
                continue
            parts.append(
                DelayPart(
                    weight=float(served),
                    t_net_sec=float(t_net),
                    t_svc_sec=float(t_svc),
                    wait_lo_sec=float(wait_lo),
                    wait_hi_sec=float(wait_hi),
                )
            )
        out.append(mix_offered_quantile(q, parts))
    return out


@dataclass(frozen=True, slots=True)
class MsPhysics:
    cpu_min: float
    cpu_max: float
    ram_min: float
    rho_cpu: float
    rho_ram: float
    theta_target: float = 0.60


def ms_physics_from_meta(meta: dict, app_id: str, ms_id: str) -> MsPhysics:
    theta = 0.60
    scaler = meta.get("autoscaler") or {}
    params = scaler.get("params") or {}
    if params.get("theta_target") is not None:
        theta = float(params["theta_target"])
    for app in meta.get("config", {}).get("apps", []):
        if app.get("id") != app_id:
            continue
        for ms in app.get("microservices", []):
            if ms.get("id") != ms_id:
                continue
            return MsPhysics(
                cpu_min=float(ms["cpu_min_cores"]),
                cpu_max=float(ms["cpu_max_cores"]),
                ram_min=float(ms["ram_min_mb"]),
                rho_cpu=float(ms["cpu_per_request_cores"]),
                rho_ram=float(ms["ram_per_request_mb"]),
                theta_target=theta,
            )
    raise KeyError(f"no microservice spec for app={app_id} ms={ms_id}")


def replica_serve_mu(cpu_alloc: float, ram_alloc: float, spec: MsPhysics) -> float:
    mu_cpu = max(0.0, float(cpu_alloc) - spec.cpu_min) / spec.rho_cpu
    mu_ram = max(0.0, float(ram_alloc) - spec.ram_min) / spec.rho_ram
    return min(mu_cpu, mu_ram)


def serve_mu_series(
    tau_full: list[int],
    containers: list[ContainerSeries],
    spec: MsPhysics,
) -> list[float]:
    parts: list[list[float]] = []
    for container in containers:
        mu = [
            replica_serve_mu(cpu, ram, spec)
            for cpu, ram in zip(container.cpu_capacity, container.ram_capacity)
        ]
        parts.append(series_on_tau(tau_full, container.tau, mu))
    if not parts:
        return [0.0] * len(tau_full)
    return sum_series(parts)


def packed_cpu_cores(incoming: float, spec: MsPhysics, *, theta: float = 1.0) -> float:
    """Least packed CPU that can serve ``incoming`` at utilization ``theta``.

    n = ceil(need_μ / μ_max) replicas at cpu_max; floors buy no throughput.
    """
    need_mu = float(incoming) / float(theta) if theta > 0.0 else 0.0
    mu_max = max(0.0, spec.cpu_max - spec.cpu_min) / spec.rho_cpu
    if need_mu <= 0.0:
        return spec.cpu_min
    n = max(1, int(ceil(need_mu / mu_max))) if mu_max > 0.0 else 1
    return n * spec.cpu_min + need_mu * spec.rho_cpu


def group_containers_by_app(containers: list[ContainerSeries]) -> dict[str, list[ContainerSeries]]:
    grouped: dict[str, list[ContainerSeries]] = defaultdict(list)
    for container in containers:
        grouped[container.app_id].append(container)
    return dict(sorted(grouped.items(), key=lambda item: item[0]))


def group_containers_by_microservice(
    containers: list[ContainerSeries],
) -> dict[str, list[ContainerSeries]]:
    grouped: dict[str, list[ContainerSeries]] = defaultdict(list)
    for container in containers:
        grouped[container.microservice_id].append(container)
    return dict(sorted(grouped.items(), key=lambda item: item[0]))


def server_to_cluster(meta: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for cluster in meta.get("config", {}).get("clusters", []):
        for server in cluster.get("servers", []):
            mapping[server["id"]] = cluster["id"]
    return mapping


def app_owner_cluster_id(meta: dict, app_id: str) -> str:
    """Match world stamp: first container id (sorted) of the app → that server's cluster."""
    placed: list[dict] = []
    for app in meta.get("config", {}).get("apps", []):
        if app.get("id") != app_id:
            continue
        for ms in app.get("microservices", []):
            placed.extend(ms.get("containers") or [])
    if not placed:
        raise KeyError(f"no initial containers for app '{app_id}'")
    placed.sort(key=lambda row: row["id"])
    server_id = placed[0]["server_id"]
    mapping = server_to_cluster(meta)
    if server_id not in mapping:
        raise KeyError(f"server '{server_id}' not in run_meta clusters")
    return mapping[server_id]


def cluster_to_vicinity(meta: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for vicinity in meta.get("config", {}).get("vicinities") or []:
        for member in vicinity.get("members") or []:
            mapping[member] = vicinity["id"]
    return mapping


def classify_site(cluster_id: str, owner_cluster_id: str, vmap: dict[str, str]) -> str:
    if cluster_id == owner_cluster_id:
        return "home"
    if not vmap:
        return "remote"
    if vmap.get(cluster_id) and vmap.get(cluster_id) == vmap.get(owner_cluster_id):
        return "vicinity"
    return "outside"


def replica_counts_by_site(
    tau_full: list[int],
    containers: list[ContainerSeries],
    *,
    owner_cluster_id: str,
    vmap: dict[str, str],
) -> dict[str, list[float]]:
    sites = ("home", "vicinity", "outside", "remote")
    counts = {site: [0.0] * len(tau_full) for site in sites}
    tau_index = {t: i for i, t in enumerate(tau_full)}
    for container in containers:
        site = classify_site(container.cluster_id, owner_cluster_id, vmap)
        for t in container.tau:
            idx = tau_index.get(t)
            if idx is not None:
                counts[site][idx] += 1.0
    if vmap:
        counts.pop("remote")
    else:
        counts.pop("vicinity")
        counts.pop("outside")
    return counts


ACTION_FAMILY: dict[str, str] = {
    "vertical_up": "vertical up",
    "vertical_down": "vertical down",
    "horizontal_spawn": "horizontal spawn",
    "horizontal_terminate": "horizontal terminate",
    "vicinity_spawn": "vicinity",
    "vicinity_up": "vicinity up",
    "vicinity_terminate": "vicinity terminate",
    "vicinity_down": "vicinity down",
    "cascade_spawn": "cascade",
    "cascade_terminate": "cascade",
    "need_horizontal": "escalate",
    "need_vicinity_help": "escalate",
    "unmet_demand": "unmet",
}


def action_markers(actions: list[ActionRow], *, ms_id: str | None = None) -> dict[str, list[int]]:
    """Successful mutations and log-only escalations, grouped for plot legends."""
    by_family: dict[str, list[int]] = {}
    for row in actions:
        if ms_id is not None and row.ms_id and row.ms_id != ms_id:
            continue
        if row.result_code not in {"OK", "LOGGED"}:
            continue
        family = ACTION_FAMILY.get(row.reason) or ACTION_FAMILY.get(row.action_type)
        if family is None:
            continue
        by_family.setdefault(family, [])
        if row.tau not in by_family[family]:
            by_family[family].append(row.tau)
    for family in by_family:
        by_family[family].sort()
    return by_family
