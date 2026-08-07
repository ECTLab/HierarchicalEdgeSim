# Plan: Proactive Decide + Apply (v1, no reactive dependency)

**Audience:** implementation kickoff  
**Status:** ready to code — decisions below are locked unless called out as open  
**Constraint:** scalers must stay **siblings** — neither imports the other’s package; shared vertical packing/snapshot live in `autoscaler/common/`  
**Scope:** (1) lift shared allocate primitives into `common/`, (2) proactive decide + allocate/apply for `proactive_auto_scaler`  
**Out of scope:** reactive policy algorithm (streaks/intent), MAPE/κ, BEV/BEH, spawn/terminate, predictor quality

**Decide formulas:** [rps-forecast-predict-and-decide.md](./rps-forecast-predict-and-decide.md) §4.1–4.4 and §4.6 (**ignore** §4.5 confidence / reactive mode entirely)  
**Forecast already done:** [proactive-auto-scaler-implementation.md](./proactive-auto-scaler-implementation.md) Steps 1–2  
**Build steps (modular):** [proactive-decide-and-apply-implementation-steps.md](./proactive-decide-and-apply-implementation-steps.md)  
**Structure guidance (optional):** [autoscaler-structure-naming-modularity-review.md](./autoscaler-structure-naming-modularity-review.md) §3 — sensing / decide / allocate split

---

## 0. One-sentence goal

When YAML selects `proactive_auto_scaler`, keep today’s sensing/forecast; while RPS history is short emit **no** scale actions; once history is full, on each TTW close run PredictAndDecide (§4.1–4.4), pack residuals via **shared** `common.distribute`, and let `env.apply_actions` apply them. Proactive never imports `reactive_vertical`; reactive never imports `proactive_auto_scaler`.

---

## 1. Locked design choices (v1)

| Topic | Lock |
| --- | --- |
| Scaler independence | **No cross-imports** between `reactive_vertical/` and `proactive_auto_scaler/`. Shared code → `autoscaler/common/` only. |
| Reactive policy | **Not used** by proactive. No embed, no warm-up handoff, no κ fallback, no nested `params.reactive`. |
| Pre-ready MS | If `not hist.is_full()` → sense/history only; **return no actions** for that MS. |
| Ready gate | **Per-MS** `hist.is_full()` (`len >= feature_window`). |
| Decision cadence | Proactive decide + allocate **only on TTW close**. Mid-TTW: accumulate `lambda_in` only. |
| Default `ttw_ticks` | **60** — one TTW = 60 simulator ticks (RPS sample + at most one decide per closed TTW). |
| Default `feature_window` | **10** — need 10 real TTW RPS samples before `hist.is_full()` / forecast / proactive decide. |
| Confidence / κ | Out of scope. |
| Sustained | Compute in `decide.py` (for later BEV/BEH); **allocate ignores it in v1**. |
| Packing | `common/distribute.py` — **paired** CPU+RAM grants when RAM is modeled (§2.4). |
| Snapshot | `common/snapshot.py` (`MsSnapshot`, `snapshot_ms`). `room_up_* = min(MS_max−alloc, server_free)` — **edge-server status enters here**. |
| Server capacity | Considered at snapshot + `Env.resize`; **not** inside decide. See §2. |
| Reactive as baseline | **No.** Shared code may live in `common/`; proactive policy/packing rules are chosen for the proposed method, not to match reactive. |
| Action types | Existing env types via `common/actions.py`; pass **reason string into** `distribute_*` (no post-hoc `replace` hack). |
| Env apply path | Unchanged (`apply_actions` sequential packing is the hard gate). |
| Cooldown | Proactive: TTW-based `next_allowed_ttw[ms] = t + C + 1` after **successful resize** (§2.7). `need_horizontal` alone does not arm. |

**Explicit divergence from design doc:** §2 cold-start / §4.5 say “stay reactive until ready.” v1 **holds** until history is full, then is always proactive.

---

## 2. Vertical scaling mechanics (read before coding allocate)

This section locks **how** a scale decision becomes container alloc changes. It matches what `Env.resize` / today’s reactive distribute already do. Proactive only changes **how δ is chosen** (PredictAndDecide); packing and apply stay the same substrate.

### 2.1 End-to-end pipeline (one MS, one decision tick/TTW)

```text
┌─────────────────────┐
│  DECIDE (policy)    │  MS-wide demand → signed δ_cpu, δ_ram
│  proactive: r★, θ   │  Does NOT look at per-server free capacity
│  reactive: deficit  │
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  SNAPSHOT (common)  │  Per replica: alloc, q, drop, slack,
│  snapshot_ms(...)   │  room_up = min(MS_max−alloc, server_free),
│                     │  room_down = alloc−MS_min
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  DISTRIBUTE (common)│  Pack |δ| onto replicas by score;
│  distribute_up/down │  never give more than that replica’s room_*;
│                     │  leftover Up → NeedHorizontalAction (log only)
└──────────┬──────────┘
           ▼
┌─────────────────────┐
│  ENV APPLY          │  apply_actions → resize one-by-one;
│  Env.resize         │  hard-reject if MS bounds or server caps violated
└─────────────────────┘
```

**Layers of responsibility:**

| Layer | Asks | Sees edge-server free? |
| --- | --- | --- |
| Decide | “How much more/less capacity does MS *m* want?” | **No** — fleet demand / util only |
| Snapshot + distribute | “Which replicas can absorb that δ, and by how much?” | **Yes** — baked into `room_up_*` |
| `Env.resize` | “Is this absolute alloc legal right now?” | **Yes** — final authority |

### 2.2 Yes — edge-server resource status is considered

For every container \(c\) on server \(s\):

```text
server_free_cpu(s) = s.cpu_cap_cores − Σ alloc_cpu of containers on s
server_free_ram(s)  = s.ram_cap_mb   − Σ alloc_ram of containers on s

room_up_cpu(c)  = min( spec.cpu_max_cores − c.cpu_alloc , server_free_cpu(s) )
room_up_ram(c)  = min( spec.ram_max_mb    − c.ram_alloc , server_free_ram(s) )
room_down_cpu(c)= max(0, c.cpu_alloc − spec.cpu_min_cores)
room_down_ram(c)= max(0, c.ram_alloc − spec.ram_min_mb)
```

Implementation today: `Env.get_server_free(server_id)` → (`server_free_cpu_cores`, `server_free_ram_mb`) in `env/world.py`. Snapshot must call this (or equivalent) when building each `ReplicaView`.

**Up is dual-bounded:** a replica cannot grow past its MS max **or** past what its host still has free (after other containers’ current allocs).

**Down does not need server free:** shrinking only releases capacity back to the server; `room_down` is MS-min bounded only.

**Other containers on the same server matter:** free capacity is whatever is left after *all* co-located containers (any MS). Growing one replica can starve another on the same host until the next snapshot.

### 2.3 What decide ignores vs what allocate enforces

| Quantity | Decide (proactive) | Allocate / resize |
| --- | --- | --- |
| `r_t`, `r_hat`, θ, `A_m`, ρ | Used | Not re-decided |
| Per-server free / `room_up` | **Ignored** | **Enforced** |
| MS min/max | Not needed for δ sign/magnitude | Enforced via room + `Env.resize` |
| Which replica grows | N/A | Grow score (drop, util, room) |
| Horizontal spawn | Out of scope | `NeedHorizontalAction` logged only |

So a large proactive Up residual is correct even if hosts are full: distribute grants what fits; remainder becomes `need_horizontal` for later BEV/BEH. Do **not** shrink δ in decide based on Σ `room_up` (that would hide unmet demand).

### 2.4 Distribute behavior (shared, both scalers)

**Up (`distribute_up`):**

1. Rank replicas by grow score (see open question on score inputs in the steps doc). Tie-break: lower `container_id`.
2. Walk rank order; for each replica apply the **paired** grant rule below; never exceed that replica’s `room_*`.
3. Emit absolute-target `ResizeAction` (`new_alloc = old + give`).
4. If leftover δ > EPS → append `NeedHorizontalAction` with residual cores/MB (no spawn in v1).

**Down (`distribute_down`):**

1. Rank by shrink score. Tie-break: lower `container_id`.
2. Skip replicas that are still “busy” if that gate is enabled (`slack` / `drop` — see open questions).
3. Take a **paired** shrink (both dims when RAM is modeled); never below MS min.
4. Consolidate-vs-spread shrink policy is an open product choice (steps doc).

**CPU/RAM pairing (modeling lock):** a request consumes **both** `cpu_per_request_cores` and `ram_per_request_mb`. Vertical scale keeps μ coherent:

- When both residuals are nonzero and both dims have room → move **both**.
- When both residuals are nonzero but one dim is **at its bound** (MS min/max or no server free) → allow the other dim alone (otherwise Down would get stuck at `ram_min`).
- When only one residual is nonzero → move that dim only.
- When `ram_per_request_mb ≤ ε` → CPU-only vertical.
- Unmet Up demand after packing → `need_horizontal`.

This is a **proposed-method** lock for `common/distribute`, not “whatever reactive did historically.”

**`env` argument:** packing uses **precomputed** `ReplicaView.room_*`; it does not re-query free capacity mid-loop. Snapshot freshness is the planner’s view for that tick.

### 2.5 Env apply — hard gate + sequential packing

`Env.apply_actions` (unchanged):

1. Sort actions by `(type, ms_id, container_id)` for determinism.
2. `need_horizontal` → log only (`result_code=LOGGED`); not a mutation; **does not** appear in resize `results` list.
3. At most one resize per `container_id` per batch (`DUPLICATE_IN_BATCH` otherwise).
4. Each resize calls `Env.resize`, which rejects with:
   - `BELOW_MS_MIN` / `ABOVE_MS_MAX`
   - `SERVER_CPU_EXCEEDED` / `SERVER_RAM_EXCEEDED` (live caps vs other containers’ **current** allocs)
   - `NO_CHANGE` / `UNKNOWN_CONTAINER`
5. **Sequential packing:** after a successful resize, that container’s new alloc is live, so the next resize on the **same server** sees reduced free capacity. This is the second defense if the planner’s snapshot was stale across siblings.

### 2.6 Same-server siblings — planner free accounting

Within one `distribute_up` call, two replicas on the **same** server can each see the **same** snapshotted `server_free` in their `room_up`, so naive packing can over-propose.

**Not inherited from reactive.** Choose explicitly (see steps doc open questions): either (a) decrement a per-server remaining-free map while packing, or (b) keep snapshot rooms and rely on `Env.resize` rejects. Until decided, implementers must not assume either.

### 2.7 Cooldown vs success vs partial apply

Proactive (and reactive today) arm cooldown when **`any(result.ok)`** for the pending MS set after `apply_actions`.

| Outcome | Cooldown? | Notes |
| --- | --- | --- |
| ≥1 resize `ok` | **Yes** | Even if another resize for same MS was rejected |
| All resizes rejected | **No** | Can retry next eligible TTW |
| Only `need_horizontal` (no resize) | **No** | Nothing in `results` with `ok`; do not arm |
| Decide NONE / empty allocate | **No** | No pending MS |

**Lock:** only add `ms_id` to `_pending_proactive_ttw` when at least one **resize** action was emitted for that MS (same spirit as reactive). `need_horizontal` alone must not arm cooldown.

### 2.8 Absolute targets, not deltas, on the wire

`ResizeAction` carries **absolute** `cpu_alloc_cores` / `ram_alloc_mb`. Decide/allocate think in residuals; distribute converts to absolute targets from the snapshot’s current alloc. `Env.resize` never adds a delta itself.

### 2.9 Single-replica vs multi-replica MS

| Topology | Behavior |
| --- | --- |
| One container | All of δ that fits `room_*` goes there; leftover → `need_horizontal` |
| Many containers, possibly different servers | Hot/high-room replicas preferred; free hosts absorb more Up |
| Zero containers | No `ReplicaView`s → distribute returns `[]`; decide may still compute positive δ but allocate is a no-op until spawn exists (out of scope) |

### 2.10 What proactive implementers must not reinvent

- Do not re-check server caps inside `decide.py`.
- Do not call `Env.resize` from the scaler — return actions; env applies.
- Do not implement spawn when `need_horizontal` fires.
- Do not bypass `room_up = min(MS_max−alloc, server_free)` in snapshot — that *is* how server status enters scaling.

---

## 3. Why `common/` must grow (coupling we refuse)

Without a shared layer, proactive allocate would need either:

| Bad option | Why it fails independence |
| --- | --- |
| `from ...reactive_vertical.distribute import ...` | Proactive depends on reactive package internals / naming |
| Copy `distribute_*` + `_aggregate_ms` into proactive | Divergent packing bugs; two sources of truth |
| Type allocate params as `ReactiveVerticalParams` | Proactive YAML/params coupled to reactive’s full knob set (streaks, `alpha_*`, …) |

So v1 **does** move the vertical-packing substrate into `common/`, and allows a **thin reactive rewire** (import path + typed snapshot) with **no behavior change**.

---

## 4. Target `common/` surface

`common/` already has: `actions.py`, `load.py`, `params_base.py`, `supported.py`.

### 4.1 Add — shared vertical allocate substrate

```text
autoscaler/common/
  actions.py          # exists — re-export ResizeAction / NeedHorizontalAction / …
  snapshot.py         # NEW
  distribute.py       # NEW (moved + generalized from reactive_vertical/distribute.py)
  distribute_params.py  # NEW (or fold into distribute.py — one module max if small)
```

#### `snapshot.py` — env → typed MS view

| Symbol | Role |
| --- | --- |
| `ReplicaView` | Per-container packing inputs (today in reactive `distribute.py`) |
| `MsSnapshot` | Typed fleet aggregate (replaces reactive `_aggregate_ms` `dict`) |
| `snapshot_ms(env, ms_id, tau) -> MsSnapshot` | Single env reader both scalers call |

`MsSnapshot` fields (locked shape; names may be spelled out as below):

| Field | Meaning |
| --- | --- |
| `ms_id`, `spec` | identity + `MicroserviceSpec` |
| `replicas: list[ReplicaView]` | sorted by `container_id` |
| `offered_total`, `served_total`, `dropped_total` | sum `lambda_in` / `served` / `dropped` this tick |
| `util_ratio`, `slack_ratio` | MS-level q / slack (reactive intent uses these) |
| `A_cpu`, `A_ram` | sum of replica allocs |
| `rho_cpu`, `rho_ram` | from spec (`cpu_per_request_cores`, `ram_per_request_mb`) |
| `tick_sec` | from `env.world_spec.sim.tick_sec` |
| `u_meas` | max container util in [0,1] (proactive Up safety) |
| `room_up_cpu/ram`, `room_down_cpu/ram` | fleet room totals (reactive intent clamps) |

Replica field sources (must match today’s reactive helper — **server free is required**):

| `ReplicaView` field | Source |
| --- | --- |
| `cpu_alloc` / `ram_alloc` | container alloc |
| `drop` | `history_at(tau).lambda_dropped` |
| `q` | max finite `q_cpu`/`q_ram` clamped to [0,1]; NaN/Inf → 1 |
| `slack` | `1 - q` |
| `room_up_cpu/ram` | `min(spec.max − alloc, env.get_server_free(host))` — **§2.2** |
| `room_down_cpu/ram` | `max(0, alloc − spec.min)` |

Snapshot tests for PR1 should include: container near MS max → `room_up` limited by MS; container with headroom but full host → `room_up ≈ 0` from server; after a successful shrink elsewhere on host → next snapshot shows more free.

#### `distribute.py` — packing only (no policy)

| Symbol | Role |
| --- | --- |
| `distribute_up(...)` | Rank hot-first; emit resizes + optional `NeedHorizontalAction` |
| `distribute_down(...)` | Rank cold-first; emit resizes |

**API change vs today (small, intentional):**

```text
distribute_up(..., params: DistributeParams, reason: str, ...)
distribute_down(..., params: DistributeParams, reason: str, ...)
```

- Reactive calls with `reason="reactive_up"` / `"reactive_down"`.
- Proactive calls with `reason="proactive_up"` / `"proactive_down"`.
- Removes `dataclasses.replace` reason remapping and keeps hardcoded `"reactive_*"` out of `common/`.

Still take non-negative delta magnitudes (callers convert signed residuals).

#### `DistributeParams` — packing knobs only

| Knob | Used by |
| --- | --- |
| `grow_weights` | `distribute_up` |
| `shrink_weights` | `distribute_down` |
| `eps_drop` | down eligibility |
| `theta_free` | down eligibility |
| `prefer_consolidate_down` | down loop |

`validate_distribute_params(raw: dict) -> DistributeParams` rejects unknown keys.

**Not in `DistributeParams`:** streaks, `cooldown_ticks`, `alpha_*`, `delta_*_min`, `up_mode`, `theta_high`, … — those stay on `ReactiveVerticalParams` only.

### 4.2 Do **not** put in `common/`

| Keep in scaler package | Why |
| --- | --- |
| Reactive streaks / intent / tick cooldown / `up_mode` sizing | Reactive-only policy |
| Proactive TTW RPS, history, forecast, predictors | Proactive-only sensing |
| Proactive `decide.py` (θ, `r★`, sustained) | Proactive-only math |
| Proactive TTW `next_allowed_ttw` cooldown | Different time base than reactive |
| Env `apply_actions` | Already env-owned; scalers only emit actions |

### 4.3 Dependency rule (checkable)

```text
env/  ◄──  autoscaler/common/  ◄──  reactive_vertical/
                           ▲
                           └──  proactive_auto_scaler/

FORBIDDEN:
  proactive_auto_scaler  →  reactive_vertical
  reactive_vertical      →  proactive_auto_scaler
  env                    →  autoscaler/*
```

Both strategy packages may import `common` and `env`. `common` may import `env` (types + read APIs for snapshot) but **never** a strategy package.

---

## 5. Reactive rewire (allowed, behavior-preserving)

Earlier drafts said “zero edits to `reactive_vertical/`.” That blocked independence. **Revised lock:**

| Allowed reactive edit | Not allowed |
| --- | --- |
| Delete local `distribute.py`; import from `common.distribute` | Change streak/intent formulas |
| Replace `_aggregate_ms` body with `snapshot_ms` + field reads | Change default numeric behavior |
| Pass `DistributeParams` + `reason="reactive_*"` into distribute | Add proactive imports |
| Keep flat YAML: `grow_weights` etc. still top-level reactive params; `validate_params` builds/embeds `DistributeParams` | Force users to nest `distribute:` under reactive (optional later) |

Existing reactive tests must stay green without assertion changes (except import paths if any test imported `reactive_vertical.distribute` directly — today they go through policy).

`reactive_vertical/distribute.py` becomes either **removed** or a **one-line re-export shim** from `common` for one release; prefer **remove + fix imports** to avoid two paths.

---

## 6. Target proactive loop

```text
each tick τ:
  sense_tick(env, τ)                    # accumulate λ_in into per-MS TTW totals

  if not is_ttw_close(τ, ttw_ticks):
      return []

  t = ttw_index(τ, ttw_ticks)
  actions = []

  for each ms_id:
      r_t = close_ttw_rps(...)          # append history; rps_forecast_log lead=0
      if not hist.is_full():
          continue                      # HOLD

      r_hat[1..H] = forecast_horizon(...)
      log forecast leads

      if t < next_allowed_ttw[ms]:
          continue

      snap = snapshot_ms(env, ms, τ)    # common
      decision = predict_and_decide(r_t, r_hat, snap.A_*, snap.rho_*, snap.tick_sec,
                                    snap.u_meas, θ_*, sustained_tau)

      if decision.direction is NONE:
          continue

      ms_actions = allocate_vertical(   # proactive glue: abs(δ) + common.distribute
          env, snap, τ, decision, distribute_params, reasons=proactive_*
      )
      if any resize in ms_actions:
          pending_proactive_ttw[ms] = t
      actions.extend(ms_actions)

  return actions

on_actions_applied(results):
  if any result.ok:
      for ms, t in pending_proactive_ttw.items():
          next_allowed_ttw[ms] = t + cooldown_C + 1
  pending.clear()
```

---

## 7. Decide math (pure — `proactive_auto_scaler/decide.py`)

Implement design-doc §4.1–4.4 only. No `Env`, no actions, no `common.distribute`. **No server-free inputs** (see plan §2.3).

### 7.1 Inputs / outputs

```text
in:
  r_t, r_hat[1..H]
  A_cpu, A_ram, rho_cpu, rho_ram, tick_sec, u_meas
  theta_up, theta_down, theta_target, sustained_tau, eps

out:
  direction: UP | DOWN | NONE
  delta_cpu, delta_ram   # signed
  sustained: bool
```

### 7.2 Utilization bridge (sim units lock)

`cpu_per_request_cores` = cores per request **per tick** (`env/usage.py`). Full-util throughput in **req/s**:

```text
C_full_cpu = (A_cpu / max(rho_cpu, eps)) / tick_sec
u_hat[h] / u_rps from r_hat[h] / r_t over C_full_*
u_obs = max(u_rps, u_meas)
```

Mirror RAM when `rho_ram > eps`.

### 7.3 Direction / sustained / residuals

- **UP** if `u_obs ≥ θ_up` or `max(u_hat) ≥ θ_up`
- **DOWN** if `u_obs ≤ θ_down` and `max(u_hat) ≤ θ_down`
- **NONE** otherwise
- Sustained (UP only): count of `u_hat[h] ≥ θ_up` ≥ `sustained_tau`
- `r_star = max(r_t, max(r_hat))`
- `A_req_cpu = rho_cpu * r_star * tick_sec / theta_target` → `delta = A_req - A` (clamp by direction)

Unit-test the bridge with a known `(A, ρ, tick_sec, r★, θ)` tuple.

```python
class Direction(str, Enum): ...
@dataclass(frozen=True, slots=True)
class DecideResult:
    direction: Direction
    delta_cpu: float
    delta_ram: float
    sustained: bool

def predict_and_decide(...) -> DecideResult: ...
```

---

## 8. Proactive allocate glue (`proactive_auto_scaler/allocate.py`)

Thin only — full mechanics in §2:

1. Take `MsSnapshot` (already includes per-replica `room_up_*` with **server free**) + signed `DecideResult`.
2. UP → pass positive deltas; DOWN → `abs(delta_*)`.
3. Call `common.distribute_up/down` with `DistributeParams` and `reason="proactive_*"`.
4. Do not re-snapshot; do not call `Env.resize`; do not filter δ by Σ `room_up` (unmet demand → `need_horizontal`).

No second snapshot implementation. No reactive imports.

---

## 9. Minimal file touch list

```text
autoscaler/common/
  snapshot.py           # NEW — ReplicaView, MsSnapshot, snapshot_ms
  distribute.py         # NEW — distribute_up/down (moved from reactive)
  distribute_params.py  # NEW — DistributeParams + validate (or merged into distribute.py)

autoscaler/reactive_vertical/
  distribute.py         # DELETE (or temporary re-export shim)
  policy.py             # CHANGE — import common.snapshot + common.distribute; pass reasons
  params.py             # CHANGE — build/embed DistributeParams from existing flat keys

autoscaler/proactive_auto_scaler/
  policy.py             # CHANGE — thin orchestration
  params.py             # CHANGE — theta_*, sustained_tau, cooldown_C; optional distribute nest
  sensing.py            # NEW — extract today’s on_tick_end body
  decide.py             # NEW — PredictAndDecide pure math
  allocate.py           # NEW — signed δ → common.distribute
  # unchanged: ttw_rps, history, forecast, predictors/*

env/                    # ZERO edits for apply path
```

| Artifact | Role |
| --- | --- |
| `common/snapshot.py` | Shared env read; one MS view for both strategies |
| `common/distribute*.py` | Shared vertical packing |
| `proactive/.../sensing.py` | TTW sense + forecast log |
| `proactive/.../decide.py` | Proactive-only math |
| `proactive/.../allocate.py` | Proactive-only glue to common distribute |
| `proactive/.../policy.py` | Orchestrator + TTW cooldown |

**Proactive dependency direction:**

```text
ttw_rps / history / forecast / predictors / decide  →  pure
sensing / allocate                                  →  Env + common
policy                                              →  orchestrates only
```

---

## 10. Sample shapes

### 10.1 Proactive params

```python
@dataclass(frozen=True, slots=True)
class ProactiveAutoScalerParams:
    ttw_ticks: int = 60
    feature_window: int = 10
    horizon_H: int = 3
    model_path: str | None = None
    scaler_path: str | None = None
    meta_path: str | None = None
    theta_up: float = 0.80
    theta_down: float = 0.30
    theta_target: float = 0.60
    sustained_tau: int = 2
    cooldown_C: int = 3
    distribute: DistributeParams = field(default_factory=DistributeParams)
```

Validate: `theta_up > theta_target > theta_down` in `(0, 1]`; `sustained_tau >= 1`; `cooldown_C >= 0`; `ttw_ticks >= 1`; `feature_window >= 1`; nest `distribute:` via `validate_distribute_params`.

**Default intuition:** with `tick_sec = 1`, `ttw_ticks = 60` → one RPS sample / decide opportunity per simulated minute; `feature_window = 10` → ~10 minutes of TTW history before proactive scaling starts (hold until then).

### 10.2 Reactive params (compatibility)

Keep **flat** YAML keys (`grow_weights`, …) on reactive configs. Internally:

```python
# conceptual
distribute = validate_distribute_params({
    "grow_weights": ..., "shrink_weights": ..., "eps_drop": ...,
    "theta_free": ..., "prefer_consolidate_down": ...,
})
# reactive-only fields remain on ReactiveVerticalParams
```

### 10.3 `on_tick_end` sketch (proactive)

```python
def on_tick_end(self, env: Env, tau: int) -> list[Any]:
    closed = self._sensing.on_tick(env, tau)
    if not closed:
        return []

    actions: list[Any] = []
    self._pending_proactive_ttw.clear()

    for rec in closed:
        if not rec.history_full or rec.r_hat is None:
            continue
        if self._in_cooldown(rec.ms_id, rec.ttw_t):
            continue

        snap = snapshot_ms(env, rec.ms_id, tau)
        d = predict_and_decide(
            r_t=rec.r_t, r_hat=rec.r_hat,
            A_cpu=snap.A_cpu, A_ram=snap.A_ram,
            rho_cpu=snap.rho_cpu, rho_ram=snap.rho_ram,
            tick_sec=snap.tick_sec, u_meas=snap.u_meas,
            theta_up=self.params.theta_up, ...
        )
        if d.direction is Direction.NONE:
            continue

        ms_actions = allocate_vertical(
            env, snap=snap, tau=tau, decision=d,
            params=self.params.distribute,
        )
        if any(getattr(a, "type", "") == "resize" for a in ms_actions):
            self._pending_proactive_ttw[rec.ms_id] = rec.ttw_t
        actions.extend(ms_actions)
    return actions
```

### 10.4 `on_actions_applied`

```python
def on_actions_applied(self, results: list[Any]) -> None:
    if any(getattr(r, "ok", False) for r in results):
        for ms_id, t in self._pending_proactive_ttw.items():
            self._next_allowed_ttw[ms_id] = t + self.params.cooldown_C + 1
    self._pending_proactive_ttw.clear()
```

---

## 11. YAML (proactive)

```yaml
autoscaler:
  name: proactive_auto_scaler
  decision_every_k_ticks: 1
  params:
    ttw_ticks: 60          # default; override only if demos need a shorter loop
    feature_window: 10     # default; W real TTW samples before decide
    horizon_H: 3

    theta_up: 0.80
    theta_down: 0.30
    theta_target: 0.60
    sustained_tau: 2
    cooldown_C: 3

    distribute: {}   # optional DistributeParams overrides
```

**Absent:** `kappa_*`, `mape_*`, `rps_floor`, `reactive:`, second `scaling_mode`.

**Demo note:** short smoke configs (e.g. 300-tick worlds) may override `ttw_ticks` / `feature_window` downward so warm-up and ≥1 decide fit in the horizon; production-like defaults remain **60 / 10**. Update `configs/demo_*_proactive*.yaml` in the last slice.

---

## 12. Logging

- Keep `rps_forecast.csv`.
- `actions.csv` reasons: `proactive_up` / `proactive_down` (reactive unchanged).
- Optional: `decision_log` list on proactive scaler; no new logging framework.

---

## 13. Build order

### Slice 0 — Lift shared substrate into `common/`

1. Add `common/snapshot.py`, `common/distribute.py` (+ `DistributeParams`) with **paired CPU/RAM** grant rule (§2.4).
2. Rewire `reactive_vertical` to import from `common/`; remove local `distribute.py`.
3. Reactive tests: update any that assumed one-sided CPU/RAM growth; streak/intent behavior otherwise unchanged.
4. Snapshot tests: MS-max vs server-full `room_up`; down room ignores server free; paired skip when only one dim has room.

### Slice 1 — Extract proactive sensing (behavior-preserving)

1. Move today’s `on_tick_end` body into `sensing.py`.
2. Policy still returns `[]`.
3. Forecast tests stay green.

### Slice 2 — `decide.py` + unit tests (no env)

- Direction / residuals / sustained / util-bridge unit cases (see prior list).

### Slice 3 — Proactive allocate + wire + cooldown

1. `allocate.py` → `common.distribute` with proactive reasons.
2. Extend proactive `params.py` (θ, `cooldown_C`, optional `distribute:`).
3. **Default change (locked):** `ttw_ticks=60`, `feature_window=10` (today’s code still defaults to 1 / 30 — update validator + any tests that assumed the old defaults).
4. Policy orchestration + TTW cooldown.
5. Integration: post-`feature_window` rising load → `proactive_*` actions + capacity change (use a short-horizon fixture that overrides TTW/W if needed).
6. Assert proactive package does not import `reactive_vertical` (small import-linter or grep test).

### Slice 4 — Demo YAML (+ optional decision buffer)

### Explicitly do not do

| Do not | Reason |
| --- | --- |
| `proactive` → `reactive_vertical` imports | Independence lock |
| Embed / call `ReactiveVerticalAutoscaler` | Out of scope |
| Duplicate `distribute_*` or snapshot inside proactive | Belongs in `common/` |
| Fork packing algorithm “for proactive” | One shared implementaton |
| Clamp decide δ by Σ `room_up` / server free | Hides unmet demand; allocate + `need_horizontal` handle it (§2.3) |
| Call `Env.resize` from the scaler | Env apply path only |
| Implement spawn on `need_horizontal` | Out of scope |
| κ / confidence / reactive fallback | Scope |
| New action types | Use `common.actions` / env |
| Use `sustained` in allocate | Deferred to BEV/BEH |
| Change reactive streak/intent math while lifting | Behavior-preserving rewire only |
| Fix same-server snapshot over-grant in v1 without asking | Open — see §17 |

---

## 14. Picture

```text
                    autoscaler/common/
                 ┌──── snapshot_ms ────┐  ← room_up includes server free
                 │  distribute_up/down │  ← clamps grants to room_*
                 │  DistributeParams   │
                 │  actions (re-export)│
                 └─────────┬───────────┘
            ┌──────────────┼──────────────┐
            ▼                             ▼
 reactive_vertical/              proactive_auto_scaler/
  policy (streaks/intent)         sensing → decide → allocate
  params (reactive + packing)     decide: demand only (no servers)
        │                         allocate: common.distribute
        └──────────► env.apply_actions / Env.resize ◄┘
                     (hard gate: MS bounds + live server caps)

(no arrows between the two strategy packages)
```

---

## 15. Acceptance

1. **Import graph:** `proactive_auto_scaler` does not import `reactive_vertical` (and vice versa). Both may import `common`.
2. Reactive demos/tests: same scaling behavior as before the lift (reasons still `reactive_*`).
3. Proactive: before `feature_window` TTWs → no scale actions; after full → TTW-close decisions; resize reasons `proactive_*`.
4. Shared packing/snapshot live only under `common/` (one implementation).
5. **Server-aware Up:** snapshot `room_up` respects `get_server_free`; a full host yields `room_up ≈ 0` even if below MS max; unmet δ → `need_horizontal` logged, not a crash.
6. **Env hard gate:** illegal alloc still rejected by `Env.resize` (`SERVER_*_EXCEEDED` / `ABOVE_MS_MAX`); scaler does not call `resize` directly.
7. No κ/confidence code; no `ReactiveVerticalAutoscaler` on the proactive path.
8. Post-ready rising load → resizes in `actions.csv` + next-tick capacity change.
9. Cooldown: after ≥1 successful resize, skip `cooldown_C` TTWs; `need_horizontal`-only does not arm; sensing/forecast continue.
10. Forecast tests updated only where “always `[]`” / “unknown `cooldown_C`” expectations intentionally change.

---

## 16. PR boundaries

| PR | Contents |
| --- | --- |
| **PR1** | Slice 0 — `common` snapshot + distribute; reactive rewire; **snapshot tests for server free / MS max room** |
| **PR2** | Slice 1 — proactive sensing extraction |
| **PR3** | Slice 2 — `decide.py` + pure tests |
| **PR4** | Slice 3 — allocate + policy wire + cooldown + independence test |
| **PR5** | Slice 4 — demo YAML (+ optional decision log) |

---

## 17. Open items — locked for first implementation round

| Topic | Lock |
| --- | --- |
| CPU/RAM pairing | Both dims move together when RAM modeled |
| Same-server Up | Decrement per-server free while packing |
| Apply vs score order | Accept env sort by `container_id` |
| Unmet Down | Silent drop |
| Down shape | Consolidate (`prefer_consolidate_down=True`) |
| `u_meas` | max over containers of `max(q_cpu, q_ram)` |
| Ranking | Up: drop, util, paired room; Down: slack, no-drop, paired room; skip busy |
| Cooldown | `any(result.ok)` |
| Multi-MS same host | No fairness |
| Defaults | `ttw_ticks=60`, `feature_window=10` |

Final demo target: **one container**, FIFA day80 **1-hour** trace, observe proactive up and down.
