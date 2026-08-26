"""VicinityPartitionAndLeaderElection (paper Algorithm vicinity).

Groups clusters by inter-cluster distance and elects one leader per group.
Does not delay user requests and does not send RPCs: it only publishes a
partition into RootOrchestrator.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from .config import EPS
from .models import Vicinity

# Paper: α ≫ β so capacity dominates centrality.
DEFAULT_K = 1.0
DEFAULT_M_MAX = 5
DEFAULT_ALPHA = 10.0
DEFAULT_BETA = 1.0
DEFAULT_W_CPU = 1.0
# 1 GiB counts like 1 core, so RAM MB does not drown CPU in cap(c).
DEFAULT_W_RAM = 1.0 / 1024.0


@dataclass(frozen=True, slots=True)
class PartitionParams:
    k: float = DEFAULT_K
    m_max: int = DEFAULT_M_MAX
    alpha: float = DEFAULT_ALPHA
    beta: float = DEFAULT_BETA
    w_cpu: float = DEFAULT_W_CPU
    w_ram: float = DEFAULT_W_RAM


def pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def lookup_distance(distances: dict[tuple[str, str], float], a: str, b: str) -> float:
    """d(a,b); diagonal is 0. Matrix is stored with unordered pair keys."""
    if a == b:
        return 0.0
    try:
        return distances[pair_key(a, b)]
    except KeyError as exc:
        raise KeyError(f"no distance for pair '{a}'-'{b}'") from exc


def distance_from_coords(coords: dict[str, tuple[float, float]]) -> dict[tuple[str, str], float]:
    """Euclidean d(c,c') from 2-D cluster coordinates."""
    ids = list(coords)
    matrix: dict[tuple[str, str], float] = {}
    for i, a in enumerate(ids):
        ax, ay = coords[a]
        for b in ids[i + 1 :]:
            bx, by = coords[b]
            matrix[pair_key(a, b)] = math.hypot(ax - bx, ay - by)
    return matrix


def latency_edges_to_matrix(
    edges: list[tuple[str, str, float]],
) -> dict[tuple[str, str], float]:
    """Build a symmetric matrix from (from, to, ms) edges. Last write wins on duplicates."""
    matrix: dict[tuple[str, str], float] = {}
    for a, b, ms in edges:
        if a == b:
            continue
        matrix[pair_key(a, b)] = float(ms)
    return matrix


def matrix_is_complete(cluster_ids: list[str], matrix: dict[tuple[str, str], float]) -> bool:
    ids = list(cluster_ids)
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            if pair_key(a, b) not in matrix:
                return False
    return True


def resolve_distance_matrix(
    cluster_ids: list[str],
    coords: dict[str, tuple[float, float]],
    latency: dict[tuple[str, str], float],
) -> dict[tuple[str, str], float] | None:
    """Prefer a complete latency matrix; else Euclidean coords. None if neither is complete."""
    if latency and matrix_is_complete(cluster_ids, latency):
        return dict(latency)
    if len(cluster_ids) <= 1:
        if coords and set(coords) == set(cluster_ids):
            return {}
        return None
    if coords and set(coords) == set(cluster_ids):
        return distance_from_coords(coords)
    return None


def parse_partition_params(raw: dict | None) -> PartitionParams:
    """Build PartitionParams from an optional YAML mapping (unknown keys rejected)."""
    if not raw:
        return PartitionParams()
    allowed = {"k", "m_max", "alpha", "beta", "w_cpu", "w_ram"}
    extra = set(raw) - allowed
    if extra:
        raise ValueError(f"unknown topology.partition keys: {sorted(extra)}")
    kwargs: dict = {}
    if "k" in raw:
        kwargs["k"] = _partition_float("k", raw["k"])
    if "m_max" in raw:
        kwargs["m_max"] = _partition_int("m_max", raw["m_max"])
    if "alpha" in raw:
        kwargs["alpha"] = _partition_float("alpha", raw["alpha"])
    if "beta" in raw:
        kwargs["beta"] = _partition_float("beta", raw["beta"])
    if "w_cpu" in raw:
        kwargs["w_cpu"] = _partition_float("w_cpu", raw["w_cpu"])
    if "w_ram" in raw:
        kwargs["w_ram"] = _partition_float("w_ram", raw["w_ram"])
    params = PartitionParams(**kwargs)
    if params.k < 0:
        raise ValueError("topology.partition.k must be >= 0")
    if params.m_max < 1:
        raise ValueError("topology.partition.m_max must be >= 1")
    if params.alpha < 0 or params.beta < 0:
        raise ValueError("topology.partition alpha/beta must be >= 0")
    return params


def _partition_float(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"topology.partition.{name} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"topology.partition.{name} must be finite")
    return result


def _partition_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"topology.partition.{name} must be an int")
    return value


def cluster_capacity(
    cpu_cap: dict[str, float],
    ram_cap: dict[str, float],
    params: PartitionParams,
) -> dict[str, float]:
    """Paper cap(c) = w_cpu · cpuCap(c) + w_ram · ramCap(c)."""
    return {
        cid: params.w_cpu * cpu_cap[cid] + params.w_ram * ram_cap[cid] for cid in cpu_cap
    }


def partition_and_elect(
    cluster_ids: list[str],
    distances: dict[tuple[str, str], float],
    cpu_cap: dict[str, float],
    ram_cap: dict[str, float],
    params: PartitionParams | None = None,
) -> list[Vicinity]:
    """Return a covering, disjoint partition with one leader per vicinity.

    Formation order is deterministic. Vicinity ids are ``v1``, ``v2``, …
    """
    params = params or PartitionParams()
    remaining = set(cluster_ids)
    if not remaining:
        return []
    _require_complete_matrix(remaining, distances)
    cap = cluster_capacity(cpu_cap, ram_cap, params)

    groups: list[Vicinity] = []
    while remaining:
        seed = _densest_seed(remaining, distances)
        members = _grow_vicinity(seed, remaining, distances, params)
        leader = _elect_leader(members, distances, cap, params)
        ordered = _order_members(seed, members, distances)
        vid = f"v{len(groups) + 1}"
        groups.append(
            Vicinity(id=vid, member_cluster_ids=ordered, leader_cluster_id=leader)
        )
        remaining -= members
    return groups


def _require_complete_matrix(ids: set[str], distances: dict[tuple[str, str], float]) -> None:
    missing: list[str] = []
    ordered = sorted(ids)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1 :]:
            if pair_key(a, b) not in distances:
                missing.append(f"{a}-{b}")
    if missing:
        raise ValueError(f"incomplete distance matrix, missing pairs: {', '.join(missing)}")


def _densest_seed(remaining: set[str], distances: dict[tuple[str, str], float]) -> str:
    """Cluster with the most others at or inside the median pairwise distance of U."""
    median = _pairwise_median(remaining, distances)

    def key(cid: str) -> tuple[int, str]:
        count = sum(
            1
            for other in remaining
            if other != cid and lookup_distance(distances, cid, other) <= median + EPS
        )
        return (-count, cid)

    return min(remaining, key=key)


def _pairwise_median(remaining: set[str], distances: dict[tuple[str, str], float]) -> float:
    ids = sorted(remaining)
    pairs: list[float] = []
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            pairs.append(lookup_distance(distances, a, b))
    if not pairs:
        return 0.0
    return float(statistics.median(pairs))


def _grow_vicinity(
    seed: str,
    remaining: set[str],
    distances: dict[tuple[str, str], float],
    params: PartitionParams,
) -> set[str]:
    others = sorted(
        remaining - {seed},
        key=lambda cid: (lookup_distance(distances, seed, cid), cid),
    )
    if not others:
        return {seed}

    ranked = [(lookup_distance(distances, seed, cid), cid) for cid in others]
    d_only = [row[0] for row in ranked]
    cand_ids = _candidate_ids(d_only, [row[1] for row in ranked], params)
    take = min(len(cand_ids), max(0, params.m_max - 1))
    return {seed, *cand_ids[:take]}


def _candidate_ids(
    d_sorted: list[float],
    ids_sorted: list[str],
    params: PartitionParams,
) -> list[str]:
    """Z-score cut when σ>0, else largest-gap; paper-silent edges documented in tests."""
    n = len(d_sorted)
    if n == 0:
        return []
    if n == 1:
        # Paper gap loop is empty when |D|=1 (σ is forced 0). The only neighbor
        # is the candidate; otherwise two clusters could never share a vicinity.
        return list(ids_sorted)

    mu = statistics.fmean(d_sorted)
    sigma = statistics.pstdev(d_sorted)
    if sigma > EPS:
        return [
            cid
            for dist, cid in zip(d_sorted, ids_sorted, strict=True)
            if (dist - mu) / sigma <= -params.k
        ]
    return _gap_candidates(d_sorted, ids_sorted, params)


def _gap_candidates(
    d_sorted: list[float],
    ids_sorted: list[str],
    params: PartitionParams,
) -> list[str]:
    n = len(d_sorted)
    window = min(n, params.m_max)
    if window < 2:
        return ids_sorted[:1]
    gaps = [d_sorted[i + 1] - d_sorted[i] for i in range(window - 1)]
    max_gap = max(gaps)
    if max_gap <= EPS:
        return ids_sorted[: min(n, params.m_max - 1)]
    cut = gaps.index(max_gap) + 1
    return ids_sorted[:cut]


def _elect_leader(
    members: set[str],
    distances: dict[tuple[str, str], float],
    cap: dict[str, float],
    params: PartitionParams,
) -> str:
    cap_vals = [cap[cid] for cid in members]
    mu = statistics.fmean(cap_vals)
    sigma = statistics.pstdev(cap_vals) if len(members) >= 2 else 0.0

    def rho(cid: str) -> float:
        z = (cap[cid] - mu) / sigma if sigma > EPS else 0.0
        others = members - {cid}
        if not others:
            mean_d = 0.0
        else:
            mean_d = statistics.fmean(lookup_distance(distances, cid, o) for o in others)
        return params.alpha * z - params.beta * mean_d

    return min(members, key=lambda cid: (-rho(cid), cid))


def _order_members(
    seed: str,
    members: set[str],
    distances: dict[tuple[str, str], float],
) -> list[str]:
    rest = sorted(
        members - {seed},
        key=lambda cid: (lookup_distance(distances, seed, cid), cid),
    )
    return [seed, *rest]
