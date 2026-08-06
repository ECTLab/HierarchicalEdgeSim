"""Minimal root orchestrator — topology façade for vicinities / leaders."""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Vicinity


@dataclass(slots=True)
class RootOrchestrator:
    """Owns static vicinity membership and leaders.

    Part A: query-only. No BEG/admission policy and not invoked by the tick loop.
    """

    vicinities: dict[str, Vicinity] = field(default_factory=dict)
    _cluster_to_vicinity: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_vicinities(cls, vicinities: list[Vicinity]) -> "RootOrchestrator":
        root = cls()
        for vicinity in vicinities:
            root.vicinities[vicinity.id] = vicinity
            for cluster_id in vicinity.member_cluster_ids:
                root._cluster_to_vicinity[cluster_id] = vicinity.id
        return root

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

    def beg_admit(self, *args, **kwargs):
        """Reserved for Part B global escalation."""
        raise NotImplementedError("beg_admit is not implemented in Part A")
