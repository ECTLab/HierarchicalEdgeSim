# Proposed Implementation Roadmap

**Branch base:** `7f998f2` (`implementing the basics for auto-scaling and a reactive auto-scaler`)  
**Authority for algorithms:** `proposed_method_complete.tex` (BEV → BEH → VicinityLeaderSchedule → BEG)  
**Style:** same incremental gates as Part A / autoscaler step docs — one stage green before the next

---

## 0. Why this base commit

| Commit | Why not start here |
|---|---|
| `d957147`+ (`proactive-decide-and-apply-plan`, decide/apply) | Starts finishing proactive **before** horizontal / ownership / vicinity help exist. In the paper, proactive only changes residual demand; it still walks the same ladder. |
| `c4f7a49` / `77652af` | Useful LSTM scaffolding, but pulls the project into stage-8 work with spawn/terminate still stubs. |
| **`7f998f2` (chosen)** | Part A env + static root/vicinity shell + **reactive vertical** are in. Next real paper gap is BEH. |

`main` can keep the early proactive experiments; this roadmap deliberately re-orders: **finish the reactive ladder, then attach the predictor**.

---

## 1. Current baseline (what is already true at this tip)

### Done

- Tick engine, traces, capacity-weighted routing, drop-on-overflow, metrics logs
- Multi-cluster topology; static `vicinities` + `RootOrchestrator` query façade
- Live `Env.resize` + `apply_actions`
- Plugin hook: `reactive_vertical` (streaks → vertical redistribute; cooldown)
- `NeedHorizontalAction` emitted/logged when vertical room is exhausted — **no effect**

### Explicitly not done

- Dynamic app admission / CM “deploy task” protocol (placement is YAML-static — acceptable for sim)
- `spawn` / `terminate`
- Horizontal policy (same worker → other workers in cluster)
- Loans, app-owner vs worker-owner RPC, loan registry
- Vicinity leader joint schedule / global BEG
- Proactive PredictAndDecide wired through the full ladder

### Design lock carried forward

| Lock | Choice |
|---|---|
| Env vs policy | Physics + mutation APIs in `env/`; algorithms in `autoscaler/<name>/` |
| Static placement for early stages | YAML places initial replicas; live placement appears with BEH via `spawn` |
| Vicinity v1 | Hand-specified partition + leader (already in config); distance Algorithm later |
| Actions take effect next tick | Unchanged |
| No threads | Unchanged |

---

## 2. Stage map (paper ↔ build order)

```text
Paper ladder:     BEV  →  BEH  →  VicinityLeader  →  BEG
Your old stages:  #3   →  #4–5 →  #6              →  #7   →  #8 proactive

This roadmap:     S0 (done) → S1 → S2 → S3 → S4 → S5 → S6 → S7
```

| Stage | Goal | Paper anchor | Gate |
|---|---|---|---|
| **S0** | Env + reactive vertical | BEV substrate | *already green at branch tip* |
| **S1** | Horizontal mutation APIs | BEH prerequisites | `spawn`/`terminate` real; packing tests |
| **S2** | Reactive local ladder (V↔H, same cluster) | BEV+BEH, `sustained` | No unmet local residual without trying BEH |
| **S3** | Ownership + loan registry (still local-only borrowers unused) | Alg. owner, notation | Single writer per worker; intent API sketched |
| **S4** | Vicinity help (static groups) | VicinityLeaderSchedule (simplified) | Saturated cluster gets neighbor capacity via leader |
| **S5** | Global help | BEG | Vicinity-full → root places outside vicinity |
| **S6** | Scale-down reclaim + cascade home | Scale-down order, CheckCascadingMigration | Costly loans released first; optional pull-home |
| **S7** | Proactive front-end on full ladder | PredictAndDecide + AllocateResources | Same allocate path; forecast swaps residual source |

Optional later (not blocking thesis core): dynamic root admission (your old #1–#2), κ/confidence blending. Vicinity partition + leader election now runs at bootstrap when coords or `latency_ms` are set ([vicinity-partition.md](./vicinity-partition.md)).

---

## 3. Stage details

### S0 — Baseline (done)

Keep as regression gate: `pytest` with autoscaler off + `reactive_vertical` demos.

No new coding on this branch except docs/cleanup unless a bug blocks S1.

---

### S1 — Horizontal mutation APIs (`spawn` / `terminate`)

**Why first:** every later tier is meaningless while these raise `NotImplementedError`.

**Env work**

- Implement `Env.spawn(ms_id, server_id, cpu_alloc, ram_alloc, …)`  
  - Enforce MS minima as floors (paper: new instance ≥ `cpu_min`/`ram_min`)  
  - Enforce server free capacity  
  - Register container on `World` / MS / server indexes  
- Implement `Env.terminate(container_id)`  
  - Free capacity; remove from indexes; refuse terminating last replica if you lock that (decide + test)  
- Extend `apply_actions` to accept `SpawnAction` / `TerminateAction` (deterministic order with resize)
- Result codes parallel to `ResizeResultCode`

**Still out of scope:** policy that *decides* when to spawn; loans; foreign clusters.

**Tests**

- Spawn on free server → routing weight updates next tick  
- Spawn rejected when under minima / over server cap  
- Terminate frees capacity; subsequent spawn can reuse it  
- Batch: resize + spawn same tick, deterministic apply order

**Gate:** horizontal mutation works with a **scripted** autoscaler (or unit tests calling APIs), no smart policy required.

---

### S2 — Reactive local ladder (BEV → BEH inside one cluster)

**v1 status:** done — see [s2-reactive-local-ladder.md](./s2-reactive-local-ladder.md). How Algorithm 4 is mapped: [allocate-resources.md](./allocate-resources.md).

**Policy:** evolve beyond vertical-only (new scaler name or extend `reactive_vertical` → e.g. `reactive_local`).

**Behavior (Up)**

1. Compute residual from drops / near-saturation (existing reactive signals OK for v1).  
2. **BEV:** pack onto existing replicas (`distribute_up` / shared packing).  
3. If residual remains **and** `sustained` (streak / horizon flag): skip further vertical preference and go BEH; else try BEV first then BEH (match Alg. AllocateResources).  
4. **BEH:**  
   - Prefer servers that already host the MS  
   - Then other servers in the **same** cluster by free CPU  
   - Spawn at minima until residual cleared or cluster full  
5. If still residual → emit escalated signal (log-only until S4), e.g. `NeedVicinityHelp`

**Behavior (Down)**

- Shrink vertical to minima first; then terminate coldest local replicas  
- Never escalate down outside the cluster

**Tests**

- Trace that exceeds vertical max but fits another worker → spawn appears  
- Worker full, sibling free → intra-cluster spawn  
- Cluster full → `NeedVicinityHelp` logged, no crash  
- Sustained surge: BEV skipped / minimized per locked rule

**Gate:** single-cluster overload demos show V then H without vicinity involvement.

---

### S3 — Ownership bookkeeping (prepare for borrow)

Paper requirement: only the **worker-owning** cluster mutates a node; the **app-owning** cluster issues intents.

**Model additions**

- Per app (or MS deployment): `owner_cluster_id` (stamp at initial placement; YAML or inferred from first container’s server)  
- Per server: loan registry `L_j = {(borrower, ms_id, tier, ts)}` (empty until S4)  
- Env mutation path: local owner applies immediately; non-owner must go through `request_worker_owner_scale(...)` (can no-op-reject foreign until S4)

**Tests**

- Owner can spawn/resize/terminate on its servers  
- Non-owner intent without loan → reject  
- Registry round-trip unit tests

**Gate:** all mutations funneled through one writer per server; no vicinity placement yet.

---

### S4 — Vicinity help (static partition + leader)

Uses existing `topology.vicinities` / `RootOrchestrator`.

**Protocol (simplified v1)**

1. Home CM finishes local BEV+BEH with residual → enqueue help request to vicinity leader.  
2. Leader runs one FCFS joint round per decision window over member free capacity (Alg. VicinityLeaderSchedule lite).  
3. Placement on neighbor worker → loan registry entry `tier=Vicinity`; app owner keeps decision responsibility; worker owner applies spawn.  
4. Status/usage of borrowed instance visible to app owner (mirror or shared world read — document the sim choice).

**Still simplified vs paper:** no distance ranking inside vicinity beyond config order; no Reserve formula until a follow-up if needed for fairness.

**Tests**

- Two-cluster vicinity; home saturated → spawn on neighbor  
- Leader is sole arbitrator for concurrent requests (ordering test)  
- Scale-down prefers terminating vicinity loan before local (if S6 not done yet, at least document TODO + minimal preference)

**Gate:** demo config with vicinity help under reactive policy; root unused for placement.

---

### S5 — Global escalation (BEG)

When leader cannot cover residual:

1. Forward to `RootOrchestrator` with coarse load summaries.  
2. Root walks candidates **outside** the home vicinity (v1: config order or simple free-capacity rank; paper’s load–distance score can wait).  
3. Successful place → loan `tier=Global`.

**Tests**

- Vicinity full → third cluster outside vicinity gets the replica  
- Clusters inside vicinity are not chosen as “global” candidates

**Gate:** three-cluster demo: local → vicinity → global failover visible in `actions.csv` / loans.

---

### S6 — Scale-down reclaim order + cascading migration

**Reclaim order on Down:** Global loans → Vicinity loans → local coldest replicas (paper cost hierarchy).

**Cascading migration:** if local free ≥ minima after shrink/terminate, optionally pull one expensive borrowed replica home (Alg. CheckCascadingMigration).

**Tests**

- Mixed local+vicinity+global replicas: down removes global first  
- After local free appears, borrowed replica migrates home (or explicit flag off)

**Gate:** down path never calls vicinity/global *for growth*; reclaim prefers expensive loans.

---

### S7 — Proactive autoscaler on the completed ladder

**v1 status:** done on this branch — see [s7-proactive-front-end.md](./s7-proactive-front-end.md). How Algorithm 3 is mapped (gate vs residual): [predict-and-decide.md](./predict-and-decide.md). Option A TCN (`60×2` → 5-step delta) on Alibaba `MS_588`; persistence remains the torch-free test backend.

Only now attach the predictor.

**Pipeline**

```text
sense (per-window RPS history)
  → PredictAndDecide (direction, δ_cpu, δ_ram, sustained)
  → AllocateResources (same S2–S5 ladder)
```

**Predictor contract (lock before coding)**

Reconcile these — do not ship ambiguity:

| Option | I/O | Notes |
|---|---|---|
| A (paper-ish) | `60×2` (load + normalized time) → 5-step delta | Matches your stated model |
| B (current `main` experiment) | window `W` univariate → 1-step, recursive roll | Already partially coded on `main` |

Recommendation: pick **one** for S7 v1; treat the other as a drop-in `predictors/` backend.

**Cold start:** hold or reactive-only until history full (lock explicitly; paper mentions κ blend — optional v2).

**Reuse from `main` (cherry-pick, don’t merge blindly)**

Candidates after S2+ exist:

- `autoscaler/proactive_auto_scaler/sensing.py`, `history.py`, `forecast.py`, `window_rps.py`
- LSTM loader **if** Option B
- Decide math / tests — rewire `allocate` to call shared ladder, not vertical-only

**Gate:** same overload scenarios as S2/S4/S5 but decisions driven by forecast; reactive remains available as baseline scaler name.

---

## 4. What not to rebuild from your old stages 1–2

| Old item | Recommendation |
|---|---|
| Live “CM assigns deploy task to worker” | Skip as a separate stage. Initial world = YAML. First dynamic deploy = `spawn` in S1/S2. |
| Root least-load app admission | Optional experiment after S5; not required for ladder correctness. |
| Full distance-based vicinity Algorithm | After static S4 works; swap generator behind same `RootOrchestrator` API. |

---

## 5. Suggested package evolution

```text
autoscaler/
  common/           # snapshot, distribute, actions re-exports, later ladder helpers
  reactive_vertical/   # keep as BEV-only baseline
  reactive_local/      # S2: BEV+BEH (recommended new name)
  reactive_hierarchical/  # S4–S6: + vicinity/global  (or grow reactive_local)
  proactive_auto_scaler/  # S7: sensing + decide + calls shared allocate ladder
env/
  api.py            # resize, spawn, terminate, apply_actions, owner RPC
  root.py           # topology now; BEG admit in S5
  loans.py          # NEW in S3/S4
```

Keep scalers **siblings** (no cross-imports); share packing/ladder in `common/`.

---

## 6. Demo / config progression

| Stage | Config idea |
|---|---|
| S1–S2 | 1 cluster, ≥2 servers, 1 MS, tight `cpu_max` so H is forced |
| S4 | Extend `demo_60_two_clusters.yaml` with shared MS pressure + vicinity |
| S5 | 3 clusters, 2 in vicinity, 1 outside |
| S7 | Same topologies; swap `autoscaler.name` |

---

## 7. Definition of “method complete” (MVP)

The simulator implements the proposed method when:

1. Reactive mode walks BEV → BEH → vicinity → global with ownership-safe mutations.  
2. Scale-down respects loan cost order (and optionally cascade-home).  
3. Proactive mode only replaces residual estimation; allocate path is shared.  
4. Part A still runs with autoscaler off for physics-only baselines.

Anything beyond that (learned vicinity partitions, κ blending, multi-MS affinity) is post-MVP.

---

## 8. Working-tree cleanup (candidates)

See the companion list in chat / section below. Do **not** delete until you confirm; some “unwanted on this branch” items are still useful on `main`.

### Safe to remove from version control (noise / accidental)

| Path | Why |
|---|---|
| `.mplconfig/fontlist-v3.11.0.json` | Local matplotlib cache; should not be tracked |
| `docs/implementation-plan copy.md` | Duplicate of `implementation-plan.md` |

### Add to `.gitignore` (keep local, stop tracking)

| Pattern | Why |
|---|---|
| `.mplconfig/` | Regenerated by matplotlib |
| `models/**/*.pth`, `models/**/*.pkl` *(optional)* | Large binaries — track via LFS or document download; currently on `main` only |

### On `main` but out of scope for this roadmap branch (do not port yet)

| Path | Why |
|---|---|
| `src/.../proactive_auto_scaler/**` | Premature relative to S1–S6; cherry-pick in S7 |
| `tests/test_proactive_*.py` | Same |
| `configs/demo_*proactive*.yaml` | Same |
| `docs/proactive-decide-and-apply*.md` | Planning for early proactive; superseded by this roadmap’s S7 |
| `docs/proactive-auto-scaler-implementation.md` | Same |
| `docs/how-to-run-proactive-lstm-tests.md` | Same |
| `docs/rps-forecast-predict-and-decide.md` | Keep as design ref; not needed until S7 |
| `docs/deep-research-report.md` | Background survey; optional |
| `docs/autoscaler-structure-naming-modularity-review.md` | Optional |
| `models/rps_lstm_v1/**` | Bring back in S7 if Option B |
| `traces/demo/api_3600_smooth_hill.csv`, `api_wc_day80_1s.csv` | Proactive demos; optional later |

### Untracked but keep

| Path | Why |
|---|---|
| `proposed_method_complete.tex` | Method authority — **add and track** when you want it in-repo |

### Already ignored (fine)

`results/`, `.pytest_cache/`, `.venv/`, `__pycache__/`

---

## 9. Immediate next action

1. Clean the two safe tracked junk paths (section 8).  
2. Implement **S1** (`spawn`/`terminate` + tests).  
3. Do not open S7 work on this branch until S2 is green.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-11 | Branch `plan/reactive-ladder-roadmap` from `7f998f2`; full ladder-before-proactive reorder |
