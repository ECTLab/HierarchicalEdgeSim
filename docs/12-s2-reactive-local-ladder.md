# S2 — Reactive local ladder (BEV → BEH)

**Status:** done  
**Branch:** `ladder-based-implementation`  
**Roadmap:** [10-proposed-implementation-roadmap.md](./10-proposed-implementation-roadmap.md) §3 S2  
**Depends on:** [11-s1-horizontal-mutation-apis.md](./11-s1-horizontal-mutation-apis.md)

**Algorithm 4 mapping:** [25-allocate-resources.md](./25-allocate-resources.md)

S2 adds a **policy** that uses S1 mutations. `reactive_vertical` stays as a BEV-only baseline. The new scaler is `reactive_local`.

Shared `autoscaler.params` (streaks, θ, α, δ, weights): [08-reactive-local-params.md](./08-reactive-local-params.md).

---

## Behavior

Every decision tick, `cluster_manager_cycle` groups microservices by owner cluster, then per microservice:

1. Same reactive signals as vertical (drop streak → up, slack streak → down).
2. **Up — AllocateResources local tiers**
   - If the up-streak is **not** yet `sustained_up_streak`: **BEV** packs residual onto existing replicas (`common.distribute.distribute_up`).
   - Leftover residual (or the full residual if **sustained**, skipping BEV) goes to **BEH**:
     - Prefer servers in the home cluster that already host the MS
     - Then other servers in that cluster by free CPU
     - Spawn above MS minima: pack leftover headroom so the new replica has μ>0 (floors buy no throughput). Skip a server that can only fit the floor.
   - If residual remains → log-only `NeedVicinityHelpAction` (no vicinity protocol yet; S4).
3. **Down**
   - BEV shrink toward minima, then **terminate coldest extra replicas** (never the last).
   - Down never emits vicinity/global help.

**Sustained lock:** `sustained_up_streak` defaults to **6** vs `x_up_streak` **3**, so the first UP still tries vertical packing. Set `sustained_up_streak <= x_up_streak` to skip BEV on the first UP (tests do this).

**Home cluster:** `env.get_app_owner_cluster_id(ms_id)` (S3 stamp). BEH only places on that cluster’s servers. Leftover after BEH is queued for S4 vicinity help when `World.root` exists (YAML vicinities or Algorithm 1); otherwise it stays a log-only `NeedVicinityHelpAction`.

---

## What landed

| Piece | Role |
|---|---|
| `NeedVicinityHelpAction` | Log-only escalation; `apply_actions` writes `need_vicinity_help` / `LOGGED` |
| `autoscaler/common/distribute.py` | Shared BEV packing (vertical re-exports it) |
| `autoscaler/reactive_local/` | Policy + in-cluster BEH |
| `configs/08-demo_60_reactive_local.yaml` | One replica + empty sibling worker |

Apply order is now: terminate → need_horizontal → need_vicinity_help → resize → spawn.

---

## Tests

`tests/test_reactive_local.py`:

- MS CPU/RAM max but server still has room → spawn on the **same** worker
- Home worker full, sibling free → spawn on the **sibling**
- Cluster full → `need_vicinity_help` logged, no crash
- Sustained surge → spawn **without** resize
- Non-sustained with vertical room → BEV resize only
- Two replicas at minima + slack → terminate one
- YAML `name: reactive_local` loads

How to run:

```bash
python3 -m pytest tests/ -q
python3 -m pytest tests/test_reactive_local.py -v
```

**Result when S2 landed:** 130 passed, 0 failed.

Demo:

```bash
python3 examples/run_with_autoscaler.py configs/08-demo_60_reactive_local.yaml
```

---

## Out of scope (later stages)

Loans, app-owner vs worker-owner RPC, vicinity leader schedule, BEG. `NeedVicinityHelp` is a log line until S4.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-15 | S2 reactive_local BEV→BEH notes |
| v2 | 2026-08-27 | Decision tick is ClusterManagerCycle (per owner cluster) |
