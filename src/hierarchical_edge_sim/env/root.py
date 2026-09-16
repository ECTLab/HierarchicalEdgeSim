"""Root orchestrator — publishes vicinities / leaders and optional cluster distances."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Vicinity
from .partition import lookup_distance


@dataclass(slots=True)
class RootOrchestrator:
    """Owns vicinity membership and leaders.

    ``vicinity_source`` is ``yaml`` (hand groups) or ``algorithm``
    (VicinityPartitionAndLeaderElection). Distances are optional and do not
    delay user requests. Membership is frozen after publish; admission stamps
    live in ``env/admission.py``.
    """

    vicinities: dict[str, Vicinity] = field(default_factory=dict)
    _cluster_to_vicinity: dict[str, str] = field(default_factory=dict)
    vicinity_source: str = "yaml"
    distances: dict[tuple[str, str], float] | None = None

    @classmethod
    def from_vicinities(
        cls,
        vicinities: list[Vicinity],
        *,
        vicinity_source: str = "yaml",
        distances: dict[tuple[str, str], float] | None = None,
    ) -> "RootOrchestrator":
        root = cls(vicinity_source=vicinity_source, distances=distances)
        for vicinity in vicinities:
            root.vicinities[vicinity.id] = vicinity
            for cluster_id in vicinity.member_cluster_ids:
                root._cluster_to_vicinity[cluster_id] = vicinity.id
        return root

    def distance(self, a: str, b: str) -> float:
        if self.distances is None:
            raise RuntimeError("no cluster distance matrix (set coords or topology.latency_ms)")
        return lookup_distance(self.distances, a, b)

    def list_vicinities(self) -> list[str]:
        return sorted(self.vicinities.keys())

    def get_vicinity(self, vicinity_id: str) -> Vicinity:
        return self.vicinities[vicinity_id]

    def vicinity_of(self, cluster_id: str) -> str:
        if cluster_id not in self._cluster_to_vicinity:
            raise KeyError(f"cluster '{cluster_id}' is not assigned to a vicinity")
        return self._cluster_to_vicinity[cluster_id]

    def leader_of(self, vicinity_id: str) -> str:
        return self.vicinities[vicinity_id].leader_cluster_id

    def is_leader(self, cluster_id: str) -> bool:
        vicinity_id = self.vicinity_of(cluster_id)
        return self.leader_of(vicinity_id) == cluster_id

    def list_vicinity_members(self, vicinity_id: str) -> list[str]:
        return list(self.vicinities[vicinity_id].member_cluster_ids)
