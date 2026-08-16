"""Aggregation helpers for multi-container / multi-app analysis."""

from __future__ import annotations

from collections import defaultdict

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
    return "global"


def replica_counts_by_site(
    tau_full: list[int],
    containers: list[ContainerSeries],
    *,
    owner_cluster_id: str,
    vmap: dict[str, str],
) -> dict[str, list[float]]:
    sites = ("home", "vicinity", "global", "remote")
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
        counts.pop("global")
    return counts


ACTION_FAMILY: dict[str, str] = {
    "bev_up": "BEV up",
    "bev_down": "BEV down",
    "beh_spawn": "BEH spawn",
    "beh_terminate": "BEH terminate",
    "vicinity_spawn": "vicinity",
    "beg_spawn": "BEG",
    "cascade_spawn": "cascade",
    "cascade_terminate": "cascade",
    "need_horizontal": "escalate",
    "need_vicinity_help": "escalate",
    "need_global_help": "escalate",
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
