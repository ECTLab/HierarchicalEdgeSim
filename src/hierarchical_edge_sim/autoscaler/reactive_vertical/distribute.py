"""Re-export shared VerticalScaling packing (kept so reactive_vertical.policy imports stay stable)."""

from hierarchical_edge_sim.autoscaler.common.distribute import ReplicaView, distribute_down, distribute_up

__all__ = ["ReplicaView", "distribute_down", "distribute_up"]
