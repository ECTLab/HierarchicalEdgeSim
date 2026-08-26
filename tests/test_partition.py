"""VicinityPartitionAndLeaderElection: geometry in, covering partition out."""

from __future__ import annotations

import pytest

from hierarchical_edge_sim.env.partition import (
    PartitionParams,
    distance_from_coords,
    lookup_distance,
    parse_partition_params,
    partition_and_elect,
)


def _caps(ids: list[str], cpu: float = 8.0, ram: float = 16384.0) -> tuple[dict[str, float], dict[str, float]]:
    return ({cid: cpu for cid in ids}, {cid: ram for cid in ids})


def test_distance_from_coords_is_symmetric_euclidean():
    coords = {"c1": (0.0, 0.0), "c2": (3.0, 4.0)}
    matrix = distance_from_coords(coords)
    assert lookup_distance(matrix, "c1", "c2") == pytest.approx(5.0)
    assert lookup_distance(matrix, "c2", "c1") == pytest.approx(5.0)
    assert lookup_distance(matrix, "c1", "c1") == 0.0


def test_single_cluster_is_its_own_vicinity():
    vis = partition_and_elect(["c1"], {}, {"c1": 8.0}, {"c1": 1024.0})
    assert len(vis) == 1
    assert vis[0].id == "v1"
    assert vis[0].member_cluster_ids == ["c1"]
    assert vis[0].leader_cluster_id == "c1"


def test_two_clusters_join_one_vicinity_despite_paper_empty_gap_loop():
    """|D|=1 makes the tex gap loop empty; we still take the only neighbor."""
    coords = {"c1": (0.0, 0.0), "c2": (1.0, 0.0)}
    cpu, ram = _caps(["c1", "c2"])
    cpu["c1"] = 16.0
    cpu["c2"] = 4.0
    vis = partition_and_elect(
        ["c1", "c2"],
        distance_from_coords(coords),
        cpu,
        ram,
    )
    assert len(vis) == 1
    assert set(vis[0].member_cluster_ids) == {"c1", "c2"}
    assert vis[0].leader_cluster_id == "c1"  # more cap(c)
    assert vis[0].member_cluster_ids[0] == "c1"  # densest-seed tie → smallest id


def test_two_close_and_one_far_split_by_z_score():
    coords = {
        "c1": (0.0, 0.0),
        "c2": (0.1, 0.0),
        "c3": (10.0, 0.0),
    }
    cpu, ram = _caps(["c1", "c2", "c3"])
    vis = partition_and_elect(
        ["c1", "c2", "c3"],
        distance_from_coords(coords),
        cpu,
        ram,
        PartitionParams(k=1.0, m_max=5),
    )
    by_id = {v.id: set(v.member_cluster_ids) for v in vis}
    # c1/c2 are a tight pair; c3 is an outlier and becomes its own group.
    assert {"c1", "c2"} in by_id.values()
    assert {"c3"} in by_id.values()
    assert len(vis) == 2


def test_five_sites_two_pairs_and_isolate_with_k_half():
    coords = {
        "west-a": (0.0, 0.0),
        "west-b": (0.2, 0.0),
        "east-a": (10.0, 0.0),
        "east-b": (10.2, 0.0),
        "isolated": (50.0, 50.0),
    }
    ids = list(coords)
    cpu = {cid: 4.0 for cid in ids}
    ram = {cid: 8192.0 for cid in ids}
    cpu["west-a"] = 16.0
    cpu["east-a"] = 16.0
    vis = partition_and_elect(
        ids,
        distance_from_coords(coords),
        cpu,
        ram,
        PartitionParams(k=0.5, m_max=5),
    )
    groups = {frozenset(v.member_cluster_ids) for v in vis}
    assert groups == {
        frozenset({"west-a", "west-b"}),
        frozenset({"east-a", "east-b"}),
        frozenset({"isolated"}),
    }


def test_m_max_caps_group_size():
    coords = {f"c{i}": (float(i), 0.0) for i in range(1, 6)}
    ids = list(coords)
    cpu, ram = _caps(ids)
    vis = partition_and_elect(
        ids,
        distance_from_coords(coords),
        cpu,
        ram,
        PartitionParams(k=0.0, m_max=2),
    )
    assert all(len(v.member_cluster_ids) <= 2 for v in vis)
    covered = [cid for v in vis for cid in v.member_cluster_ids]
    assert sorted(covered) == sorted(ids)
    assert len(covered) == len(set(covered))


def test_leader_prefers_capacity_over_centrality():
    # Equilateral-ish: c2 sits between c1 and c3, but c1 has far more machines.
    coords = {"c1": (0.0, 0.0), "c2": (1.0, 0.0), "c3": (2.0, 0.0)}
    cpu = {"c1": 32.0, "c2": 4.0, "c3": 4.0}
    ram = {"c1": 32768.0, "c2": 4096.0, "c3": 4096.0}
    vis = partition_and_elect(
        ["c1", "c2", "c3"],
        distance_from_coords(coords),
        cpu,
        ram,
        PartitionParams(k=0.0, m_max=5, alpha=10.0, beta=1.0),
    )
    # k=0 flags everyone closer-than-or-equal-typical; one vicinity of 3.
    assert len(vis) == 1
    assert set(vis[0].member_cluster_ids) == {"c1", "c2", "c3"}
    assert vis[0].leader_cluster_id == "c1"


def test_leader_tie_breaks_by_smallest_cluster_id():
    coords = {"c2": (0.0, 0.0), "c1": (1.0, 0.0)}
    cpu, ram = _caps(["c1", "c2"])
    vis = partition_and_elect(
        ["c2", "c1"],
        distance_from_coords(coords),
        cpu,
        ram,
    )
    assert vis[0].leader_cluster_id == "c1"


def test_partition_is_deterministic():
    coords = {
        "west": (0.0, 0.0),
        "east": (0.2, 0.0),
        "far": (20.0, 0.0),
    }
    cpu, ram = _caps(["west", "east", "far"])
    d = distance_from_coords(coords)
    a = partition_and_elect(["far", "west", "east"], d, cpu, ram)
    b = partition_and_elect(["east", "far", "west"], d, cpu, ram)
    assert [(v.id, v.member_cluster_ids, v.leader_cluster_id) for v in a] == [
        (v.id, v.member_cluster_ids, v.leader_cluster_id) for v in b
    ]


def test_incomplete_matrix_raises():
    with pytest.raises(ValueError, match="incomplete distance matrix"):
        partition_and_elect(
            ["c1", "c2"],
            {},
            {"c1": 1.0, "c2": 1.0},
            {"c1": 1.0, "c2": 1.0},
        )


def test_parse_partition_params_rejects_unknown_and_bool_m_max():
    with pytest.raises(ValueError, match="unknown topology.partition keys"):
        parse_partition_params({"k": 1.0, "gamma": 2})
    with pytest.raises(ValueError, match="m_max must be an int"):
        parse_partition_params({"m_max": True})
    params = parse_partition_params({"k": 0.5, "m_max": 3})
    assert params.k == pytest.approx(0.5)
    assert params.m_max == 3
