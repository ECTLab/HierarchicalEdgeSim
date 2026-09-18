# S4 — Vicinity help (VicinityLeaderSchedule lite)

**Status:** done  
**Branch:** `ladder-based-implementation`  
**Roadmap:** [10-proposed-implementation-roadmap.md](./10-proposed-implementation-roadmap.md) §3 S4  
**Depends on:** [13-s3-ownership-bookkeeping.md](./13-s3-ownership-bookkeeping.md)

S4 is the first **cross-cluster** rung. Local BEV+BEH still run first. Leftover residual is a help request into one vicinity-wide schedule. That schedule places on **non-home** members and stamps a vicinity loan so the app owner can keep mutating that worker.

---

## Vicinity leader

In the paper, each vicinity has an elected leader. After every member has finished its own BEV/BEH, unmet scale-up demand is sent to that leader as a help request. The leader is the **sole arbitrator** for the vicinity that window: it assigns FCFS sequence numbers, treats all member workers as one pool, and emits one placement plan. Two clusters cannot race for the same neighbor; there is no extra tie-break. Members that are not the leader only submit; they do not place on each other directly. Unresolved residual after the round falls through to BEG.

That is the role S4 implements, with sim-shaped mechanics:

| Paper | This simulator |
|---|---|
| Distributed CMs; non-leaders RPC to the leader | One in-process `reactive_local` tick; no CM threads |
| Leader process runs `VicinityLeaderSchedule` | `schedule_vicinity_help` **is** that round |
| Sequence numbers assigned on receipt at the leader | `seq` from FCFS \((t_{det}, ms\_id)\) with \(t_{det}=\tau\) among leftovers this tick |
| Election publishes the leader id | YAML `topology.vicinities[].leader`, **or** Algorithm 1 election, plus `env.is_leader` / `Cluster.is_vicinity_leader` |

**Published `leader` is topology metadata**, same as membership (YAML or Algorithm 1). The scaler does **not** branch on `env.is_leader(...)`. With a single shared world there is only one scheduler, so the named leader is not a second actor. The function still matches the paper’s *job*: one FCFS joint round per vicinity, then stop.

Why keep the named leader at all? So later stages (heartbeat timeout → skip vicinity and go to BEG, re-election) have a real leader id to talk about, and so configs already match the three-layer picture (root publishes `{vicinity → members, leader}`).

### What one leader round does

`reactive_local.on_tick_end` first walks every microservice locally (BEV then in-cluster BEH). Each leftover becomes a `HelpRequest` `(ms_id, home_cluster_id, remain_cpu, remain_ram, minima)`. Then, if `World.root` exists:

1. Group requests by `env.vicinity_of(home)`.
2. For each vicinity, sort by `(seq, ms_id)` — **FCFS, one round**.
3. Snapshot free CPU/RAM on all member servers; subtract this tick’s pending resize/spawn/terminate so two requests cannot over-commit the same worker.
4. For each request, spawn **above MS minima** on **non-home** members only (same `packed_spawn_size` as BEH so μ>0 on the next tick). Skip a worker that can only fit the floor. Member order is the published vicinity list (YAML `members:` or Algorithm 1 seed-then-closest); within a cluster, servers by free CPU then id.
5. Each spawn is `reason="vicinity_spawn"`, `loan_tier="vicinity"`, `actor_cluster_id=home`. `apply_actions` grants the loan on the neighbor worker (and drops it if spawn fails). Later reclaim of that replica is `vicinity_terminate` (S6).
6. If residual remains, S5 BEG consumes it (`NeedGlobalHelpAction` if BEG also fails).

Borrowed replicas live in the same `World` the app owner already reads (routing, metrics, later terminate). No mirror/status RPC.

### Lite vs Algorithm VicinityLeaderSchedule

Not in S4 (paper has them; we deferred):

- **Reserve / `safe_j`:** lender withholds capacity for its own predicted near-future load. S4 uses raw free capacity.
- **Distance ranking** inside the vicinity (`d(home, owner(j))` then safe headroom). S4 uses config member order.
- **Multi-replica `k` on one worker** in one inner step. S4 places one minima-sized replica per inner iteration, same as BEH.
- **Leader re-partition / heartbeat.** Bootstrap election is Algorithm 1 (or YAML). Periodic \(T_{\mathit{repart}}\) and heartbeat → BEG are not simulated.

If both `topology.vicinities` and a complete cluster distance are omitted, `World.root` is `None` and leftovers stay S2 log-only `NeedVicinityHelpAction` — there is no leader to run. See [21-vicinity-partition.md](./21-vicinity-partition.md).

---

## Behavior

Every decision tick, after every MS has walked local up (or down):

1. **Up — local first** (unchanged S2): BEV then in-cluster BEH on the app-owner cluster.
2. Leftover `(remain_cpu, remain_ram)` becomes a `HelpRequest` (FCFS `t_det = τ`, then `ms_id`; see [22-cluster-manager-cycle.md](./22-cluster-manager-cycle.md)).
3. If `World.root` is `None` (no YAML vicinities and no complete cluster distance): same as S2 — log-only `NeedVicinityHelpAction`.
4. If a vicinity exists: run the leader round above (`schedule_vicinity_help`).
5. Still leftover after that round → **S5 BEG** (see [15-s5-global-help.md](./15-s5-global-help.md)); if BEG also fails, log-only `NeedGlobalHelpAction`.
6. **Down:** terminate global loans, then vicinity, then local extras (never the last). Optional cascade-home is S6.

---

## What landed

| Piece | Role |
|---|---|
| `SpawnAction.loan_tier` | `"vicinity"` / `"global"`; empty means no grant |
| `Env._owner_spawn` | Unauthorized + valid `loan_tier` → `add_loan` then `spawn`; failed spawn drops the grant |
| `autoscaler/reactive_local/vicinity.py` | `HelpRequest`, `schedule_vicinity_help`, leftover → `NeedVicinityHelpAction` |
| `beh_down` | Rank remote (`cluster_id != owner`) before local |
| `configs/09-demo_60_vicinity_help.yaml` | Packed c1, empty c2, static vicinity |

Scaler name stays `reactive_local` (roadmap: grow this plugin rather than a sibling name).

---

## Tests

`tests/test_vicinity_help.py`:

- Home saturated, neighbor free → spawn on neighbor **above min** + vicinity loan
- Neighbor that can only fit the floor → no spawn (would be μ=0)
- Two MS, one packed neighbor slot → FCFS first `ms_id` wins; second escalates (S5: `need_global_help` when no outside cluster)
- Vicinity also full and no outside cluster → `need_global_help` logged, no loan
- Scale-down prefers the borrowed replica and drops the loan
- Failed foreign spawn with `loan_tier` does not leave a loan
- Scripted `apply_actions` grant path

Existing `test_cluster_full_logs_need_vicinity_help` (no vicinities / `root is None`) still holds.

```bash
python3 -m pytest tests/test_vicinity_help.py tests/test_reactive_local.py tests/test_ownership.py -v
python3 -m pytest tests/ -q
```

Demo:

```bash
python3 examples/run_with_autoscaler.py configs/09-demo_60_vicinity_help.yaml
```

---

## Out of scope (later stages)

Reclaim order global→vicinity→local and cascade-home are **S6** — see [16-s6-scale-down-reclaim.md](./16-s6-scale-down-reclaim.md). Distance ranking and Reserve inside the vicinity.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-15 | S4 vicinity FCFS help, loan grant, borrowed-first down |
| v1.1 | 2026-08-15 | Leader role vs YAML `leader:`; round mechanics; lite vs paper |
