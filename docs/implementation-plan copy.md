# Implementation Plan (v2)

Modular Python plan for the hierarchical edge autoscaling workbench.

**Two parts, kept separate**

| | Part A — Environment | Part B — Autoscaler |
|---|---|---|
| Job | Mimic clusters / apps / containers / load over time | Decide scaling; call env APIs |
| Works alone? | **Yes** (autoscaler off) | Needs Part A |
| Contains hierarchy? | No — only topology metadata | Yes — inside hierarchical plugin |

Reviewed with Sonnet 5 ([critique](f22f4a5e-2303-4c2c-88a0-38aab58fc1c4)): architecture kept; contracts, challenges, and milestones tightened below.

Related: [custom-simulator-environment.md](./custom-simulator-environment.md) · [implementation-evaluation-options.md](./implementation-evaluation-options.md) · `../algorithm.tex`

---

## 1. Design lock (accept before coding)

| # | Decision | v1 choice |
|---|---|---|
| L1 | Usage model | **Option A:** `cpu_usage = min(alloc, share × ρ)` |
| L2 | RAM usage | **Floor-dominated:** `ram_usage = ram_min + q × (ram_alloc − ram_min)` |
| L3 | BEG latency gate from `algorithm.tex` | **Simplified away:** admit by load+distance only; document as deliberate v1 gap |
| L4 | Vicinities | **Hand-specified** in YAML |
| L5 | Root / leader | **Plugin logic only** — env has no `RootOrchestrator` object (only topology metadata). Reconciles env-doc diagrams with this plan. |
| L6 | Concurrency | **No threads.** Simulated CM parallelism = decide-all-then-apply inside the hierarchical plugin |
| L7 | Float compares | Global `EPS = 1e-9` for residual vs zero |
| L8 | Vertical grow/shrink on a node | Split delta **evenly** across co-located containers of that MS (`resize_pool` helper in plugin, not env) |
| L9 | In-window FCFS | Sort by `(ms_id, cluster_id)` — all events in a window are simultaneous; no wall-clock `t_det` |
| L10 | Stack | Plain Python; no Mesa / EdgeSimPy / Docker in eval loop |

---

## 2. Critical challenges → solutions

| Challenge | Solution (fits A/B split) |
|---|---|
| **C1. Loans needed for scale-down order** | Every `Container` has mandatory `tier ∈ {local,vicinity,global}`, `borrower_cluster_id`, `loaned_at` from day one. Default on local spawn: `tier=local`, `borrower=app_home`. No separate registry — derive loans from `list_containers()`. |
| **C2. Stale free capacity in Stage 2** | Stage 1: plan all local actions on snapshot S0, then apply. Stage 2/3: call `metrics_snapshot()` **again**. Never reuse S0. Test: Stage 1 fills a server → Stage 2 must not pack onto it. |
| **C3. BEG response-time gate** | v1: omit; use `L_c + γ·d` only (L3). Thesis states simplification. |
| **C4. Paper metrics / safety tests need audit trail** | Env appends every write attempt to an event log; expose `get_events()`. Plugins and tests never touch `World` internals. |
| **C5. BEV pool vs per-container resize** | Plugin helper `resize_pool(api, ms, server, Δcpu, Δram)` splits evenly; loops atomic `resize()`. |
| **C6. FCFS timestamps** | Use sorted ids only (L9). |
| **C7. Cooldown / sustained / κ state leaks** | State lives on **Autoscaler instance** (`__init__`). One fresh instance per `run()`. Never module globals. |
| **C8. Scale-down flips into grow escalation** | Down only in Stage 1; residual clamped to 0 after local reclaim; **no HelpRequest** on Down. Test required. |
| **C9. Vicinity pack order ≠ apply order** | Stage 2/3 `spawn()` in **exact pack order**. Test two requesters one server. |
| **C10. Stringly Reject / half resize** | `RejectReason` enum; `resize` is **atomic** (cpu+ram together or neither). |
| **C11. Float drift** | Use `EPS` everywhere (L7). |
| **C12. Non-determinism** | Sorted iteration; every milestone checks identical CSV on repeat run. |
| **C13. Metrics schema late** | Lock CSV columns before vicinity work (milestone B2). |
| **C14. Env vs plugin “root”** | L5 — root is Stage 3 in `hierarchical.py`. |

---

## 3. Part A — Environment

### 3.1 Objects

```text
World
├── Topology     # latency matrix; vicinities: members + leader_id
├── Cluster[]    # owns Server ids
├── Server[]     # cpu_cap, ram_cap
├── Application[] / MicroserviceSpec[]
└── Container[]  # alloc, usage, tier, borrower_cluster_id, loaned_at, …
```

| Field on Container (mandatory) | Meaning |
|---|---|
| `cpu_alloc`, `ram_alloc` | Reserved size |
| `cpu_usage`, `ram_usage` | Observed this window |
| `tier` | `local` \| `vicinity` \| `global` |
| `borrower_cluster_id` | App-home cluster that “owns” the workload |
| `server_owner_cluster_id` | Physical owner (derived from server) |
| `loaned_at` | Window index when created (0 ok for bootstrap) |

Free CPU/RAM on a server = `cap − Σ alloc` (never `cap − usage`).

### 3.2 EnvAPI contract

Protocol + types live in `env/api.py` (so `env/` never imports `autoscaler/`).

#### Read

| Method | Purpose |
|---|---|
| `get_time() -> int` | Current window |
| `list_clusters() -> list[ClusterId]` | Inventory |
| `list_servers(cluster_id) -> list[ServerId]` | Owned servers |
| `list_containers(...) -> list[ContainerView]` | Includes tier, borrower, alloc, usage |
| `get_server_free(server_id) -> (cpu, ram)` | From alloc |
| `get_ms_spec(ms_id) -> SpecView` | min/max cpu/ram, ρ |
| `get_ms_metrics(ms_id, home_cluster) -> MsMetrics` | Λ, total alloc, max/avg q, counts |
| `get_eligible_nodes(ms_id, cluster_id) -> list[ServerId]` | Owned ∪ currently loaned to this cluster for ms (**e_m**) |
| `get_vicinity(cluster_id) -> VicinityView` | `members` (incl. self), `leader_id` |
| `get_latency(c1, c2) -> float` | ms |
| `metrics_snapshot() -> Snapshot` | Frozen free/alloc/usage/Λ view |
| `get_events(since_t=None) -> list[Event]` | Audit / paper metrics |

#### Write (return `Ok` or `Reject(RejectReason)`)

| Method | Rules |
|---|---|
| `spawn(ms_id, server_id, cpu, ram, *, borrower_cluster_id, tier)` | `borrower` must equal app home; validate free & mins; set `loaned_at=t` |
| `resize(container_id, cpu, ram)` | **Atomic**; floors/caps; enough free for growth |
| `terminate(container_id)` | Remove container |

```python
class RejectReason(Enum):
    INSUFFICIENT_CAPACITY = "insufficient_capacity"
    BELOW_MIN = "below_min"
    ABOVE_MAX = "above_max"
    UNKNOWN_ID = "unknown_id"
    INVALID_BORROWER = "invalid_borrower"
```

#### Run

```text
for t in 1..T:
    step_load()                 # trace → usage
    if autoscaler: autoscaler.on_window(api)
    log_metrics()
    advance()
```

`autoscaler=None` ⇒ Part A demo still works.

#### Event log (every write attempt)

`(t, op, ms_id, container_id, server_id, tier, borrower, delta_cpu, delta_ram, result)`

### 3.3 Autoscaler protocol (in `env/api.py`)

```python
class Autoscaler(Protocol):
    def on_window(self, api: EnvAPI) -> None: ...
```

Engine type-hints this protocol from `env`, not from plugin package.

### 3.4 Part A modules

```text
src/hass/env/
  models.py      # dataclasses
  world.py
  topology.py
  workload.py    # CSV → windows
  usage.py       # Option A + RAM rule
  events.py      # event log
  api.py         # EnvAPI + Autoscaler Protocol + RejectReason
  engine.py      # run loop
  metrics_log.py # CSV
```

**`env/` must not import `autoscaler/`.**

### 3.5 Part A milestones

| ID | Deliverable | Verify |
|---|---|---|
| A0 | Package + pytest smoke | collects |
| A1 | YAML → World + topology | inventory print |
| A2 | Write APIs + RejectReason + mandatory tier/borrower | capacity unit tests |
| A3 | Trace → usage, fixed replicas | hand-math CSV; **repeat run identical** |
| A4 | `examples/run_env_only.py` | plot q(t) under burst, scaler off; **repeat identical** |

**Gate:** no Part B until A4 done.

---

## 4. Part B — Autoscaler plugins

### 4.1 Shared local semantics (`autoscaler/common/`)

**PredictAndDecide (structure from day one)**  
- Maintain per-(cluster, ms) instance state: cooldown, last decisions (sustained streak), optional κ.  
- v1 predictor stub always returns `κ = 0` → always **Reactive** branch (structure ready for MA/LSTM later).  
- Residual (Up): `δ = max(0, A × ũ / θ_target − A)` (and ram analog); Down: non-positive; clamp with `EPS`.

**BEV / BEH helpers**  
- Operate only via EnvAPI.  
- BEV uses `resize_pool` (even split).  
- BEH spawn at mins; terminate by reclaim order when Down: `global → vicinity → local`, then coldest `q`.

**Scale-down rules**  
- Only local stage.  
- After reclaim, residual **clamped to 0**.  
- Never enqueue HelpRequest on Down.

### 4.2 Hierarchical plugin — stages inside `on_window`

```text
def on_window(api):
    # ----- Stage 1: simulated parallel CMs -----
    S0 = api.metrics_snapshot()
    plans = []
    help = []
    for cluster in sorted(api.list_clusters()):
        for ms in sorted(mss_of(cluster)):
            direction, δ, sustained = predict_and_decide(...)  # uses S0 + instance state
            if direction is NONE: continue
            if direction is DOWN:
                plans += plan_local_down(cluster, ms, δ, S0)   # BEV/BEH; clamp; no help
            else:
                local_plans, residual = plan_local_up(cluster, ms, δ, sustained, S0)
                plans += local_plans
                if residual_cpu > EPS or residual_ram > EPS:
                    help.append(HelpRequest(...))
    apply_sequential(api, plans)   # only owned / eligible local ops

    # ----- Stage 2: vicinity leaders -----
    S1 = api.metrics_snapshot()    # MUST refresh
    for V in sorted(vicinities):
        reqs = [h for h in help if h.requester in V.members]
        pack = vicinity_pack(V, reqs, S1)   # uses free from S1; forecast reserve = 0 until predictors
        apply_sequential(api, pack.spawns) # EXACT pack order; tier=vicinity
        help = remaining(help, pack)

    # ----- Stage 3: root / global -----
    S2 = api.metrics_snapshot()
    for h in sorted(help):
        spawns = beg_pack(h, S2)           # L+γd ranking; up to B retries
        apply_sequential(api, spawns)      # tier=global
```

**Reactive baseline:** Stage 1 only (Up/Down local); ignore help; same BEV/BEH helpers.

**Safety (tested via `get_events`)**  
- Stage 1 emits no `spawn` with `tier≠local` onto foreign-owned servers.  
- Stage 2/3 apply order = pack order.  
- Down windows produce zero HelpRequest-driven spawns.

### 4.3 Part B modules

```text
src/hass/autoscaler/
  reactive_local.py
  hierarchical.py
  common/
    predict.py      # PredictAndDecide + κ stub
    bev.py
    beh.py
    types.py        # HelpRequest, etc.
  predictors/       # later: moving_average, lstm
```

Plugins import **only** `hass.env.api` types + their `common/`.

### 4.4 Metrics schema (lock before vicinity)

Per-window CSV (and/or events aggregation):

`t, ms_id, home_cluster, lambda, cpu_alloc_total, cpu_usage_total, q_max, n_replicas, n_local, n_vicinity, n_global, unmet_cpu, unmet_ram, actions_up, actions_down, rejects, cost_proxy`

`cost_proxy = Σ (c_cpu×cpu_alloc + c_mem×ram_alloc)` with constants from config.

### 4.5 Part B milestones

| ID | Deliverable | Verify |
|---|---|---|
| B0 | Protocol wiring + no-op scaler; PredictAndDecide **skeleton** with κ=0 stub | env run unchanged; **repeat identical** |
| B1 | BEV/BEH helpers + **ReactiveLocal** Up **and** Down (clamp; reclaim order for local-only) | burst+decay; Down never escalates; **repeat identical** |
| B2 | Event log → metrics CSV schema filled for reactive | columns present; **repeat identical** |
| B3 | Hierarchical Stage 2 (vicinity); forecast reservation = **0** | hotspot → neighbor loans; stale-snapshot test; pack-order test; **repeat identical** |
| B4 | Stage 3 global (`L+γd`, retries B) | spill beyond vicinity; **repeat identical** |
| B5a | Hand scenario forcing Stage 2 **and** 3 | regression fixture |
| B5b | Same real trace: reactive vs hierarchical | thesis comparison table |
| B6 | Optional: MA/LSTM + κ; optional forecast reservation | proactive path |

---

## 5. Full package layout

```text
hass/
├── pyproject.toml
├── README.md
├── configs/tiny.yaml
├── traces/sample.csv
├── examples/
│   ├── run_env_only.py
│   ├── run_reactive.py
│   └── run_hierarchical.py
├── tests/
│   ├── env/
│   └── autoscaler/
└── src/hass/
    ├── env/           # Part A
    └── autoscaler/    # Part B
```

---

## 6. Must-verify before first coding commit

- [ ] L1–L10 accepted  
- [ ] C1–C14 solutions accepted  
- [ ] EnvAPI tables (§3.2) accepted as the only plugin interface  
- [ ] `Autoscaler` Protocol lives in `env/api.py`  
- [ ] Container tier/borrower mandatory from A2  
- [ ] Event log + metrics schema accepted  
- [ ] Scale-down clamp test scenario sketched  
- [ ] Vicinity pack-order + stale-snapshot tests sketched  
- [ ] A4 gate before any real scaler logic  

---

## 7. v1 simplifications (state openly in thesis)

1. No queueing delay model / no BEG response-time confirmation.  
2. No algorithmic vicinity partition (YAML only).  
3. Forecast reservation = 0 until B6.  
4. Predictor confidence stubbed (always reactive) until B6.  
5. Independent MS demand (no call-graph).  

---

## 8. One-page picture

```text
PART A (always)
  Trace → step_load → usages on containers → CSV
  APIs: read metrics / write spawn·resize·terminate / events

PART B (optional plugin each window)
  Reactive:     Stage1 local only
  Hierarchical: Stage1 (decide-all on S0 → apply)
                Stage2 (snapshot S1 → pack vicinity → apply in order)
                Stage3 (snapshot S2 → global → apply)

examples: run_env_only | run_reactive | run_hierarchical
```

---

## 9. Immediate next step

Accept §1 Design lock + §6 checklist, then start **A0–A4** only.  
Do not implement hierarchical Stage 2 until **B1–B2** (reactive + metrics) are green.
