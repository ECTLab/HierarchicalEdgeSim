"""Runtime domain models for the Part A environment."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ContainerTickRecord:
    tau: int
    lambda_in: float
    lambda_served: float
    lambda_dropped: float
    cpu_usage_cores: float
    ram_usage_mb: float
    cpu_alloc_cores: float
    ram_alloc_mb: float
    q_cpu: float
    q_ram: float


@dataclass(slots=True)
class Container:
    id: str
    app_id: str
    server_id: str
    microservice_id: str
    cpu_alloc_cores: float
    ram_alloc_mb: float
    # Snapshot of alloc at world build (survives later resize for meta/logs).
    initial_cpu_alloc_cores: float | None = None
    initial_ram_alloc_mb: float | None = None
    history: list[ContainerTickRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.initial_cpu_alloc_cores is None:
            self.initial_cpu_alloc_cores = self.cpu_alloc_cores
        if self.initial_ram_alloc_mb is None:
            self.initial_ram_alloc_mb = self.ram_alloc_mb

    def append_history(self, record: ContainerTickRecord) -> None:
        """Append a single tick record to in-memory history."""
        self.history.append(record)

    def history_at(self, tau: int) -> ContainerTickRecord:
        """Get history record for a specific 1-based tick index."""
        for record in self.history:
            if record.tau == tau:
                return record
        raise KeyError(f"no history record found for tau={tau}")


@dataclass(slots=True)
class Microservice:
    id: str
    app_id: str
    container_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Server:
    id: str
    cluster_id: str
    cpu_cap_cores: float
    ram_cap_mb: float
    container_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Cluster:
    id: str
    server_ids: list[str] = field(default_factory=list)
    # Derived mirrors from RootOrchestrator (None when hierarchy is not configured).
    vicinity_id: str | None = None
    is_vicinity_leader: bool = False


@dataclass(slots=True)
class Vicinity:
    id: str
    member_cluster_ids: list[str]
    leader_cluster_id: str


@dataclass(slots=True)
class App:
    id: str
    microservice_ids: list[str] = field(default_factory=list)
