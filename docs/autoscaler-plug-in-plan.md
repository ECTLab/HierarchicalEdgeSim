# Plan — Plug-in Autoscaler & Reactive Vertical Scaling (per microservice)

**Status:** planning only — ready for design lock (no code yet); v6 pre-coding review  
**Scope:** what to add to Part A so scaling actions work; an `autoscaler/` tree with **one separate folder per autoscaler**; a **supported list** so config picks one and passes its parameters; first concrete scaler = **reactive vertical** (per-MS aggregates).

Related: [autoscaler-implementation-steps.md](./autoscaler-implementation-steps.md) (build order + tests) · [implementation-plan.md](./implementation-plan.md) (§13) · [extension-plan-root-and-vicinity.md](./extension-plan-root-and-vicinity.md)

---

## 1. Goal

Run the tick engine **with or without** an autoscaler. When enabled:

1. After each tick τ, the **chosen** autoscaler observes the world (typically per microservice: aggregate stats across that MS’s containers).
2. It decides scaling intents and asks the env to apply them via write APIs (`resize` first; later `spawn` / `terminate`).
3. Changes take effect on **tick τ+1** (design lock L10).

This doc answers:

1. What is missing in the **current env** so autoscaling actions are actually doable?
2. How do **multiple autoscalers** live as **separate codebases** under one parent folder?
3. How does config **choose one** from a supported list and pass **that** scaler’s params (with a light standard)?
4. What does the first reactive vertical scaler look like? (algorithm + end-to-end example)

**Locked for this milestone**

| In | Out |
|---|---|
| Folder `autoscaler/` with **one subfolder per autoscaler codebase** | One shared “policy engine” that mixes algorithms |
| Explicit **supported autoscalers** list; config picks **one** name + params | Running two autoscalers in the same tick loop |
| Light **param standard** (common wrapper + per-scaler fields) | Env hard-coding any autoscaler |
| Env gains real **write APIs** + after-tick call site | Horizontal spawn/terminate in the first scaler (vertical only) |
| Part A still runs with autoscaler omitted / disabled | Forecast / BEVi / BEG in this milestone |

---

## 2. Readiness analysis (current code)

### 2.1 What already works (sensing + physics)

| Asset | Where | Why it matters |
|---|---|---|
| MS → containers | `Microservice.container_ids` | Aggregation unit for per-MS policies |
| Per-container history | `ContainerTickRecord` (`lambda_dropped`, `q_cpu`, …) | Inputs for decisions |
| Per-MS traces | `TraceStore` | Offered load Λ |
| Routing / μ from alloc | `routing`, `usage` | After `resize`, next tick behaves correctly automatically |
| MS min/max, server free | specs + `get_server_free` | Bounds for vertical actions |
| Env read APIs | `Env` | Scalers can observe without touching the engine |
| Write API **stubs** | `spawn` / `resize` / `terminate` | Names exist but **raise NotImplementedError** |

### 2.2 What blocks autoscaling actions today

| Gap | Today | Needed |
|---|---|---|
| Live `resize` | Stub | Mutate `cpu_alloc_cores` / `ram_alloc_mb` with MS clamp + server packing |
| Live `spawn` / `terminate` | Stub | Not required for first vertical scaler; keep stubs until a scaler needs them |
| After-tick call site | None | Once per τ, after all MS physics, call the selected autoscaler |
| Action / decision log | Only load CSVs | Optional `actions.csv` (who resized what, accept/reject) |
| Autoscaler package | Missing | Separate folders + config selection |

**Verdict:** the env can **measure** overload; it cannot yet **change** capacity or invite a policy each tick. Those two env pieces are the main additions. Autoscaler algorithms stay outside `env/`.

### 2.3 Scorecard

```text
Signals / history / routing / μ     ██████████  ready
Read APIs                           ██████████  ready
resize (real)                       ██░░░░░░░░  stub only
spawn / terminate                   ░░░░░░░░░░  deferred
After-tick call site                ░░░░░░░░░░  missing
autoscaler/ folders + selection     ░░░░░░░░░░  missing
```

---

## 3. What to add to the **current** codebase (env)

These are the only env changes required so **any** autoscaler can perform vertical scaling. No algorithm code belongs here.

### 3.1 Must add

| Addition | Module | Behavior |
|---|---|---|
| **`Env.resize(...)`** | `env/api.py` (+ helpers) | Set new alloc for a container; clamp to MS `min`/`max`; reject if server free capacity exceeded; return success/reject (do not crash the run) |
| **After-tick call** | `env/engine.py`, `Env.run` / `_run_partial` | After tick τ physics + histories are complete: if an autoscaler object was provided, call it |
| **`apply_actions(list)`** | `env/api.py` | Sort + dispatch one-by-one; sequential packing (§8.3) |
| **`ResizeResult` / reject codes** | `env/api.py` | e.g. `OK`, `ABOVE_MS_MAX`, `SERVER_CPU_EXCEEDED`, `NO_CHANGE`, … |
| **Action log + meta** | `env/metrics_log.py` | Buffer during run; flush `actions.csv`; record scaler in `run_meta`; fix initial/final alloc in container meta (§8.7) |

### 3.2 Timing (why the call site matters)

```text
TODAY (Part A only)
  for τ:
      for each MS: route → serve/drop → append history
      (end)

WITH AUTOSCALER SUPPORT
  for τ:
      for each MS: route → serve/drop → append history
      if autoscaler attached:
          actions ← autoscaler.on_tick_end(env, τ)
          for each action: env.resize(...)     # effective at τ+1
```

The call itself is small. **`resize` correctness** (clamps + packing) is the substantive env work.

### 3.3 Leave as stubs (for now)

| API | When to implement |
|---|---|
| `spawn` | When some supported autoscaler needs horizontal scale-out |
| `terminate` | When some supported autoscaler needs scale-in of replicas |

First scaler (reactive vertical) only needs **`resize`**.

### 3.4 Do **not** put in env

- Streak counters, thresholds, “which replica to grow”
- Parsing of autoscaler-specific params
- Imports of `autoscaler/reactive_vertical/...`

Env only knows: optional object with `on_tick_end`, plus write APIs.

---

## 4. Multiple autoscalers — separate folders, one chosen in config

### 4.1 Layout (your model)

One parent folder; **one subfolder = one autoscaler codebase** (kept separate even if ideas look similar).

```text
src/hierarchical_edge_sim/
  env/                         # Part A (+ resize + after-tick call)
  autoscaler/
    __init__.py
    common/                    # thin shared standards only (optional but useful)
      protocol.py              # “what every autoscaler must implement”
      actions.py               # ResizeAction, … (requests to env)
      params_base.py           # standard wrapper fields (see §4.3)
      supported.py             # SUPPORTED = ["reactive_vertical", ...]
      load.py                  # given name + params → build that scaler
    reactive_vertical/         # FIRST autoscaler — own codebase
      __init__.py
      policy.py
      params.py                # this scaler’s parameters + validation
      distribute.py
    # later, equally separate:
    # other_scaler_name/
    #   policy.py
    #   params.py
    #   ...
```

**Independence**

- Adding `other_scaler_name/` does not modify `reactive_vertical/` files.
- Scalers do not import each other’s decision logic.
- `common/` holds only the contract + the supported list + loader — not blended algorithms.

Dependency direction:

```text
autoscaler/<name>/  →  env
autoscaler/common/  →  env (types only) / scaler folders (loader)
env                 ✗→  autoscaler   (forbidden)
```

### 4.2 Supported list + config selection

Maintain an explicit list of supported autoscaler **names** (folder names):

```text
SUPPORTED_AUTOSCALERS = [
  "reactive_vertical",
  # "threshold_vertical",   # example future entry
]
```

Config chooses **one** name and provides **that** scaler’s parameters:

```yaml
autoscaler:
  enabled: true
  name: reactive_vertical      # must be in the supported list
  params:
    # fields defined by reactive_vertical/params.py only
    x_up_streak: 3
    y_down_streak: 5
    theta_free: 0.40
    ...
```

```text
if autoscaler omitted or enabled: false → run Part A (no scaler)
else if name not in SUPPORTED_AUTOSCALERS → error
else → validate params with that scaler’s schema → build instance → attach to Env.run
```

### 4.3 Standard for providing params (light)

Keep a **common wrapper**; leave algorithm fields to each scaler.

| Field | Required? | Meaning |
|---|---|---|
| `enabled` | yes (or omit whole block) | Master switch |
| `name` | yes if enabled | Must match a supported autoscaler folder / list entry |
| `params` | yes if enabled (may be `{}`) | Mapping validated by **that** autoscaler only |

Optional shared wrappers (all scalers may ignore):

| Field | Meaning |
|---|---|
| `decision_every_k_ticks` | Call decide every k ticks (default 1) |

**Per-scaler standard inside `params`:** each folder defines its own documented fields (types, defaults, ranges). The loader does not invent a universal param schema for all algorithms — only the wrapper above is universal.

Example: another scaler later might use completely different params:

```yaml
autoscaler:
  enabled: true
  name: threshold_vertical
  params:
    cpu_util_high: 0.85
    cpu_util_low: 0.30
    window: 10
```

Same wrapper (`enabled` / `name` / `params`); different folder; different `params` meaning.

### 4.4 Control loop (env + whichever scaler was selected)

```text
for τ in 1..N:
    # 1) Part A physics (unchanged)
    for ms in sorted(microservices by id):
        route → apply_tick → history

    # 2) Selected autoscaler (if any)
    actions ← selected.on_tick_end(env, τ)

    # 3) Env applies actions (resize for vertical)
    apply via Env.resize; log results
```

---


## 5. Actions: propose a list, then apply one by one

Yes — your reading is correct.

```text
1) Autoscaler observes env at end of tick τ
2) Autoscaler returns a list of actions   (proposals only — world not changed yet)
3) Env/runner applies that list in order, one action at a time
4) Each apply calls the matching write API (resize / later spawn / terminate)
5) Next tick τ+1 sees the updated world
```

The autoscaler **does not** mutate allocs itself. It only emits structured requests. The env is the single place that changes state (and can reject an illegal request).

### 5.1 Apply loop (conceptual)

```text
actions = autoscaler.on_tick_end(env, tau)   # list, maybe empty

# deterministic order before apply (recommended):
actions = sort(actions, key=(type, ms_id, container_id))

for action in actions:
    result = env.apply(action)   # or dispatch on action.type
    log(tau, action, result)
```

`apply` for vertical scaling is just:

```text
if action.type == "resize":
    result = env.resize(
        container_id=action.container_id,
        cpu_alloc_cores=action.cpu_alloc_cores,   # target absolute alloc
        ram_alloc_mb=action.ram_alloc_mb,
    )
```

If one action is rejected (e.g. server full), later actions in the same list still run unless we document a stop-on-first-failure rule. **Recommendation:** continue the list; log each reject (partial success is OK).

### 5.2 Common action shape (standard)

Every action is a small record with a **type** plus type-specific fields. Shared envelope:

| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | string | yes | `"resize"` now; later `"spawn"` / `"terminate"` |
| `ms_id` | string | yes | Microservice this decision belongs to (audit + ordering) |
| `reason` | string | recommended | Short why (e.g. `up_streak`, `down_slack`) — for logs only |
| `tau` | int | optional | Tick when proposed (usually current τ) |

Autoscaler returns `list[Action]`. Empty list = HOLD (do nothing this tick).

### 5.3 `resize` action (needed for first scaler)

**Meaning:** set this container’s allocation to the given **absolute** targets (not deltas). Absolute targets avoid ambiguity when several actions touch related state.

| Field | Type | Required | Meaning |
|---|---|---|---|
| `type` | `"resize"` | yes | Discriminator |
| `ms_id` | string | yes | Owning microservice |
| `container_id` | string | yes | Which replica to change |
| `cpu_alloc_cores` | float \| null | at least one of cpu/ram | New absolute CPU alloc |
| `ram_alloc_mb` | float \| null | at least one of cpu/ram | New absolute RAM alloc |
| `reason` | string | recommended | e.g. `reactive_up` / `reactive_down` |

**Example — one scale-up touching two containers** (two actions in one list):

```text
[
  {
    type: "resize",
    ms_id: "api",
    container_id: "c-api-1",
    cpu_alloc_cores: 1.25,
    ram_alloc_mb: 640,
    reason: "reactive_up"
  },
  {
    type: "resize",
    ms_id: "api",
    container_id: "c-api-2",
    cpu_alloc_cores: 1.10,
    ram_alloc_mb: 560,
    reason: "reactive_up"
  }
]
```

Env then:

```text
apply action[0] → resize c-api-1 → OK or REJECT
apply action[1] → resize c-api-2 → OK or REJECT
```

**Example — hold**

```text
[]    # no actions
```

### 5.4 Future action types (same list mechanism)

Not required for the first vertical scaler; same propose-then-apply pattern:

| `type` | Main fields | Env API |
|---|---|---|
| `spawn` | `ms_id`, `server_id`, initial `cpu_alloc_cores` / `ram_alloc_mb`, optional `container_id` | `env.spawn(...)` |
| `terminate` | `ms_id`, `container_id` | `env.terminate(...)` |

One tick’s list may eventually mix types (e.g. resize then spawn). Apply order should be documented (e.g. terminates → resizes → spawns, or stable sort by type then id). For vertical-only v1, only `resize` appears.

### 5.5 What an action is *not*

| Not an action | Lives where |
|---|---|
| MS-level intent `UP`/`DOWN`/`HOLD` | Internal to the autoscaler; may be logged, but env only sees concrete actions |
| Direct mutation of `container.cpu_alloc_cores` | Forbidden in autoscaler code |
| Trace / history edits | Forbidden |

### 5.6 Apply result (env → log)

Each one-by-one apply returns a result for logging:

| Field | Meaning |
|---|---|
| `ok` | bool |
| `code` | `OK` / `ABOVE_MS_MAX` / `SERVER_CPU_EXCEEDED` / … |
| `container_id` | echo |
| `cpu_alloc_cores` / `ram_alloc_mb` | values after attempt (old if rejected) |

---
## 6. Algorithm — first scaler: reactive vertical (per microservice)

### 6.1 Design principle

| Layer | Responsibility |
|---|---|
| **Decide** | Once per **microservice** per tick (or every k ticks) |
| **Sense** | **Aggregate** request stats over that MS’s containers |
| **Act** | Emit vertical `resize` on one or more replicas (**smart distribution**) |
| **Not in v1** | Spawn new replicas, terminate, cross-MS or vicinity moves |

So: **one brain per MS**, **many arms (containers)** for vertical actuation.

### 6.2 User intent → refined rules

Raw intent:

- **X** consecutive ticks with (aggregate) request **drops** → scale **up**
- **Y** consecutive ticks with **free** resources above a percentage → scale **down**

Refined: hysteretic streaks + cooldown at **MS** level; slack measured on **MS-wide** serving headroom, not a single noisy replica.

### 6.3 Per-MS observation (aggregate from containers)

For microservice `m` at tick τ, let `C_m` be its live containers. For each `c ∈ C_m`, read `r_c = c.history_at(τ)`.

| Symbol | Definition | Notes |
|---|---|---|
| `Λ_τ` | `Σ_c r_c.lambda_in` | Should match offered MS load (routing partitions Λ) |
| `S_τ` | `Σ_c r_c.lambda_served` | Aggregate served |
| `D_τ` | `Σ_c r_c.lambda_dropped` | **Primary scale-up signal** |
| `drop_ratio_τ` | `D_τ / max(Λ_τ, ε)` | Optional normalized pressure |
| `μ_tot` | `Σ_c serving_capacity(c, spec)` | Optional; can recompute from allocs |
| `q_ms,τ` | capacity-weighted util, see below | Better than naive mean of `q_c` |
| `slack_ms,τ` | `1 − q_ms,τ` | **Primary scale-down signal** |

**Recommended MS utilization (smart, not naïve avg):**

Serving headroom on container `c`:

```text
h_cpu,c = max(0, cpu_alloc_c − cpu_min)
h_ram,c = max(0, ram_alloc_c − ram_min)
```

Demand used this tick (already implied by served load):

```text
used_cpu,c = r_c.lambda_served * cpu_per_request
used_ram,c = r_c.lambda_served * ram_per_request
```

Then:

```text
q_cpu,ms = (Σ used_cpu,c) / max(Σ h_cpu,c, ε)
q_ram,ms = (Σ used_ram,c) / max(Σ h_ram,c, ε)   # skip if ram_per_request ≈ 0
q_ms,τ   = max(q_cpu,ms, q_ram,ms) clipped to [0, 1]
slack_ms,τ = 1 − q_ms,τ
```

This matches the physics: routing already weights by CPU headroom; MS slack answers “how much of the **fleet’s** serving headroom was unused?”

Fallback if you want simpler v1: `q_ms = max_c q_c` (pessimistic) or `mean_c q_c` (noisier). Prefer the weighted form above.

**Also track per replica (for distribution only, not for fire/no-fire):**

| Per-container | Use |
|---|---|
| `D_c`, `q_c`, `slack_c` | Who is hot / cold |
| `room_up_c` | `min(ms_max − alloc, server_free on host)` |
| `room_down_c` | `alloc − ms_min` |

### 6.4 Pressure flags and streaks (**per MS**)

```text
U_τ = (D_τ > ε_drop)                                    # scale-up pressure
      or optional (q_ms,τ ≥ θ_high)

Dflag_τ = (D_τ ≤ ε_drop) and (slack_ms,τ ≥ θ_free)       # scale-down pressure
          and (some replica still above min + Δ_min)

if U_τ: Dflag_τ = false                                 # drops always win
```

State keyed by **`ms_id`** (not container id):

```text
u_streak[ms] ← u_streak+1 if U_τ else 0
d_streak[ms] ← d_streak+1 if Dflag_τ else 0
cooldown[ms] ← max(0, cooldown−1) each tick
```

Fire:

```text
intent = UP   if u_streak ≥ X and cooldown == 0 and Σ room_up_c > 0
intent = DOWN if d_streak ≥ Y and cooldown == 0 and Σ room_down_c > 0
intent = HOLD otherwise
```

On any **successful** vertical change for that MS: reset both streaks; `cooldown ← C`.

Recommend **Y > X** (e.g. X=3, Y=5) so scale-down is more conservative than scale-up.

### 6.5 MS intent → vertical magnitude

Compute a **target extra MS-wide serving budget**, then distribute to containers.

**Scale up — desired extra demand to absorb** (elegant default):

Use recent aggregate drop as the deficit (smoothed optional):

```text
deficit ≈ D_τ                         # or max(D_τ, α_up * Λ_τ)
# resources needed above current serving headroom:
need_cpu = deficit * cpu_per_request
need_ram = deficit * ram_per_request  # 0 if RAM unconstrained
```

Then ask for at least a minimum step and at most a fraction of current total alloc:

```text
Δ_cpu_ms = clamp(need_cpu, Δ_cpu_min, α_up * Σ cpu_alloc_c)
Δ_ram_ms = clamp(need_ram, Δ_ram_min, α_up * Σ ram_alloc_c)
```

Alternative simpler rule (also fine for v1): multiplicative on **each** selected replica without explicit deficit — but deficit-driven up is closer to “we were dropping requests.”

**Scale down — desired release:**

```text
Δ_cpu_ms = min( α_down * Σ cpu_alloc_c,  max(0, slack_ms − θ_free) * Σ h_cpu )
           floored by Δ_cpu_min if releasing at all
# analogous for RAM
```

Simpler v1: release `max(Δ_min, α_down * alloc)` per selected replica subject to min clamps.

### 6.6 Smart distribution across containers (vertical only)

Decision is per MS; **actuation** must choose **which replicas grow/shrink** and by how much. This is the “smart” part.

#### Scale **up** distribution

Goal: place extra CPU/RAM where it both **helps routing** and **fits on the host**.

1. Rank live containers by a **grow score** (higher = prefer first), deterministic tie-break by `container_id`:

   ```text
   grow_score_c =
       w1 * (D_c / max(D_τ, ε))          # who actually dropped
     + w2 * q_c                          # who is saturated
     + w3 * (room_up_c / max_room)       # who can physically grow
   ```

   Default weights: `w1=0.5`, `w2=0.3`, `w3=0.2`.  
   If all `D_c ≈ 0` but MS still fired on optional θ_high: rely on `q_c` and `room_up_c`.

2. Allocate `Δ_cpu_ms` / `Δ_ram_ms` in rank order:

   - Give container `c` up to `room_up_c` (MS max and **server free**).
   - Continue to next replica until the MS delta is exhausted or no room left.
   - If residual delta remains → emit a **separate** `NEED_HORIZONTAL` log line (no spawn in this milestone).

3. Emit one `ResizeAction` per container that receives a nonzero delta.

**Why not grow all replicas equally?** Equal growth wastes budget on cold replicas and may hit a tight server while a sibling on a freer server could absorb more. Preferring drop/hot + free room matches capacity-weighted routing (more headroom → more future share).

**Single-replica MS:** distribution is trivial — all delta goes to that container (subject to clamps).

#### Scale **down** distribution

Goal: reclaim resources from **slack** replicas without reintroducing drops.

1. Rank by **shrink score** (higher = shrink first):

   ```text
   shrink_score_c =
       w1 * slack_c
     + w2 * (1 − D_c_norm)               # avoid shrinking anyone who dropped recently
     + w3 * (room_down_c / …)
   ```

2. Only shrink containers with `slack_c ≥ θ_free` (or MS-level fire already implies fleet slack — still avoid shrinking the hottest replica first).
3. Never shrink below `cpu_min` / `ram_min`.
4. Prefer shrinking **one or few** cold replicas rather than nibbling every replica (keeps headroom concentrated for routing) — optional `prefer_consolidate: true`.

#### Invariants

- Every resize target ∈ `[cpu_min, cpu_max]` and `[ram_min, ram_max]` for that MS.  
- Sum of allocs on a server never exceeds caps (enforced by `Env.resize`).  
- CPU and RAM moved **together** by default so μ stays balanced; if `ram_per_request_mb == 0`, CPU-only vertical is allowed.  
- Action apply order: sort by `(ms_id, container_id)`.

### 6.7 Worked intuition (multi-replica)

MS `api` has containers `c1` (busy, dropping), `c2` (idle, large slack). Offered Λ high for 3 ticks → `D_τ > 0` streak hits X → **UP**.

- Deficit ≈ aggregate drops → `Δ_cpu_ms` computed.  
- Grow score ranks `c1` first → resize `c1` up until server/MS max; leftover may go to `c2` if still needed.  
- Next ticks: routing sends more share to `c1` (higher headroom); drops fall.

Later Λ low for 5 ticks, `slack_ms ≥ θ_free` → **DOWN**. Shrink score prefers `c2` → release from cold replica first; `c1` stays until still slack.

### 6.8 Config for this scaler only

When `name: reactive_vertical`, `params` look like:

```yaml
autoscaler:
  enabled: true
  name: reactive_vertical
  decision_every_k_ticks: 1
  params:
    x_up_streak: 3
    y_down_streak: 5
    cooldown_ticks: 3
    eps_drop: 1e-9
    theta_free: 0.40
    theta_high: 0.90
    use_near_saturation_up: false
    alpha_up: 0.25
    alpha_down: 0.15
    delta_cpu_min_cores: 0.25
    delta_ram_min_mb: 128
    up_mode: deficit
    prefer_consolidate_down: true
    grow_weights: { drop: 0.5, util: 0.3, room: 0.2 }
    shrink_weights: { slack: 0.5, no_drop: 0.3, room: 0.2 }
```

### 6.9 Scope (this scaler)

| Scope | Role |
|---|---|
| Per microservice | Decision + streaks + cooldown |
| Per container | Resize targets after smart distribution |
| Horizontal / vicinity | Not this scaler |

---

## 7. End-to-end example (how the pieces fit)

### 7.1 Setup

- World: one MS `api` with two containers `c-api-1`, `c-api-2` (as in a two-container demo).
- Config includes:

```yaml
autoscaler:
  enabled: true
  name: reactive_vertical
  params:
    x_up_streak: 3
    y_down_streak: 5
    theta_free: 0.40
    cooldown_ticks: 2
    alpha_up: 0.25
    ...
```

- Runner: load world → look up `reactive_vertical` in supported list → build policy from `params` → `Env.run(autoscaler=policy)`.

### 7.2 What was added vs today

| Step | Today | With plan implemented |
|---|---|---|
| Tick serve/drop | Yes | Same |
| After tick | Nothing | Call `reactive_vertical.on_tick_end` |
| Change alloc | Impossible (`resize` stub) | `Env.resize` updates alloc if legal |
| Next tick μ / routing | Static alloc | Uses new alloc automatically |

### 7.3 One spike, then idle (story)

```text
τ=1..2   load moderate, D_τ=0, slack high but d_streak not yet Y → HOLD
τ=3..5   load high, aggregate drops D_τ>0 each tick → u_streak hits 3 → UP
         policy asks: grow c-api-1 first (more drops), maybe c-api-2 if still needed
         Env.resize(c-api-1, cpu=…, ram=…) → OK (within MS max + server free)
τ=6..     μ higher → fewer drops
… later  load low, slack_ms ≥ 0.40 for 5 ticks → DOWN
         shrink colder replica first via resize toward min
```

Action log (illustrative):

```text
tau,ms_id,autoscaler,intent,container_id,cpu_old,cpu_new,result
5,api,reactive_vertical,UP,c-api-1,1.0,1.25,OK
12,api,reactive_vertical,DOWN,c-api-2,1.0,0.85,OK
```

### 7.4 Switching to another autoscaler later

Change **only** config (and have that folder implemented + listed as supported):

```yaml
autoscaler:
  enabled: true
  name: threshold_vertical
  params:
    cpu_util_high: 0.85
    window: 10
```

No edits to `reactive_vertical/` and no edits to env beyond the shared `resize` + after-tick call already in place.

### 7.5 Autoscaler off

```yaml
# no autoscaler: block
# or
autoscaler:
  enabled: false
```

Same as today’s Part A run.

---


## 8. Gaps filled before coding (review pass)

Items that were easy to miss; locked here so implementation does not invent them ad hoc.

### 8.1 Config wiring (same YAML, env stays clean)

Today `load_yaml` only reads `sim` / `topology` / `apps` / `traces_dir` and **silently ignores** an `autoscaler:` block. Keep that separation:

| Piece | Responsibility |
|---|---|
| `env.config.load_yaml` / `validate` | World only (unchanged semantics) |
| Runner or `autoscaler.common.load` | Re-read YAML (or accept a pre-parsed mapping) for the `autoscaler:` wrapper; validate `name` ∈ supported list; validate `params` with that scaler’s schema |
| `Env.run(autoscaler=...)` | Receives an **already built** object — does not parse YAML |

Recommended runner flow:

```text
spec = validate_or_raise(load_yaml(path))
env = Env.from_config(path)          # or build from spec
scaler = load_autoscaler_from_yaml(path)   # None if omitted/disabled
run_dir = env.run(autoscaler=scaler)
```

Do **not** require `env` to import scaler folders.

### 8.2 Who applies actions

**Env owns apply** (single place for packing rules + logging hooks):

```text
Env.run / run_ticks:
  tick physics
  if autoscaler:
      actions = autoscaler.on_tick_end(env, τ)
      env.apply_actions(actions)   # sorts, dispatches one-by-one, logs
```

`apply_actions` is the dispatcher (`resize` now; `spawn`/`terminate` later). Autoscalers never call `resize` themselves if we want one audit path — **recommendation:** allow either (a) scaler returns actions only, or (b) scaler may call `env.resize` directly. Prefer **(a)** only so every mutation goes through `apply_actions` and the action log stays complete.

### 8.3 Sequential packing inside one list

When applying several `resize` actions in one tick, **each successful resize updates free capacity** before the next action. Example: two containers on the same server — the second action must see the free CPU/RAM left after the first. Do not snapshot free capacity once at the start of the list.

### 8.4 Partial fields on `resize`

| Spec | Behavior |
|---|---|
| Both `cpu_alloc_cores` and `ram_alloc_mb` set | Set both |
| Only CPU set (`ram` null) | Keep current RAM |
| Only RAM set | Keep current CPU |
| Both null | Reject `NO_CHANGE` / invalid |
| New value within `EPS` of current | Result `NO_CHANGE` (not an error; no cooldown reset) |

### 8.5 Duplicate `container_id` in the same list

**Reject or coalesce.** Recommendation: **last write wins** after sort stability is defined is messy — prefer **validate in `apply_actions`**: if the same `container_id` appears twice in one batch, reject the later ones with `DUPLICATE_IN_BATCH` (or merge before apply inside the autoscaler). First scaler should emit at most one resize per container per tick.

### 8.6 Timing vs history (easy to confuse)

| Moment | Alloc recorded |
|---|---|
| During tick τ physics | Current alloc → `ContainerTickRecord.cpu_alloc_cores` for τ |
| After tick, `resize` applied | Live `container.cpu_alloc_cores` changes |
| Tick τ+1 physics | New alloc used for μ/routing; history for τ+1 stores the new alloc |

So history row τ reflects **serving** alloc for that tick, not the post-decision alloc. Action log is the place that records the change at end of τ.

### 8.7 Action log + run outputs

| Concern | Lock |
|---|---|
| Buffer | Env (or run context) appends in-memory rows during the run |
| Flush | `write_run_outputs` writes `actions.csv` at run root (alongside `run_meta.yaml`) |
| Empty run | File may be header-only if no actions |
| `run_meta.yaml` | Record `autoscaler: { enabled, name, params }` (or `null`) for reproducibility |
| Container `.meta.json` | Today writes `initial_*` from **current** alloc at flush time — after resizes that would be **final**, mislabeled. **Fix:** snapshot initial alloc at `build_world` / first attach, or write both `initial_*` and `final_*` |

Suggested `actions.csv` columns:

```text
tau,autoscaler_name,ms_id,action_type,container_id,reason,
cpu_old,cpu_new,ram_old,ram_new,result_code
```

### 8.8 Cooldown / streaks vs rejected actions

Reset streaks and start cooldown **only if at least one resize for that MS succeeded** in the batch. If all rejected → keep pressure streaks (so the scaler can retry next ticks). When vertical room is exhausted but demand remains, emit a **separate** `NEED_HORIZONTAL` log line (not only a resize `reason`).

### 8.9 `decision_every_k_ticks`

Lock:

- Update streaks / pressure flags **every** tick.
- Emit actions only when `τ % k == 0` (and cooldown allows).
- Default `k = 1`.

### 8.10 Determinism

- Iterate MS ids sorted; container ids sorted for distribution ties.
- Sort action list before apply (`type`, `ms_id`, `container_id`).
- No wall-clock in decisions; `sim.seed` unused by `reactive_vertical` (reserved for future stochastic scalers).
- Same config + traces → same actions.csv and histories.

### 8.11 Analysis / demos

| Item | Note |
|---|---|
| Demo config | Prefer multi-container MS (`demo_60_two_containers` + `autoscaler:` block) |
| Runner | `examples/run_with_autoscaler.py` (Part A runner stays scaler-free) |
| A/B | Compare total dropped requests and/or actions count with scaler on vs off |
| Plots | Optional later: overlay alloc vs λ from history; not required for M1–M3 |

### 8.12 Recommended build order (when coding starts)

1. `Env.resize` + packing tests (+ initial/final meta fix)  
2. `apply_actions` + after-tick hook + in-memory action log flush  
3. `autoscaler/common` (protocol, action types, supported list, YAML load)  
4. `reactive_vertical/` + unit tests  
5. Demo runner + integration test  
6. Docs how-to update  

### 8.13 Acceptance criteria (milestone done when)

- [ ] Part A suite still green with no `autoscaler:` block  
- [ ] `resize` rejects over-max and over-server; accepts legal change  
- [ ] With scaler attached, actions appear in `actions.csv`; histories remain consistent with §8.6  
- [ ] Unknown `name` / bad `params` fail before the tick loop  
- [ ] Multi-replica MS: aggregate drop → UP; slack → DOWN; one resize per container per tick  
- [ ] Two runs identical seed → identical logs  

### 8.14 Still explicitly out of scope (do not sneak in)

- Horizontal spawn/terminate implementation  
- Vicinity / BEG / loans  
- Two autoscalers in one run  
- Mid-tick resize (during MS loop)  
- Changing traces or replay mid-run  

---
## 9. Implementation milestones

### M0 — Design lock

- [ ] Accept: env adds `resize` + after-tick call; algorithms stay under `autoscaler/`
- [ ] Accept: one folder per autoscaler; supported **name** list; config `name` + `params`
- [ ] Accept: first scaler = per-MS reactive vertical only
- [ ] Accept: no spawn/terminate until a scaler needs them
- [ ] Accept: gaps in **§8** (history timing, sequential packing, config wiring, …)

### M1 — Env: make actions doable

| Work | Exit |
|---|---|
| Implement `Env.resize` (+ partial fields, EPS/`NO_CHANGE`) | Accept/reject tests |
| `apply_actions` + after-tick call | Histories complete before call; sequential free capacity |
| Action log buffer + `actions.csv` flush | Header-only OK if empty |
| `run_meta` autoscaler snapshot; fix initial/final container meta | Reproducible; meta not lying |

### M2 — Autoscaler tree + selection

| Work | Exit |
|---|---|
| `autoscaler/common` (protocol, actions, supported list, load) | Unknown `name` fails clearly |
| Param wrapper standard (`enabled`/`name`/`params`) | Documented |
| Empty/disabled path | Part A tests unchanged |

### M3 — First folder: `reactive_vertical/`

| Work | Exit |
|---|---|
| Own `params.py` + `policy.py` + distribute | Unit + multi-replica integration |
| Listed in `SUPPORTED_AUTOSCALERS` | Selectable from YAML |

### M4 — Runner + demo example

| Work | Exit |
|---|---|
| Example config + `run_with_autoscaler.py` | Matches §7 story |
| A/B drops with/without scaler | Documented |

---

## 10. API contracts (short)

### 10.1 Env (to implement)

```text
resize(container_id, cpu_alloc_cores=?, ram_alloc_mb=?) -> ResizeResult

run(..., autoscaler=None)
  # each τ after physics:
  #   actions = autoscaler.on_tick_end(env, τ)
  #   for action in actions: dispatch → resize/spawn/terminate
```

See **§5** for the action record format and one-by-one apply rule.

### 10.2 Every supported autoscaler folder

```text
# standard entrypoint
class ...:
    def on_tick_end(self, env, tau) -> list[Action]: ...

# that folder also defines:
validate_params(mapping) -> Params
build(params) -> autoscaler instance
```

For the first scaler, `Action` is only `resize` (fields in §5.3).

### 10.3 Policy may / must not

**May:** read APIs, histories, `get_ms_spec`, `get_server_free`; **return** action lists.  
**Must not:** mutate history, call `apply_tick`, mutate allocs directly, import other autoscaler folders’ logic.

---

## 11. Testing strategy

| Layer | Focus |
|---|---|
| `resize` | Clamps, packing |
| After-tick call | Invoked once per τ; skipped when None |
| `apply_actions` packing | Second resize on same server sees updated free capacity |
| History vs actions | Alloc in history_at(τ) equals pre-resize; action log has the change |
| Supported list / load | Bad name fails; wrong params for that scaler fail |
| `reactive_vertical` | Aggregate streaks; distribute hot-first / cold-first |
| Regression | Part A suite with autoscaler disabled |

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Env grows policy logic | Keep algorithms in per-scaler folders |
| Scalers copy-paste too much | Optional thin `common/` only; do not merge codebases |
| Ambiguous dual control | One `name` per run |
| Resize rejected mid-spike | Log `NEED_HORIZONTAL`; do not fake capacity; keep streaks if all rejected (§8.8) |
| Oscillation | Cooldown + Y > X in reactive_vertical |
| Meta lies about “initial” alloc | Snapshot initial at world build / write initial+final (§8.7) |
| Action log incomplete | Scalers return actions only; env `apply_actions` is sole mutator (§8.2) |

---

## 13. Summary

| Question | Answer |
|---|---|
| What must current code gain? | Real **`resize`**, **after-tick call**, optional action log |
| How do actions work? | Scaler returns a **list**; env applies **one by one** (§5) |
| How do multiple scalers live? | `autoscaler/<name>/` — **separate codebase per name** |
| How to choose? | Supported list + config `name` + `params` |
| Param standard? | Common wrapper; each folder owns its `params` schema |
| First algorithm? | Per-MS reactive vertical in its own folder |
| Part A alone? | Yes if block omitted / `enabled: false` |
| History vs resize? | History τ = pre-resize alloc; change in `actions.csv` (§8.6) |
| Config parse? | Env ignores `autoscaler:`; loader/runner builds scaler (§8.1) |

---

## 14. Review checklist

- [ ] Env additions limited to actuation + after-tick call — accepted  
- [ ] One folder per autoscaler; supported **name** list — accepted  
- [ ] Config: `enabled` / `name` / `params` (no blended “kind registry” API) — accepted  
- [ ] Per-MS reactive vertical as first scaler — accepted  
- [ ] Smart vertical distribute across MS containers — accepted  
- [ ] Example in §6 matches the intended workflow — accepted  

---

## 15. Document history

| Version | Change |
|---|---|
| v1 | Initial plug-in + reactive plan (per-container decide) |
| v2 | Per-MS decide; aggregate stats; smart vertical distribution |
| v3 | Multi-scaler via kind/registry wording |
| v4 | Reframe: separate folder per autoscaler; supported **name** list; clarify env additions; end-to-end example; drop “kind” framing |
| v5 | Explicit action format: propose list → apply one-by-one; resize fields; future spawn/terminate |
| v6 | Pre-coding review: config wiring, apply ownership, sequential packing, history timing, action log/meta, cooldown-on-success, acceptance criteria |
| v7 | Lock: `NEED_HORIZONTAL` = separate log line; align with implementation-steps v3 (`ResizeResultCode`) |
