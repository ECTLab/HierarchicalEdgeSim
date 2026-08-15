# S5 — Global escalation (BEG lite)

**Status:** done  
**Branch:** `ladder-based-implementation`  
**Roadmap:** [proposed-implementation-roadmap.md](./proposed-implementation-roadmap.md) §3 S5  
**Depends on:** [s4-vicinity-help.md](./s4-vicinity-help.md)

S5 is the last **scale-up** rung. After the vicinity leader cannot cover residual, the home cluster escalates to the root. The root does **not** pool every worker the way the leader pools a vicinity. It only ranks *other clusters* outside the home vicinity and tries to spawn there with a **global** loan.

---

## Behavior

On an up tick, after local BEV→BEH and the vicinity round:

1. Unresolved `HelpRequest`s go to `schedule_beg` (paper BEG, lite).
2. The root ranks candidates: `C \ ({home} ∪ V_home)`, most free CPU first, then cluster id. That is the S5 stand-in for the paper’s load–distance score `L + γ·d` (no distances in the sim yet).
3. Concurrent BEG in the same window is serialized: requests stay FCFS (`seq`, then `ms_id`); each placement updates the free snapshot before the next.
4. Spawn at MS minima on the chosen cluster’s servers (free CPU, then id). `reason="beg_spawn"`, `loan_tier="global"`, `actor_cluster_id=home`.
5. `apply_actions` grants the global loan (same S4 grant path; failed spawn rolls back).
6. Still leftover → log-only `NeedGlobalHelpAction` (paper `LogUnmetDemand`).

If `World.root` is `None`, BEG does not run; leftovers stay S2 `NeedVicinityHelpAction`.

Home vicinity members are **never** BEG candidates, even if they have more free CPU than an outside cluster. Vicinity already had its chance; global must not steal that pool.

**Down** is unchanged from S4 (any remote before local). Global-before-vicinity reclaim is S6.

---

## What landed

| Piece | Role |
|---|---|
| `RootOrchestrator.rank_beg_candidates` | Topology filter + least-loaded (free CPU) order |
| `autoscaler/reactive_local/beg.py` | `schedule_beg`, leftover → `NeedGlobalHelpAction` |
| `NeedGlobalHelpAction` | Log-only unmet after BEG |
| `place.py` / `help.py` | Shared minima packing + `HelpRequest` |
| `configs/demo_60_global_help.yaml` | Packed v1, empty v2={c3} |

`beg_admit` on the root still raises: packing stays in the scaler so `env/` does not import autoscaler. The root owns **which clusters are legal** and their order.

Lite vs paper BEG: no γ·distance, no retry bound `B` as a separate cap (we walk all legal clusters), no forecast reservation at the lender, no expected-response-time gate.

---

## Tests

`tests/test_global_help.py`:

- Vicinity full, outside cluster free → spawn on that cluster + global loan, not on the neighbor
- `schedule_beg` skips the home vicinity even when the neighbor has more free CPU
- Outside cluster also full → `need_global_help` logged
- `rank_beg_candidates` excludes `V_home` and sorts by free CPU

S4 tests: leftover after a full two-cluster vicinity is now `need_global_help` (no third cluster to borrow). No-vicinity `test_cluster_full_logs_need_vicinity_help` is unchanged.

```bash
python3 -m pytest tests/test_global_help.py tests/test_vicinity_help.py tests/test_reactive_local.py -v
python3 -m pytest tests/ -q
```

Demo:

```bash
python3 examples/run_with_autoscaler.py configs/demo_60_global_help.yaml
```

---

## Out of scope (later stages)

S6 reclaim order and cascade-home are **done** — see [s6-scale-down-reclaim.md](./s6-scale-down-reclaim.md). Paper load–distance score. Proactive residual (S7).

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-15 | S5 BEG lite: outside-vicinity spawn, global loan |
