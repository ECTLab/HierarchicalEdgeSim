# Proactive Autoscaler — High-Level Implementation Approach

**Status:** planning / discussion  
**Source of truth for the algorithm:** `proposed_method_complete/proposed_method_complete.tex`  
**Audience:** us — how to turn that big ladder into incremental code on top of HierarchicalEdgeSim

Related: [06-autoscaler-plug-in-plan.md](./06-autoscaler-plug-in-plan.md) · [05-extension-plan-root-and-vicinity.md](./05-extension-plan-root-and-vicinity.md) · [07-autoscaler-implementation-steps.md](./07-autoscaler-implementation-steps.md)

---

## 1. What the paper is asking for (compressed)

Every decision window, each cluster manager runs roughly:

```text
Collect metrics
  → PredictAndDecide per microservice (proactive if confidence high, else reactive)
  → FCFS queue of scale intents
  → AllocateResources:
        BEV  (vertical, local / via owner RPC for borrowed nodes)
     → BEH  (horizontal spawn/terminate, local / via owner RPC)
     → if Up residual remains: VicinityLeaderSchedule (joint pool, lender reserves)
     → if still unmet: BEG (root, coarse least-loaded+distance)
  → StartCooldown
```

Scale-down never leaves the home cluster: release global loans → vicinity loans → local replicas, then optional cascading migration home.

Eight clarifications that matter for code:

| # | Idea | Code implication |
|---|---|---|
| 1 | App = set of MS types; decide per type | Already true in Part A model; keep per-`(m,c)` state |
| 2 | FCFS across MS types sharing a cluster | Intent queue ordered by detection time |
| 3 | RAM floor/ceiling on grow/shrink | Already partly in `resize` clamps; must seed `spawn` at min |
| 4 | Vector state per node / per MS | Need richer observation than today’s aggregates |
| 5 | Reusable BEV / BEH blocks | Shared functions, not one giant policy |
| 6 | Worker-owner sole mutator of lent nodes | Loan registry + owner-mediated mutate API |
| 7 | Lender reserves own forecast before lending | `Reserve` / `safe_j` from each member’s PredictAndDecide |
| 8 | Non-overlapping vicinities + leader joint round; simple BEG | Partition at bootstrap or YAML; S4 joint round + S5 BEG exist in lite form |

The predictor itself is intentionally a black box for now (ensemble + confidence + proactive/reactive switch). Do not block the ladder on training an LSTM.

---

## 2. How I would approach implementation

Do **not** implement the full Algorithm set in one go. The paper is a complete specification; the codebase is a vertical-only reactive scaler on a sim with static vicinities. Treat the paper as a **layered product**, each layer shippable and testable alone.

### Principle: env capability first, policy second

Same rule as the reactive vertical work:

- `env/` owns physics, ownership bookkeeping, and mutation APIs (`resize`, `spawn`, `terminate`, loan-aware owner path).
- `autoscaler/<name>/` owns PredictAndDecide, BEV/BEH, vicinity help packaging, cooldown.
- Root owns topology publication and later BEG admission.

Policy must never directly poke another cluster’s free vectors.

### Recommended phases

```text
Phase 0  Stabilize contracts (this doc + small design locks)
Phase 1  Horizontal local (spawn/terminate) + BEH on top of reactive
Phase 2  Ownership / loans (even without real multi-cluster help)
Phase 3  Predictor plug-in + PredictAndDecide (proactive switch)
Phase 4  Vicinity leader joint schedule (help requests + Reserve)
Phase 5  BEG at root + distance / partition upgrades
Phase 6  Cascading migration, confidence ensembles, polish
```

Each phase should leave Part A + `reactive_vertical` green, and add one new selectable scaler name (or grow `proactive_hierarchical` behind feature flags). Prefer **one new scaler folder** (`autoscaler/proactive_hierarchical/`) that reuses `autoscaler/common/` helpers, rather than overloading `reactive_vertical`.

### Why this order

1. **Horizontal first.** The paper’s ladder is meaningless until `NEED_HORIZONTAL` can become a real spawn. Most of BEV already exists in spirit as `reactive_vertical` + `resize`.
2. **Ownership before vicinity help.** Clarification 6 is structural: if you add cross-cluster placement without a single-writer owner path, bookkeeping will rot and be hard to unwind.
3. **Predictor as a plug-in early, but dumb.** Start with a stub / AR / last-window copy predictor that returns `û` vectors and a confidence score. Wire `PredictAndDecide` and the proactive/reactive gate; swap models later without touching BEV/BEH.
4. **Vicinity before global.** Leader joint schedule is the novel piece; BEG is deliberately simpler (coarse load + distance retries).
5. **Distance / auto-partition last among topology pieces.** Static YAML vicinities still unblock leader scheduling tests. Algorithm `VicinityPartitionAndLeaderElection` now runs at bootstrap when coords or `latency_ms` are set; YAML remains the override.

### Decomposition inside the new scaler

Mirror the paper’s named blocks as modules, not as one `policy.py`:

```text
autoscaler/proactive_hierarchical/
  params.py
  policy.py              # ClusterManagerCycle orchestration
  predict.py             # PredictAndDecide + confidence
  bev.py                 # Best-Effort Vertical
  beh.py                 # Best-Effort Horizontal
  allocate.py            # escalator: BEV → BEH → ρ
  cascade.py             # CheckCascadingMigration
  predictors/            # black-box interfaces + stub / later LSTM
```

Vicinity leader schedule and BEG can live either:

- under the same package as pure functions called when `env.is_leader(...)`, or
- as root/cluster helper modules in `env/` for the RPC-shaped APIs, with policy calling them.

Recommendation: **mutation + loan registry in `env/`**; **scheduling logic (who gets which node) in the autoscaler** (or a thin `autoscaler/common/vicinity_schedule.py`) so `env` stays algorithm-light.

### Simulation of “RPC”

In-process sim: `RequestWorkerOwnerScale` is just a function on `Env` / owner cluster façade with:

- idempotency key
- per-node lock (sim: single-threaded tick is enough if all mutations go through this path)
- Ack / Reject
- loan registry update

No need for real networking; keep the **contract** identical to the paper so a later distributed prototype can map 1:1.

### Decision cycle vs tick hook

Today: one global autoscaler `on_tick_end(env, tau)` after all MS physics.

Paper: per-cluster cycle, then leader barrier, then apply plans.

Practical mapping (now `cluster_manager_cycle`):

1. Keep one after-tick hook.
2. Inside the scaler, loop owner clusters in deterministic id order:
   - run local PredictAndDecide + AllocateResources for MS owned there
   - collect vicinity help requests `ρ` with \(t_{det}=\tau\)
3. For each vicinity, drain `Q_V` FCFS, emit placement plans.
4. Apply all mutations through owner-aware APIs.
5. Unresolved → BEG.

See [22-cluster-manager-cycle.md](./22-cluster-manager-cycle.md).

That preserves determinism without inventing a multi-process sim.

### What to deliberately stub at first

| Paper piece | First implementation |
|---|---|
| Predictor ensemble (LSTM…) | One stub + MAPE confidence; reactive fallback |
| Vicinity partition algorithm | Bootstrap from coords/`latency_ms`; YAML override for ladder experiments |
| Heartbeat / leader failure | Skip; assume leader always alive |
| Expected RT gate in BEG | Optional boolean always-true, then add |
| Inter-MS affinity | Out of scope (paper says future work) |

---

## 3. What we already have

| Asset | Where | Maps to paper |
|---|---|---|
| Apps → MS → containers | `env/models`, YAML | Clarification 1 (independent per-MS) |
| CPU **and** RAM alloc + MS min/max | specs + `resize` | Clarification 3 (partial) |
| Per-container tick history (`q_cpu`, `q_ram`, drops, …) | `ContainerTickRecord` | Inputs for PredictAndDecide / BEV |
| After-tick hook + `apply_actions` | `env/engine`, `env/api` | Decision window call site |
| Reactive vertical scaler (streaks, cooldown, distribute) | `autoscaler/reactive_vertical` | Rough cousin of BEV Up/Down + cooldown |
| `NEED_HORIZONTAL` log signal | actions / apply path | Escalation *signal* only — no capacity yet |
| Static vicinities + leader query API | `RootOrchestrator`, YAML | Clarification 8 topology *shell* |
| Multi-cluster world + servers | `World` | Home-cluster BEH placement target |
| Autoscaler plug-in folder pattern | `autoscaler/<name>/` | Place for the new scaler |

---

## 4. What we do **not** have (gaps that block the paper)

Grouped by dependency order.

### 4.1 Env mutations & horizontal capacity (hard blockers for BEH)

| Gap | Today | Needed |
|---|---|---|
| Live `spawn` | `NotImplementedError` | Create container on a chosen server at ≥ MS min CPU/RAM; wire into routing/traces/history |
| Live `terminate` | stub | Remove container; free capacity; update MS `container_ids` |
| `apply_actions` only handles `resize` / logs `need_horizontal` | — | Dispatch `spawn` / `terminate` (order: terminate → resize → spawn is a reasonable lock) |
| New replica ↔ load trace | Traces are per-MS | Policy for how a new replica shares Λ (equal split / weight) — must be explicit |

Without these, tiers 2–4 of the ladder cannot execute.

### 4.2 Ownership, loans, eligibility (hard blockers for vicinity/global)

| Gap | Today | Needed |
|---|---|---|
| Loan registry `L_j` | Missing | Per-server stack/ledger: `(borrower, m, tier, ts)` |
| Application-owner vs worker-owner | Container lives on a server; no borrower stamp | Stamp which cluster “owns” the MS deployment decision; status reporting conceptually to app owner |
| `RequestWorkerOwnerScale` | Missing | Sole mutation path for non-owned nodes |
| Eligibility mask `e_m` | Implicit “all containers of MS” | Owned servers ∪ currently loaned-to-us for `m` |
| Tier-aware scale-in order | N/A | Global → vicinity → local using `tier` on loans |

### 4.3 Observation model (clarification 4)

| Gap | Today | Needed |
|---|---|---|
| Node-level free/used vectors for a cluster | Ad-hoc via `get_server_free` | Stable collect API: `u/f` CPU/RAM over owned workers |
| Per-MS vectors `h, a, q, e` | Aggregates in reactive scaler | Length-`W` (or dict-by-server) views for BEV/BEH |
| Mirrored state for borrowed nodes | Missing | App-owner mirrors of alloc/instance on foreign servers |

### 4.4 Decision pipeline pieces (policy)

| Gap | Today | Needed |
|---|---|---|
| Residual `δ_cpu/δ_ram` toward `θ_target` | Drop-deficit / α heuristics | Paper’s residual formulas in PredictAndDecide |
| `sustained` flag | Streaks only | Skip BEV → BEH on prolonged surge |
| FCFS intent queue across MS | Scan by `ms_id` sort | Detection timestamp ordering |
| Reusable BEV / BEH | Vertical distribute only | Explicit blocks + horizontal |
| Cooldown tied to horizon `H` | Fixed `cooldown_ticks` | Align with forecast horizon / windows |
| Cascading migration | Missing | After local free, pull expensive borrowed replica home |

### 4.5 Predictor / proactive mode

| Gap | Today | Needed |
|---|---|---|
| Any forecast | None (pure reactive) | Predictor interface: horizon-`H` û for CPU/RAM util |
| Confidence `κ` + MAPE window | Missing | Gate proactive vs reactive |
| Cold start | N/A | Force reactive until `W_κ` |
| Ensemble selection | N/A | Optional later; one model is enough for v1 |

### 4.6 Vicinity joint scheduling (clarification 7–8)

| Gap | Today | Needed |
|---|---|---|
| Help-request object `ρ` | Only `NEED_HORIZONTAL` log | Structured residual + mins + detection time |
| Leader barrier / free-vector reports | Missing | Per-window member → leader free + Reserve |
| `Reserve` / `safe_j` | Missing | Lender protects own forecast before granting |
| `VicinityLeaderSchedule` | Missing | Single FCFS joint placement over `N_V` |
| Placement plan apply via owner API | Missing | Plans are intents, not direct mutates |

### 4.7 Root / global / distance

| Gap | Today | Needed |
|---|---|---|
| `beg_admit` | Stub `NotImplementedError` | Coarse `L_c`, rank by load+γ·distance, bounded retries |
| Inter-cluster distance / latency | Coords or `latency_ms` for Algorithm 1; not used to delay requests | Same matrix could later rank BEG |
| Aggregate load summaries at root | Missing | Periodic coarse stats (not fine per-node globally) |
| Auto vicinity partition + election | `env/partition.py` at bootstrap; YAML override | Periodic \(T_{\mathit{repart}}\) / heartbeat still future |
| Leader failure / heartbeat | Missing | Future work per paper |

### 4.8 Orchestration shape

| Gap | Today | Needed |
|---|---|---|
| One global scaler over all MS | Yes | Per-cluster cycle semantics inside the hook (or multi-scaler later) |
| Which MS a cluster “hosts” for decisions | All MS globally | Scope decisions to MS with local and/or borrowed presence; avoid double-deciding |

---

## 5. Suggested first concrete milestones (after design lock)

1. **Spec lock (short):** action types for spawn/terminate; loan record fields; predictor interface; apply order.
2. **Env: spawn + terminate + apply_actions dispatch** + tests (same-server packing, MS min seed, routing still consistent).
3. **Scaler v0.5:** reactive ladder = BEV (reuse vertical) → BEH local only; `NEED_HORIZONTAL` becomes real spawn when residual remains.
4. **Env: loan registry + owner-scale API**; tests that non-owner cannot mutate directly.
5. **Predictor stub + PredictAndDecide** (proactive thresholds + confidence gate); keep BEH local.
6. **VicinityLeaderSchedule** on static YAML topology + Reserve.
7. **BEG** + distance matrix in config.
8. **Cascade migration + reclaim order** polish; only then consider LSTM-family predictors / auto-partition.

---

## 6. Risks / design locks to settle early

1. **How new replicas share demand** when MS Λ is a single trace — equal split vs capacity-weighted (affects every horizontal experiment).
2. **Simplicity of “cluster manager” in one process** — one hook that emulates per-cluster cycles (recommended) vs true multi-agent processes (overkill now).
3. **Whether `reactive_vertical` stays forever** as baseline for A/B, with proactive as a separate `name:` — strongly yes.
4. **Where Reserve is computed** — must reuse the same PredictAndDecide residuals so lenders and borrowers stay consistent (paper Eq. reserve/safe).
5. **RAM always first-class** on spawn (seed `ram_min`) even if some demos use RAM≈0 — keep the invariant so clarification 3 does not regress.

---

## 7. Bottom line

The algorithm looks large because it is a **four-tier escalator** plus **ownership** plus **forecast gating**. The current codebase already has the sensing plane, vertical mutation, cooldown/streak habits, and a static vicinity shell. The missing foundation is not “an LSTM”; it is **horizontal mutation, loan/ownership, a predictor interface, and leader-mediated help**.

Build in that order: make the ladder’s lower rungs real, keep the predictor swappable, and only then spend effort on vicinity joint scheduling and BEG. That path matches both the paper’s escalation ladder and the way this repo already grew Part A → reactive vertical → root/vicinity shell.
