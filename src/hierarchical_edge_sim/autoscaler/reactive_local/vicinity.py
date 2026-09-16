"""VicinityRound (paper Alg. leader): reports, leader schedule, ApplyVicinityPlan.

One-process mapping: every member of V produces a report (empty offers
included). Only ℓ(V) runs ScheduleReleases then SchedulePlacements into a
plan Π. ApplyVicinityPlan turns Π into env actions. Placements grow existing
hosts (local then nearer loans) then packed-spawn over all of N_V, including
home after Phase 1 frees room. Spawn stays packed, not minima; safe_j is later.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hierarchical_edge_sim.env.api import (
    Env,
    NeedVicinityHelpAction,
    ResizeAction,
    SpawnAction,
    TerminateAction,
    UnmetDemandAction,
)

from .help import HelpRequest, ReleaseIntent, help_fcfs_key
from .place import schedule_placements, snapshot_free, subtract_pending
from .release import schedule_releases

__all__ = [
    "HelpRequest",
    "PlanEntry",
    "VicinityPlan",
    "VicinityReport",
    "apply_vicinity_plan",
    "collect_reports",
    "leftover_to_help_action",
    "leftover_to_unmet_demand",
    "schedule_vicinity_help",
    "schedule_vicinity_plan",
    "vicinity_round",
]


@dataclass(slots=True)
class VicinityReport:
    """One member's report for window t. Empty Q/R is an offer, not a no-op."""

    cluster_id: str
    tau: int
    requests: list[HelpRequest] = field(default_factory=list)
    releases: list[ReleaseIntent] = field(default_factory=list)


@dataclass(slots=True)
class PlanEntry:
    """One Π tuple: (act, j, owner(j), c', m, params)."""

    act: str
    server_id: str
    owner_cluster_id: str
    for_cluster_id: str
    ms_id: str
    tau: int
    container_id: str = ""
    cpu_alloc_cores: float | None = None
    ram_alloc_mb: float | None = None
    reason: str = ""
    loan_tier: str = ""


@dataclass(slots=True)
class VicinityPlan:
    """Π for one vicinity in window t, plus leftover ρ for LogUnmetDemand."""

    vicinity_id: str
    leader_cluster_id: str
    tau: int
    entries: list[PlanEntry] = field(default_factory=list)
    unmet: list[HelpRequest] = field(default_factory=list)


def collect_reports(
    env: Env,
    requests: list[HelpRequest],
    releases: list[ReleaseIntent] | None,
    tau: int,
) -> list[VicinityReport]:
    """Build one report per leftover home, then fill empty offers for every member of V."""
    by_id: dict[str, VicinityReport] = {}

    def _report(cluster_id: str) -> VicinityReport:
        found = by_id.get(cluster_id)
        if found is None:
            found = VicinityReport(cluster_id=cluster_id, tau=tau)
            by_id[cluster_id] = found
        return found

    for req in requests:
        _report(req.home_cluster_id).requests.append(req)
    for intent in releases or []:
        _report(intent.home_cluster_id).releases.append(intent)
    if env.root is not None:
        for vid in env.list_vicinities():
            for cluster_id in env.list_vicinity_members(vid):
                _report(cluster_id)
    return [by_id[cid] for cid in sorted(by_id)]


def schedule_vicinity_help(
    env: Env,
    requests: list[HelpRequest],
    *,
    pending: list,
    tau: int,
    releases: list | None = None,
) -> tuple[list, list[HelpRequest]]:
    """VicinityRound entry: collect reports, barrier, leader schedule, apply Π."""
    reports = collect_reports(env, requests, list(releases or []), tau)
    return vicinity_round(env, reports, pending=pending, tau=tau)


def vicinity_round(
    env: Env,
    reports: list[VicinityReport],
    *,
    pending: list,
    tau: int,
) -> tuple[list, list[HelpRequest]]:
    """Invoked after every member has a report. Only ℓ(V) computes Π."""
    if env.root is None:
        leftover = [req for report in reports for req in report.requests]
        return ([], leftover)

    by_vicinity: dict[str, list[VicinityReport]] = {}
    for report in reports:
        vid = env.vicinity_of(report.cluster_id)
        by_vicinity.setdefault(vid, []).append(report)

    actions: list = []
    unmet: list[HelpRequest] = []
    for vid in sorted(by_vicinity):
        members = env.list_vicinity_members(vid)
        member_reports = list(by_vicinity[vid])
        reported = {r.cluster_id for r in member_reports}
        for cluster_id in members:
            if cluster_id not in reported:
                member_reports.append(VicinityReport(cluster_id=cluster_id, tau=tau))
                reported.add(cluster_id)
        if reported != set(members):
            raise RuntimeError(
                f"VicinityRound barrier incomplete for {vid}: "
                f"reported {sorted(reported)} members {list(members)}"
            )
        plan: VicinityPlan | None = None
        for cluster_id in members:
            if not env.is_leader(cluster_id):
                continue
            plan = schedule_vicinity_plan(
                env,
                vid,
                member_reports,
                pending=pending + actions,
                tau=tau,
            )
        if plan is None:
            raise RuntimeError(f"vicinity {vid} has no leader in members {list(members)}")
        applied, leftover = apply_vicinity_plan(env, plan)
        actions.extend(applied)
        unmet.extend(leftover)
    return (actions, unmet)


def schedule_vicinity_plan(
    env: Env,
    vicinity_id: str,
    reports: list[VicinityReport],
    *,
    pending: list,
    tau: int,
) -> VicinityPlan:
    """Leader body of Alg. leader: union reports, releases then placements."""
    leader = env.leader_of(vicinity_id)
    if not env.is_leader(leader):
        raise RuntimeError(f"{leader} is not leader of vicinity {vicinity_id}")
    requests: list[HelpRequest] = []
    releases: list[ReleaseIntent] = []
    for report in sorted(reports, key=lambda item: item.cluster_id):
        requests.extend(report.requests)
        releases.extend(report.releases)
    requests.sort(key=lambda req: (*help_fcfs_key(req), req.seq))
    releases.sort(key=lambda intent: (*help_fcfs_key(intent), intent.seq))

    members = env.list_vicinity_members(vicinity_id)
    rel_actions = schedule_releases(env, releases, pending=pending, tau=tau)
    entries = [plan_entry_from_action(env, action) for action in rel_actions]
    if not requests:
        return VicinityPlan(
            vicinity_id=vicinity_id,
            leader_cluster_id=leader,
            tau=tau,
            entries=entries,
        )

    free_cpu, free_ram = snapshot_free(env, members)
    subtract_pending(env, pending + list(rel_actions), free_cpu, free_ram)
    placed, unmet = schedule_placements(
        env,
        requests,
        members=members,
        pending=pending + list(rel_actions),
        free_cpu=free_cpu,
        free_ram=free_ram,
        tau=tau,
    )
    entries.extend(plan_entry_from_action(env, action) for action in placed)
    return VicinityPlan(
        vicinity_id=vicinity_id,
        leader_cluster_id=leader,
        tau=tau,
        entries=entries,
        unmet=unmet,
    )


def apply_vicinity_plan(env: Env, plan: VicinityPlan) -> tuple[list, list[HelpRequest]]:
    """Alg. applyplan. One-process: every entry is applied (broadcast is the plan)."""
    _ = env
    actions: list = []
    for entry in plan.entries:
        if entry.act == "terminate":
            actions.append(
                TerminateAction(
                    type="terminate",
                    ms_id=entry.ms_id,
                    container_id=entry.container_id,
                    reason=entry.reason or "vicinity_terminate",
                    tau=entry.tau,
                    actor_cluster_id=entry.for_cluster_id,
                )
            )
        elif entry.act in {"shrink", "grow"}:
            actions.append(
                ResizeAction(
                    type="resize",
                    ms_id=entry.ms_id,
                    container_id=entry.container_id,
                    cpu_alloc_cores=entry.cpu_alloc_cores,
                    ram_alloc_mb=entry.ram_alloc_mb,
                    reason=entry.reason
                    or ("vicinity_down" if entry.act == "shrink" else "vicinity_up"),
                    tau=entry.tau,
                    actor_cluster_id=entry.for_cluster_id,
                )
            )
        elif entry.act == "spawn":
            actions.append(
                SpawnAction(
                    type="spawn",
                    ms_id=entry.ms_id,
                    server_id=entry.server_id,
                    cpu_alloc_cores=entry.cpu_alloc_cores,
                    ram_alloc_mb=entry.ram_alloc_mb,
                    reason=entry.reason or "vicinity_spawn",
                    tau=entry.tau,
                    actor_cluster_id=entry.for_cluster_id,
                    loan_tier=entry.loan_tier,
                )
            )
        else:
            raise ValueError(f"unknown plan act {entry.act!r}")
    return actions, list(plan.unmet)


def plan_entry_from_action(env: Env, action: object) -> PlanEntry:
    kind = getattr(action, "type", "")
    tau = int(getattr(action, "tau", 0) or 0)
    ms_id = str(getattr(action, "ms_id", ""))
    for_cluster = str(getattr(action, "actor_cluster_id", "") or "")
    if not for_cluster and ms_id:
        for_cluster = env.get_app_owner_cluster_id(ms_id)
    if kind == "terminate":
        container = env.get_container(str(action.container_id))
        server = env.get_server(container.server_id)
        return PlanEntry(
            act="terminate",
            server_id=container.server_id,
            owner_cluster_id=server.cluster_id,
            for_cluster_id=for_cluster,
            ms_id=ms_id,
            tau=tau,
            container_id=container.id,
            reason=str(getattr(action, "reason", "") or "vicinity_terminate"),
        )
    if kind == "resize":
        container = env.get_container(str(action.container_id))
        server = env.get_server(container.server_id)
        reason = str(getattr(action, "reason", "") or "")
        act = "shrink" if reason == "vicinity_down" else "grow"
        return PlanEntry(
            act=act,
            server_id=container.server_id,
            owner_cluster_id=server.cluster_id,
            for_cluster_id=for_cluster,
            ms_id=ms_id,
            tau=tau,
            container_id=container.id,
            cpu_alloc_cores=getattr(action, "cpu_alloc_cores", None),
            ram_alloc_mb=getattr(action, "ram_alloc_mb", None),
            reason=reason or ("vicinity_down" if act == "shrink" else "vicinity_up"),
        )
    if kind == "spawn":
        server_id = str(action.server_id)
        server = env.get_server(server_id)
        return PlanEntry(
            act="spawn",
            server_id=server_id,
            owner_cluster_id=server.cluster_id,
            for_cluster_id=for_cluster,
            ms_id=ms_id,
            tau=tau,
            cpu_alloc_cores=getattr(action, "cpu_alloc_cores", None),
            ram_alloc_mb=getattr(action, "ram_alloc_mb", None),
            reason=str(getattr(action, "reason", "") or "vicinity_spawn"),
            loan_tier=str(getattr(action, "loan_tier", "") or ""),
        )
    raise ValueError(f"cannot put action type {kind!r} on a vicinity plan")


def leftover_to_help_action(req: HelpRequest) -> NeedVicinityHelpAction:
    """Leftover when there is no root, so VicinityRound cannot run."""
    return NeedVicinityHelpAction(
        type="need_vicinity_help",
        ms_id=req.ms_id,
        reason="need_vicinity_help",
        tau=req.tau,
        residual_cpu_cores=req.remain_cpu,
        residual_ram_mb=req.remain_ram,
        cluster_id=req.home_cluster_id,
    )


def leftover_to_unmet_demand(req: HelpRequest) -> UnmetDemandAction:
    """Paper LogUnmetDemand: leftover after the vicinity round."""
    return UnmetDemandAction(
        type="unmet_demand",
        ms_id=req.ms_id,
        reason="unmet_demand",
        tau=req.tau,
        residual_cpu_cores=req.remain_cpu,
        residual_ram_mb=req.remain_ram,
        cluster_id=req.home_cluster_id,
    )
