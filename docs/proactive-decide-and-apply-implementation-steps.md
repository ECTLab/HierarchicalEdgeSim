# Implementation Steps — Proactive Decide + Apply (modular)

**Status:** planning only — no coding until this guide is accepted  
**Spec authority:** [proactive-decide-and-apply-plan.md](./proactive-decide-and-apply-plan.md) — if this guide and the plan disagree, the **plan** wins on mechanism; this guide wins on **step order, module boundaries, and test gates**  
**Prior work (done):** [proactive-auto-scaler-implementation.md](./proactive-auto-scaler-implementation.md) Steps 1–2 (TTW RPS, history, LSTM forecast, `rps_forecast.csv`)  
**Decide math:** [rps-forecast-predict-and-decide.md](./rps-forecast-predict-and-decide.md) §4.1–4.4, §4.6 (ignore §4.5)

---

## How to use this guide

```text
Finish one step → run that step’s tests → full pytest still green → next step
```

| Rule | Meaning |
| --- | --- |
| One step at a time | Do not start step *n+1* until step *n* gate is green |
| Modular deliverable | Each step ends with a **importable module** or a **behavior-preserving extract** — not a half-wired `policy.py` |
| No cross-scaler imports | `proactive_auto_scaler` ↛ `reactive_vertical` and vice versa; shared code only via `autoscaler/common/` |
| No reactive-as-baseline | Do not copy reactive policy ideas into the proposed method; ask when unsure |
| `decide.py` stays pure | Never imports `env` or action types |
| Env apply path untouched | Scalers return actions; `Env.apply_actions` / `resize` stay the only mutators |
| No spawn / κ / reactive warm-up | Out of scope for this track |

**Locked defaults (params):** `ttw_ticks=60`, `feature_window=10`, `horizon_H=3`, `theta_up=0.80`, `theta_down=0.30`, `theta_target=0.60`, `sustained_tau=2`, `cooldown_C=3`. Short test fixtures may override TTW/W downward.

---

## Progress

| Step | Deliverable | Status |
| --- | --- | --- |
| **0** | Lift `snapshot` + `distribute` into `common/`; rewire reactive | **Done** |
| **1** | Extract proactive `sensing.py` (still no actions) | **Done** (landed with Step 3) |
| **2** | Pure `decide.py` + unit tests | **Done** |
| **3** | Proactive `allocate.py` + params + policy wire + cooldown | **Done** |
| **4** | Demo YAML (+ optional decision log) | **Done** — `configs/demo_wc_day80_proactive_1h_onec.yaml` |

Suggested PRs map 1:1 to steps (see plan §16).

---

## Target module map (end state)

```text
autoscaler/common/
  actions.py              # exists
  load.py / supported.py / params_base.py
  snapshot.py             # Step 0 — MsSnapshot, ReplicaView, snapshot_ms
  distribute.py           # Step 0 — distribute_up/down + DistributeParams

autoscaler/reactive_vertical/
  policy.py               # Step 0 — import common only (behavior unchanged)
  params.py               # Step 0 — embed/build DistributeParams from flat YAML
  distribute.py           # DELETE after Step 0

autoscaler/proactive_auto_scaler/
  sensing.py              # Step 1 — TTW accumulate + forecast log
  decide.py               # Step 2 — PredictAndDecide (pure)
  allocate.py             # Step 3 — signed δ → common.distribute
  policy.py               # Steps 1+3 — thin orchestrator + TTW cooldown
  params.py               # Step 3 — θ, cooldown_C, defaults 60/10
  ttw_rps.py / history.py / forecast.py / predictors/   # unchanged
```

**Dependency direction (enforce in review):**

```text
decide / ttw_rps / history / forecast / predictors  →  pure
snapshot / distribute / sensing / allocate            →  may use Env
policy                                                →  calls stages only
reactive_vertical  →  common  ←  proactive_auto_scaler
```

---

## Step 0 — Shared vertical substrate (`common/`)

**Goal:** One snapshot + packing implementation. Packing follows the **proposed** paired CPU/RAM rule (not “preserve whatever reactive distribute did”).

### 0.1 Modules to add

| File | Contents | Must NOT contain |
| --- | --- | --- |
| `common/snapshot.py` | `ReplicaView`, `MsSnapshot`, `snapshot_ms(env, ms_id, tau)` | Streaks, intent, decide math |
| `common/distribute.py` | `DistributeParams`, `validate_distribute_params`, `distribute_up`, `distribute_down` | Scaler-specific policy; hardcoded scaler reason strings as defaults |

**API lock for distribute:**

```text
distribute_up(..., params: DistributeParams, reason: str, ...)
distribute_down(..., params: DistributeParams, reason: str, ...)
```

Callers pass their own reason (`proactive_*` / `reactive_*`).

### 0.2 `room_*` formulas

```text
room_up_cpu  = min(spec.cpu_max − alloc, server_free_cpu(host))
room_up_ram  = min(spec.ram_max − alloc, server_free_ram(host))
room_down_*  = max(0, alloc − spec.min)
```

### 0.3 Paired grant rule (LOCKED — modeling)

When `ram_per_request_mb > ε`:

```text
give_cpu = min(remain_cpu, room_up_cpu)   # Up; analogous take_* on Down
give_ram = min(remain_ram, room_up_ram)
if give_cpu ≤ ε or give_ram ≤ ε:
    skip this replica   # both must move
else:
    apply both give_cpu and give_ram
```

When RAM is disabled in the world (`ram_per_request_mb ≤ ε`): CPU-only grants allowed.

### 0.4 Reactive rewire

Reactive **imports** `common` only. If old reactive tests assumed one-sided growth, **update the tests** — do not weaken pairing to keep reactive green.

### 0.5 Gate (tests)

- Snapshot: MS-max vs server-full `room_up`; down ignores server free.
- Distribute: paired skip when only one dim has room; both dims change on a successful grant.
- Reactive streak/intent tests updated only as needed for pairing.

**Stop.** Do not touch proactive policy yet.

---

## Step 1 — Extract proactive sensing (behavior-preserving)

**Goal:** `policy.on_tick_end` becomes a short call into `sensing.py`; still returns `[]`.

### 1.1 Module

| File | Responsibility |
| --- | --- |
| `sensing.py` | Per-tick `lambda_in` accumulate; on TTW close: `r_t`, history append, forecast log rows, optional `r_hat` |
| `policy.py` | Call sensing; return `[]` |

Prefer a typed close-record (e.g. `SenseCloseResult` with `ms_id`, `ttw_t`, `r_t`, `r_hat|None`, `history_full`) so Step 3 does not parse log rows.

### 1.2 Gate

- Existing proactive forecast tests green.
- No new actions in `actions.csv`.
- Naming cleanup from the modularity review is optional here (same PR is fine if mechanical).

**Stop.** No decide/allocate yet.

---

## Step 2 — Pure `decide.py`

**Goal:** PredictAndDecide as plain floats in / dataclass out. Zero Env.

### 2.1 Module

| Symbol | Role |
| --- | --- |
| `Direction` | `UP` / `DOWN` / `NONE` |
| `DecideResult` | `direction`, `delta_cpu`, `delta_ram` (signed), `sustained` |
| `predict_and_decide(...)` | §4.1–4.4 only |

**Util bridge lock:**

```text
C_full_cpu = (A_cpu / max(ρ_cpu, ε)) / tick_sec
A_req_cpu  = ρ_cpu * r_star * tick_sec / θ_target
r_star     = max(r_t, max(r_hat))
u_obs      = max(u_rps, u_meas)
```

No server-free arguments. Do not clamp δ by Σ `room_up`.

### 2.2 Gate (unit tests, no Env)

| Case | Expect |
| --- | --- |
| High `u_obs` | UP |
| Cold `u_obs` but hot horizon | UP |
| Both cold | DOWN |
| Band between θ_down and θ_up | NONE |
| Known `(A, ρ, tick_sec, r★, θ)` | Exact residual |
| `A=0`, positive demand | Positive Up residual |
| DOWN | `delta ≤ 0` |
| Sustained vs `sustained_tau` | true/false |

**Stop.** Do not wire into policy yet.

---

## Step 3 — Allocate + params + policy orchestration

**Goal:** End-to-end proactive vertical scaling on TTW close for ready MS.

### 3.1 Modules

| File | Responsibility |
| --- | --- |
| `allocate.py` | `DecideResult` + `MsSnapshot` → `abs(δ)` → `common.distribute_*` with `proactive_*` reasons |
| `params.py` | Add θ / `sustained_tau` / `cooldown_C` / optional `distribute:`; **defaults `ttw_ticks=60`, `feature_window=10`** |
| `policy.py` | sensing → (if ready & not cooldown) snapshot → decide → allocate; `on_actions_applied` arms TTW cooldown |

### 3.2 Orchestration contract

```text
mid-TTW:                 sensing only → []
TTW close, not full:     sensing only → []          # HOLD
TTW close, full, cooldown: sensing+forecast → []
TTW close, full, ready:  decide → allocate → actions
```

Cooldown: `next_allowed_ttw[ms] = t + C + 1` only if ≥1 **resize** was emitted for that MS **and** `any(result.ok)`. `need_horizontal` alone does not arm.

### 3.3 Gate

- Import test: proactive tree does not import `reactive_vertical`.
- Params: unknown keys rejected; θ ordering validated; defaults 60/10.
- Integration fixture (short `ttw_ticks` / `feature_window` overrides OK):
  - before full history → no scale actions
  - after full + rising load → `proactive_up` (or down) in `actions.csv` + next-tick alloc change
  - cooldown skips decide TTWs; forecast log continues
- Multi-replica fixture (see §Ambiguities tests): at least one shared-server and one split-server case.

**Stop.** Demo polish is Step 4.

---

## Step 4 — Demos + optional decision log

1. Update `configs/demo_*_proactive*.yaml` with decide knobs; keep or override 60/10 depending on horizon.
2. Optional `decision_log` list on the scaler (direction, residuals, sustained, `u_obs`, `r_star`) — buffer first; CSV only if a demo needs it.

### 4.1 Gate

- Demo config loads and runs.
- Document how to read `actions.csv` reasons (`proactive_up` / `proactive_down` / `need_horizontal`).

---

## Decisions & open questions (esp. multi-container vertical)

**Policy:** Do **not** copy reactive algorithm choices into the proposed scaler. Only shared **mechanics** live in `common/` (snapshot rooms, paired distribute, action types). For anything else, decide below — do not default to “what reactive did.”

### Resolved

#### C. CPU/RAM must move together — **LOCKED**

**Modeling:** each request needs CPU **and** RAM (`cpu_per_request_cores`, `ram_per_request_mb`). Serving capacity only rises/falls coherently if both allocs change.

**Rule:** if RAM is modeled (`ram_per_request_mb > ε`), skip a replica unless **both** dimensions can take a positive grant/shrink; never emit CPU-only or RAM-only resizes in that mode. If the world sets `ram_per_request_mb ≤ ε`, CPU-only is allowed.

#### H. `need_horizontal` alone does not arm cooldown — **LOCKED**

Otherwise an MS with no vertical room would go silent while still needing capacity.

#### I. Zero replicas → allocate no-op — **LOCKED**

No fake containers; spawn/BEV later.

#### L. Defaults `ttw_ticks=60`, `feature_window=10` — **LOCKED**

Short fixtures/demos override downward.

#### M. LSTM window must match `feature_window` — **LOCKED**

Fail fast on mismatch; model meta is already 10.

---

### Resolved for v1 implementation (2026-08-07)

| Q | Choice | Meaning |
| --- | --- | --- |
| 1 | **(a)** | Decrement per-server free inside `distribute_up` while packing |
| 2 | **(a)** | Accept `apply_actions` sort by `container_id` (document; single-container demos unaffected) |
| 3 | **(a)** | Unmet Down residual: silent drop |
| 4 | **(a)** | Consolidate Down: prefer one/few cold replicas |
| 5 | **(a)** | `u_meas` = max over containers of `max(q_cpu, q_ram)` |
| 6 | Locked | **Up rank:** drop share, util `q`, paired room; **Down rank:** slack, no-drop, paired room; **skip busy** on Down (`slack < theta_free` and `drop > eps_drop`) |
| 7 | **(a)** | Arm cooldown if `any(result.ok)` |
| 8 | **(a)** | No cross-MS fairness on a shared server (document) |

**Paired room for ranking:** eligibility requires both `room_up_cpu` and `room_up_ram` > ε when RAM is modeled; score room term uses `min(room_up_cpu / max_cpu_room, room_up_ram / max_ram_room)` (or CPU-only room term if RAM disabled).

---

## Multi-container vertical — quick reference (after pairing lock)

### Scale up

```text
δ_cpu, δ_ram  (MS-wide, from decide)
    → rank eligible replicas (signals TBD — Q6)
    → for each: paired grant only if both rooms allow; else skip
    → ResizeAction absolute targets (proactive_up)
    → leftover → need_horizontal (log)
    → apply_actions (order TBD — Q2) → Env.resize hard gate
```

### Scale down

```text
|δ_cpu|, |δ_ram|
    → rank / optional busy-skip (TBD — Q4, Q6)
    → paired shrink both dims; clamp to MS min
    → unmet |δ| handling TBD — Q3
```

### Tests for multi-container (Step 0 + Step 3)

| Fixture | Assert |
| --- | --- |
| RAM modeled, room on CPU only | Replica skipped (no one-sided resize) |
| RAM modeled, room on both | Both allocs change together |
| 2 replicas, different servers, Up | Paired growth where room allows |
| 2 replicas, same tight server, Up | Behavior matches Q1 choice |
| Tie scores | Deterministic tie-break (recommend lower `container_id`) |

---

## Explicitly out of scope (do not sneak into a step)

- Reactive warm-up / embed / κ / MAPE
- Treating reactive as the algorithm to match (beyond importing `common/`)
- Moving packing into proactive instead of `common/`
- Spawn / terminate / BEV / BEH (beyond logging `need_horizontal`)
- Changing env apply order unless you pick Q2(b)

---

## Document history

| Date | Change |
| --- | --- |
| 2026-08-07 | Initial modular steps; ambiguities A–M |
| 2026-08-07 | Locked paired CPU/RAM; stop using reactive as baseline; remaining items reframed as direct questions Q1–Q8 |
