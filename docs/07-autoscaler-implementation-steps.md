# Autoscaler Extension — Step-by-Step Implementation Guide

Hands-on build order for plugging autoscalers into Part A. Turns [06-autoscaler-plug-in-plan.md](./06-autoscaler-plug-in-plan.md) into concrete steps with **tests after every step** and a **final end-to-end scenario**.

**Status:** planning only — no coding until design lock  
**Spec authority:** [06-autoscaler-plug-in-plan.md](./06-autoscaler-plug-in-plan.md) (v6+) — if this guide and the plan disagree, the plan wins.  
**First scaler:** `reactive_vertical` (per-MS aggregates, vertical `resize` only)

---

## Review notes applied (v2)

A pre-coding review pass cross-checked this guide against the plan and the current `env/` code. Fixes folded into the steps below (see [Document history](#document-history) for the full log); highlights:

- **Action-type ownership** was undefined (plan puts `ResizeAction` under `autoscaler/common/`, but `env` must never import `autoscaler/`, and Step 2 needs *some* action shape before Step 3's package exists). Resolved: the canonical action type lives in `env/` (Step 2); `autoscaler/common/actions.py` (Step 3) re-exports/wraps it. See Step 2 §"Action type lives in `env`".
- **`state.current_tau` vs the after-tick hook**: the hook must fire *after* `state.current_tau` is advanced to τ, or `env.get_time()` / `history_at` reads inside `on_tick_end` would be stale. Added as an explicit build note + test in Step 2.
- **`decision_every_k_ticks`** had no threading story or test. Clarified: the hook fires every tick regardless of `k` (streaks must update every tick per plan §8.9); `k` only gates *emission* and is threaded to the scaler at construction time, not evaluated by `env`. Added a test in Step 4.
- **Cooldown-on-success** (`on_actions_applied`) was referenced in Step 4 but never added to the Step 3 protocol or exercised generically in Step 2. Added to both, plus a missing "all rejected → streaks persist" test.
- **Sequential packing** and **`DUPLICATE_IN_BATCH`** tests are only meaningful with two containers on the *same* server — `02-demo_60_two_containers.yaml` puts them on separate 8-core servers, so it cannot exercise either. Clarified that Step 2 needs a dedicated shared-server fixture, and added the missing `DUPLICATE_IN_BATCH` test.
- **Final scenario realism**: with both replicas on separate, mostly-idle 8-core servers, `SERVER_*` rejects are validated only at the Step 1/2 unit level, never in the demo/final scenario. Documented explicitly so a clean `actions.csv` isn't mistaken for a bug. Also flagged the run-id collision risk (same seed + same wall-clock second → same `run_id`) when comparing static vs. reactive runs back-to-back.
- Added missing tests: env-does-not-import-autoscaler check, config tolerates an unrecognized `autoscaler:` block, distribute tie-break determinism, `NEED_HORIZONTAL` logging decision.

---

## How to use this guide

```text
Implement step → run that step’s tests → gate green → next step
```

| Rule | Meaning |
|---|---|
| One step at a time | Do not start step *n+1* until step *n* tests pass |
| Part A stays green | After every step: full `pytest` still passes with autoscaler off |
| No policy in `env/` | Algorithms only under `autoscaler/<name>/` |
| No coding of spawn/terminate | Stubs remain until a later scaler needs them |

---

## Locked defaults (realistic params)

Use these unless a step’s test fixture needs a smaller toy value.

> **Note — deliberate deviation from the plan's illustrative numbers:** the plan's §6.8/§7.1 example params (`y_down_streak=5`, `cooldown_ticks=2–3`, `theta_free=0.40`, `alpha_up=0.25`, `alpha_down=0.15`) are illustrative, not locked. This guide locks a different concrete set below, sized against `02-demo_60_two_containers.yaml`'s actual clamps (`cpu_min=0.5`, `cpu_max=4.0`) and the 60-tick horizon. The plan remains authoritative on **mechanism** (streak/cooldown/distribution logic); this guide is authoritative on the **exact numbers** used in tests/demos. If the two are read side by side, don't treat the differing example numbers as a contradiction.

### World baseline (demo)

Prefer extending `configs/02-demo_60_two_containers.yaml` (two replicas, overload in the middle of the 60-tick trace):

| Setting | Value | Why realistic here |
|---|---|---|
| `tick_sec` | `1.0` | 1 tick ≈ 1 second |
| MS `cpu_min` / `cpu_max` | `0.5` / `4.0` | Room to grow from 1.0–2.0 alloc |
| `cpu_per_request_cores` | `0.01` | Matches existing demos |
| Initial allocs | `1.0` + `2.0` cores | Heterogeneous replicas; routing already uneven |
| Trace | `api_60_two.csv` | Peaks above total μ → real drops |

### Autoscaler wrapper

```yaml
autoscaler:
  enabled: true
  name: reactive_vertical
  decision_every_k_ticks: 1
  params:
    # … see below
```

### `reactive_vertical` params (recommended defaults)

| Param | Value | Rationale |
|---|---|---|
| `x_up_streak` | `3` | ~3s of sustained drops before scale-up (responsive, not 1-tick jitter) |
| `y_down_streak` | `8` | Scale-down slower than up (Y > X) to limit flapping |
| `cooldown_ticks` | `5` | Quiet period after a successful resize (~5s) |
| `eps_drop` | `1.0e-9` | Treat tiny float noise as no drop |
| `theta_free` | `0.35` | ≥35% unused MS serving headroom counts as “free” |
| `theta_high` | `0.90` | Reserved; unused when `use_near_saturation_up: false` |
| `use_near_saturation_up` | `false` | v1: scale up on **aggregate drops** only |
| `alpha_up` | `0.20` | Grow ~20% of current fleet alloc per UP (steady, not jump-to-max) |
| `alpha_down` | `0.10` | Shrink more gently than grow |
| `min_mu_step` | `25` | Smallest serving-μ step (req/tick). RAM follows `Δμ × ρ`; triangle `ρ_cpu=0.01` ⇒ `0.25` cores |
| `prefer_consolidate_down` | `true` | Prefer shrinking cold replicas first |
| `grow_weights` | `{drop: 0.5, util: 0.3, room: 0.2}` | Prefer hot + roomy hosts |
| `shrink_weights` | `{slack: 0.5, no_drop: 0.3, room: 0.2}` | Prefer cold replicas |

Plain-language “when / how big / which replica”: [08-reactive-local-params.md](./08-reactive-local-params.md).

Full YAML snippet for demos/tests:

```yaml
autoscaler:
  enabled: true
  name: reactive_vertical
  decision_every_k_ticks: 1
  params:
    x_up_streak: 3
    y_down_streak: 8
    cooldown_ticks: 5
    eps_drop: 1.0e-9
    theta_free: 0.35
    theta_high: 0.90
    use_near_saturation_up: false
    alpha_up: 0.20
    alpha_down: 0.10
    min_mu_step: 25
    prefer_consolidate_down: true
    grow_weights: { drop: 0.5, util: 0.3, room: 0.2 }
    shrink_weights: { slack: 0.5, no_drop: 0.3, room: 0.2 }
```

Toy tests may use smaller X/Y/cooldown (e.g. X=2, Y=3, C=1) — call that out in the test name.

---

## Step 0 — Design lock (no code)

**Goal:** Agree the plan + this guide before writing code.

### Build

None. Read [06-autoscaler-plug-in-plan.md](./06-autoscaler-plug-in-plan.md) §§3–8 and this defaults table.

### Tests

None (human review).

### Gate

- [ ] Per-MS decide + vertical only — accepted  
- [ ] One folder per autoscaler; config `name` + `params` — accepted  
- [ ] Propose actions → `apply_actions` one-by-one; effect at τ+1 — accepted  
- [ ] Realistic params above — accepted (or note edits here)  
- [ ] Action type (`ResizeAction`) is defined in `env/`, not `autoscaler/common/`, so Step 2 doesn't need the autoscaler package to exist — accepted (see Step 2)  
- [ ] After-tick hook fires **after** `state.current_tau` is advanced to τ — accepted (see Step 2)  
- [ ] `decision_every_k_ticks` gates action **emission** only, inside the scaler; `env` always calls the hook every tick — accepted (see Step 3/4)  
- [ ] `on_actions_applied(results)` is part of the autoscaler protocol (optional method), called by `env` right after `apply_actions` — accepted (see Step 2/3/4)  
- [ ] `SERVER_*` packing rejects are exercised only at Step 1/2 unit level (dedicated shared-server fixture), not in the demo/final scenario — accepted

---

## Step 1 — `Env.resize` (actuation only)

**Goal:** Live vertical changes with MS clamps + server packing. No autoscaler yet.

### Build

1. Implement `Env.resize(container_id, cpu_alloc_cores=None, ram_alloc_mb=None) -> ResizeResult`.
2. Rules: MS min/max; server free capacity (other containers’ allocs); partial fields (null = leave unchanged); `EPS` → `NO_CHANGE`.
3. Add a new `ResizeResultCode` enum (do **not** overload the existing `RejectReason`, which today has a single Part-A-stub value and reads oddly with a non-reject `OK` member): `OK`, `UNKNOWN_CONTAINER`, `BELOW_MS_MIN`, `ABOVE_MS_MAX`, `SERVER_CPU_EXCEEDED`, `SERVER_RAM_EXCEEDED`, `NO_CHANGE`. `DUPLICATE_IN_BATCH` is added in Step 2 to the same enum.
4. Snapshot **initial** alloc at world build (or on first meta write) so later flush can write `initial_*` and `final_*` correctly (`env/metrics_log.py::_write_container_meta` currently reads `container.cpu_alloc_cores` at flush time, i.e. *after* any resizes — today this mislabels post-resize allocs as `initial_*`; fix this file too).

### Tests

Add `tests/test_resize.py` (names illustrative):

| Test | Expect |
|---|---|
| `test_resize_cpu_up_ok` | Legal increase on `tiny` / demo world succeeds; `get_container` shows new alloc |
| `test_resize_rejects_above_ms_max` | `cpu_max` breach → reject; alloc unchanged |
| `test_resize_rejects_server_packing` | Sum would exceed server cap → reject |
| `test_resize_ram_only_keeps_cpu` | Only RAM set → CPU unchanged |
| `test_resize_noop_within_eps` | Same value ±EPS → `NO_CHANGE` |
| `test_resize_unknown_container` | Reject |
| `test_meta_initial_alloc_survives_resize` | Resize after build, then flush → `.meta.json` `initial_*` still shows pre-resize alloc; `final_*` shows post-resize alloc |

```bash
cd HierarchicalEdgeSim
.venv/bin/python -m pytest tests/test_resize.py -v
.venv/bin/python -m pytest -q   # full Part A suite still green
```

### Gate

- [ ] All `test_resize.py` passed  
- [ ] Full suite green  
- [ ] No autoscaler package yet (good)  
- [ ] `.meta.json` `initial_*` reflects build-time alloc even when a resize happened before flush (plan §8.7)

---

## Step 2 — After-tick hook + `apply_actions` + action log

**Goal:** Env can invite a callback each τ, apply an action list one-by-one, and persist an action log.

### Action type lives in `env`

The autoscaler package (Step 3) doesn't exist yet, but `apply_actions` needs *some* concrete action shape now. To avoid `env` importing `autoscaler/` (forbidden per plan §4.1) or Step 2 blocking on Step 3:

- Define the canonical `ResizeAction` (fields per plan §5.3: `type`, `ms_id`, `container_id`, `cpu_alloc_cores`, `ram_alloc_mb`, `reason`, optional `tau`) in `env/api.py` (or a new `env/actions.py`) — this is the type `apply_actions` accepts.
- In Step 3, `autoscaler/common/actions.py` imports and re-exports this same type (satisfying the plan's "common → env (types only)" dependency direction) rather than defining a second, incompatible dataclass.
- This also fixes the ordering problem for this step's tests: a "fake scaler" here can construct real `ResizeAction` instances directly from `env`, with no dependency on the not-yet-built autoscaler package.

### Build

1. `Env.apply_actions(actions) -> list[ResizeResult]` — sort by `(type, ms_id, container_id)`; dispatch `resize`; **update free capacity after each success**.
2. Thread optional `autoscaler` through `run_ticks` / `Env.run` / `_run_partial`: after physics for τ, **advance `state.current_tau = τ` first**, then if an autoscaler is present → `on_tick_end` → `apply_actions`. (Ordering matters: `env.get_time()` and `history_at(τ)` inside the hook must already reflect τ, not τ-1.)
3. Right after `apply_actions` returns its results, call `autoscaler.on_actions_applied(results)` if the object defines that method (duck-typed here; formalized as an optional protocol method in Step 3). This is the hook Step 4's cooldown-on-success logic depends on.
4. In-memory action log buffer; flush `actions.csv` in `write_run_outputs`.
5. Record autoscaler info in `run_meta.yaml` when provided (may be `null` for Part A).
6. Duplicate `container_id` in one batch → reject later entries (`DUPLICATE_IN_BATCH`); first scaler emits at most one resize per container per tick.

### Tests

Add `tests/test_apply_actions.py`, `tests/test_tick_hook.py`. Use a **dedicated fixture with two containers on the same server** for packing/duplicate tests — `02-demo_60_two_containers.yaml` puts its two containers on *separate* 8-core servers and cannot exercise a packing conflict.

| Test | Expect |
|---|---|
| `test_hook_none_matches_part_a` | `run(max_ticks=N)` without scaler ≡ prior golden behavior |
| `test_hook_called_once_per_tick` | Fake scaler called N times with τ=1..N |
| `test_hook_sees_correct_tau` | Inside the fake scaler's `on_tick_end`, `env.get_time() == τ` and `history_at(τ)` exists (catches the `state.current_tau` ordering bug) |
| `test_apply_actions_sequential_packing` | Shared-server fixture; two resizes same server in one batch; second sees reduced free (not a stale snapshot) |
| `test_apply_actions_duplicate_container_rejected` | Two actions with same `container_id` in one batch → first applies, second gets `DUPLICATE_IN_BATCH` |
| `test_resize_effective_next_tick` | Resize after τ=1; τ=2 history shows new `cpu_alloc_cores` |
| `test_on_actions_applied_called_with_results` | Fake scaler's `on_actions_applied` receives the exact `list[ResizeResult]` from that tick's `apply_actions` |
| `test_actions_csv_written` | Fake scaler returns one resize → `actions.csv` has a data row |
| `test_actions_csv_header_only_when_empty` | No scaler → header-only file (document choice) |

```bash
.venv/bin/python -m pytest tests/test_apply_actions.py tests/test_tick_hook.py -v
.venv/bin/python -m pytest -q
```

### Gate

- [ ] Hook optional; Part A path unchanged  
- [ ] Sequential packing verified on a shared-server fixture  
- [ ] Duplicate-in-batch rejected  
- [ ] History timing: τ pre-resize, τ+1 post-resize  
- [ ] `on_actions_applied` fires with apply results, independent of any concrete scaler  

---

## Step 3 — `autoscaler/common` (selection only)

**Goal:** Supported list + YAML load + shared action types. Still no real policy.

### Build

```text
src/hierarchical_edge_sim/autoscaler/
  common/
    protocol.py      # on_tick_end(env, tau) -> list[Action]; optional on_actions_applied(results) -> None
    actions.py       # re-exports env's ResizeAction (see Step 2 "Action type lives in env")
    supported.py     # SUPPORTED_AUTOSCALERS
    load.py          # load_autoscaler_from_yaml(path) -> Autoscaler | None
    params_base.py   # enabled / name / params / decision_every_k_ticks wrapper
```

1. Parse top-level `autoscaler:` independently of `env.config.load_yaml` (which already ignores unknown top-level keys today — confirm this with a test rather than assuming it).
2. Unknown `name` → clear error before ticks.
3. `enabled: false` / missing block → `None`.
4. `decision_every_k_ticks` (default `1`) is parsed here as part of the common wrapper and passed to the concrete scaler's `build(params, decision_every_k_ticks=...)` — **not** consumed by `env`. `env` calls `on_tick_end` unconditionally every tick (plan §8.9: streaks must update every tick); the built scaler is responsible for internally suppressing action emission on ticks where `τ % k != 0`.

### Tests

Add `tests/test_autoscaler_load.py`:

| Test | Expect |
|---|---|
| `test_missing_block_returns_none` | No `autoscaler:` → `None` |
| `test_disabled_returns_none` | `enabled: false` → `None` |
| `test_unknown_name_raises` | `name: not_a_scaler` fails fast |
| `test_wrapper_requires_name_when_enabled` | enabled without name → error |
| `test_decision_every_k_ticks_defaults_to_one` | Wrapper omits it → scaler built with `k=1` |
| `test_env_tolerates_autoscaler_block` | `Env.from_config` on a YAML with a top-level `autoscaler:` block still builds the world identically to the same file without it (confirms `env/config.py` really ignores the extra key) |
| `test_env_module_does_not_import_autoscaler` | After `import hierarchical_edge_sim.env.api`, `hierarchical_edge_sim.autoscaler` is not in `sys.modules` (static enforcement of the "env ✗→ autoscaler" rule, not just a manual gate checkbox) |

```bash
.venv/bin/python -m pytest tests/test_autoscaler_load.py -v
.venv/bin/python -m pytest -q
```

### Gate

- [ ] Env still does not import concrete scaler folders (verified by test, not just review)  
- [ ] Load errors are clear  
- [ ] `decision_every_k_ticks` threading documented and defaulted  

---

## Step 4 — `reactive_vertical` policy (unit level)

**Goal:** Per-MS streaks + distribute → `ResizeAction` list.

### Build

```text
autoscaler/reactive_vertical/
  params.py       # dataclass + validate (defaults = locked table above)
  distribute.py   # grow/shrink ranking
  policy.py       # ReactiveVerticalAutoscaler
  __init__.py     # build(params)
```

1. List `reactive_vertical` in `SUPPORTED_AUTOSCALERS`.
2. Wire `load.py` → this folder’s `build(params, decision_every_k_ticks=1)`.
3. Cooldown / streak reset: implement `on_actions_applied` (protocol hook from Step 2/3) so cooldown matches plan §8.8: reset streaks + start cooldown **only if at least one resize in the batch succeeded**; if all rejected, streaks persist untouched so pressure can retry next tick.
4. `decision_every_k_ticks` gating lives here: update `u_streak`/`d_streak` every call to `on_tick_end` (every τ), but only return a non-empty action list when `τ % k == 0` (and cooldown allows). `k=1` (default) behaves exactly as if ungated.
5. `NEED_HORIZONTAL` (plan §6.6/§8.8): when a grow decision still has residual `Δ_cpu_ms`/`Δ_ram_ms` after every replica is at MS max and/or server free is exhausted, do **not** fabricate capacity and do **not** only bury the signal in a resize `reason`. Emit a **separate log line** (same `actions.csv` or a sibling events log — pick one file in Step 2/6 and stick to it) with `action_type=need_horizontal` (or equivalent), `ms_id`, `tau`, and residual demand fields if cheap to record. No `spawn` in this milestone.

### Tests

Add `tests/test_reactive_vertical.py`. Toy params OK: `x_up_streak=2`, `y_down_streak=3`, `cooldown_ticks=1`.

| Test | Expect |
|---|---|
| `test_params_defaults_validate` | Locked defaults parse |
| `test_params_reject_bad_theta` | `theta_free: 1.5` fails |
| `test_aggregate_drop_streak_fires_up` | D>0 for X ticks → UP actions |
| `test_slack_streak_fires_down` | Low util for Y ticks → DOWN actions |
| `test_cooldown_suppresses` | After success, no new actions for C ticks |
| `test_all_rejected_keeps_streaks` | If every action in a batch is rejected (e.g. server full), streaks are **not** reset and cooldown is **not** started — next tick can retry |
| `test_decision_every_k_ticks_gates_emission` | With `k=2`, streaks advance every tick but actions are only emitted on even τ, even when fire conditions are met on an odd τ |
| `test_distribute_prefers_hot_replica` | Higher-drop replica grows first |
| `test_distribute_tie_break_deterministic` | Equal grow/shrink scores → lower `container_id` wins, both runs identical |
| `test_one_resize_per_container` | At most one action per `container_id` per tick |
| `test_drop_vetoes_down` | Drops never emit DOWN same tick |
| `test_need_horizontal_logged_on_residual_room` | All containers maxed / no room but deficit remains → a **separate** `need_horizontal` log line is written; no illegal over-max resize |

```bash
.venv/bin/python -m pytest tests/test_reactive_vertical.py -v
.venv/bin/python -m pytest -q
```

### Gate

- [ ] Policy is deterministic  
- [ ] No import cycle `env` ↔ concrete scaler  
- [ ] Cooldown/streak reset only on **successful** resize; all-rejected case retains pressure  
- [ ] `decision_every_k_ticks` gates emission only, not streak updates  

---

## Step 5 — Integration: hook + real scaler on short horizon

**Goal:** End-to-end on a **short** crafted trace (not full 60 yet).

### Build

1. Fixture: 1 MS, 1–2 containers, short trace with ≥X drop ticks then ≥Y idle ticks (`tests/data/` or tmp_path).
2. Second fixture variant: 2 containers **on the same server** with a tight `cpu_cap_cores`, so an UP decision can legitimately hit `SERVER_CPU_EXCEEDED` end-to-end (unit-level packing tests in Step 2 use a synthetic fixture; this is the first place a real scaler decision produces a real reject).
3. Run via `Env.run(max_ticks=…, autoscaler=…)`. Pass an explicit `now_utc` (see `tests/test_determinism.py` for the existing pattern) when comparing two runs — `run_id` has 1-second granularity (`{seed}_{utc_timestamp}`), so two fast back-to-back runs with the same seed can otherwise collide on the same `run_id`/directory.

### Tests

Add `tests/test_reactive_vertical_integration.py`:

| Test | Expect |
|---|---|
| `test_up_then_alloc_rises` | After UP, later history alloc > initial |
| `test_actions_csv_has_up_reason` | Up reason + `result_code=OK` |
| `test_total_drops_not_worse_than_static` | Σ drops with scaler ≤ without (same short trace) |
| `test_server_packing_reject_end_to_end` | Same-server fixture; an UP decision that would exceed server cap is rejected (`SERVER_CPU_EXCEEDED`), logged in `actions.csv`, and the run continues without crashing |
| `test_determinism_two_runs` | Two runs with fixed, distinct `now_utc` values → identical `actions.csv` + container logs |

```bash
.venv/bin/python -m pytest tests/test_reactive_vertical_integration.py -v
.venv/bin/python -m pytest -q
```

### Gate

- [ ] Resize visible in τ+1 history  
- [ ] Determinism holds  
- [ ] At least one real `SERVER_*` reject observed end-to-end (not just unit-level)  

---

## Step 6 — Demo runner + config + final scenarios

**Goal:** User-facing demos and the **final test scenarios** below (short smoke + **long primary**).

### Build

1. Keep / add short reactive demo: `configs/03-demo_60_two_containers_reactive.yaml` (optional smoke; same world as today’s 60-tick two-container demo).
2. **Primary final scenario artifacts** (create when coding Step 6):
   - `traces/demo/api_300_phased.csv` — 300-tick phased load (spec below)
   - `configs/05-demo_300_two_containers.yaml` — static world (same topology/apps as two-container demo; `trace_file: api_300_phased.csv`; `results_dir: results/03-phased-300/static/`)
   - `configs/06-demo_300_two_containers_reactive.yaml` — same world + locked `reactive_vertical` params; `results_dir: results/03-phased-300/vertical/`
3. `examples/run_with_autoscaler.py` — load world + scaler from YAML + `env.run(autoscaler=…)`.
4. Keep `examples/run_env_only.py` scaler-free.
5. Short how-to note for with/without scaler runs (mention both 60-tick smoke and 300-tick primary).

### Tests

| Test | Expect |
|---|---|
| `test_demo_config_loads_scaler` | Both reactive YAMLs load; name supported; params validate |
| `test_phased_trace_length` | `api_300_phased.csv` has header + exactly 300 data rows; `time_unit` = 1..300 |
| `test_final_scenario_long_drops_and_actions` | Automates drops A/B + non-empty UP/DOWN regions from **Scenario B** |
| `test_final_scenario_long_determinism` | Two reactive 300-tick runs (distinct `now_utc`) → identical `actions.csv` + logs |
| `test_smoke_60_optional` | Optional: 60-tick reactive produces ≥1 UP (soft smoke, not the A/B authority) |
| Manual only | Hot-first preference / story read-through |
| Full suite | Still green |

```bash
.venv/bin/python -m pytest -q
.venv/bin/python examples/run_env_only.py configs/05-demo_300_two_containers.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/06-demo_300_two_containers_reactive.yaml
# optional smoke:
.venv/bin/python examples/run_with_autoscaler.py configs/03-demo_60_two_containers_reactive.yaml
```

### Gate

- [ ] Phased 300-tick trace + configs exist and validate  
- [ ] Scenario B checklist complete (primary)  
- [ ] Part A-only path still works  
- [ ] Scenario A (60-tick) optional smoke green if kept  

---

## Final test scenarios

Two scenarios: a **short smoke** (A) and a **long primary** (B). **Scenario B is authoritative** for the “reactive reduces drops” gate. Scenario A may stay as a fast demo; do not treat a weak A/B on 60 ticks as an implementation failure.

Shared world (both scenarios unless noted):

| Item | Value |
|---|---|
| MS | `api` with `c-api-1` (1.0 core / 512 MB on `c1-w1`), `c-api-2` (2.0 / 1024 on `c1-w2`) |
| Servers | `c1-w1`, `c1-w2` @ 8 cores / 16384 MB each (packing should not block early UPs) |
| MS coeffs | `cpu_min=0.5`, `cpu_max=4.0`, `cpu_per_request=0.01`, `ram_per_request=0.5` |
| Static μ (initial) | ≈ 200 req/tick (headrooms 0.5 + 1.5) |
| Params | Locked realistic table (X=3, Y=8, C=5, θ_free=0.35, α_up=0.20, α_down=0.10, …) |
| Seed | `42` |

> **Note:** separate 8-core servers ⇒ expect **zero** `SERVER_*` rejects in A/B. Packing rejects are covered in Steps 1/2/5 with a shared-server fixture.

---

### Scenario A — Short smoke (60 ticks, optional)

**Name:** Two-container overload smoke  
**Configs:** `02-demo_60_two_containers.yaml` vs `03-demo_60_two_containers_reactive.yaml`  
**Trace:** existing `api_60_two.csv` (peak ≈ 286)

**Role:** Fast check that the scaler attaches, emits ≥1 UP during overload, and writes `actions.csv`.  
**Not authoritative** for drop A/B (horizon is tight vs cooldown / α_up).

| Check | Expected |
|---|---|
| Meta / actions | Scaler named; ≥1 UP resize during high-λ region |
| Next-tick effect | τ+1 alloc matches `cpu_new` |
| Drops A/B | Informational only |

---

### Scenario B — Long primary (300 ticks, authoritative)

**Name:** Phased reactive vertical (5 minutes @ `tick_sec=1`)  
**Configs:** `05-demo_300_two_containers.yaml` vs `06-demo_300_two_containers_reactive.yaml`  
**Trace:** `traces/demo/api_300_phased.csv` (create in Step 6)

#### Why 300 ticks

Locked params need room to work:

| Mechanism | Budget needed | How 300 ticks helps |
|---|---|---|
| UP fire | X=3 drop ticks | Overload plateau ≫ 3 |
| Growth | α_up=0.20 + C=5 between successes | ~110-tick plateau ≈ several UP cycles toward catching Λ |
| DOWN fire | Y=8 slack ticks + C=5 | ~90-tick idle tail |
| Story | Distinct phases | Easy to explain actions vs time |

#### Trace phases (`api_300_phased.csv`)

Generate a deterministic CSV (`time_unit,requests`, `time_unit=1..300`). Suggested request targets (exact integers OK; keep piecewise-linear ramps):

| Phase | τ (inclusive) | Target Λ (req/tick) | Intent |
|---|---|---|---|
| Warm-up | 1–40 | 40 → 80 | Below static μ; no sustained drops |
| Ramp-up | 41–70 | 80 → 300 | Enter overload |
| Overload plateau | 71–180 | **300** flat | Sustained drops under static μ≈200; scaler should UP repeatedly |
| Ramp-down | 181–210 | 300 → 50 | Leave overload |
| Idle / reclaim | 211–300 | **50** flat | High slack; after Y+cooldown, scaler should DOWN |

Sketch:

```text
Λ
300 |          ___________
    |         /           \
200 |--------/             \          (static μ ≈ 200)
    |       /               \
 50 |_____/                  \__________
    +----+----+----+----+----+----→ τ
     1  40  70 180 210     300
     warm ramp plateau ramp idle
```

**Generation rule (for implementers):** for each phase, linearly interpolate inclusive endpoints on integer τ, round requests to nearest int ≥ 0. No randomness (determinism).

#### Procedure

1. Run static: `run_env_only.py configs/05-demo_300_two_containers.yaml` → `RUN_STATIC` under `results/03-phased-300/static/`.
2. Run reactive: `run_with_autoscaler.py configs/06-demo_300_two_containers_reactive.yaml` → `RUN_REACTIVE` under `results/03-phased-300/vertical/`.
3. Sum `dropped_requests` over both containers in each run.
4. Split `actions.csv` by phase windows (UP expected mainly in τ∈[71,180]; DOWN mainly in τ∈[211,300] after streak/cooldown).
5. Confirm determinism with a second reactive run (distinct `now_utc`).

#### Expected outcomes

| Check | Expected |
|---|---|
| Meta | `name: reactive_vertical` + locked params in `run_meta` |
| Warm-up | No UP required; actions empty or only harmless NO_CHANGE |
| Overload | After ≥3 drop ticks from plateau start → first UP; **multiple** UPs across the plateau (cooldown permitting) |
| Catch-up | Reactive Σ drops on τ∈[71,180] **strictly below** static Σ drops on the same window (primary hardness) |
| Full-horizon A/B | Full-run `Σ drops(reactive) ≤ Σ drops(static)` (should follow from plateau win) |
| Next-tick effect | After each successful UP, τ+1 history alloc = `cpu_new` |
| Hot-first | Early UPs prefer hotter / higher-drop replica |
| Idle DOWN | In reclaim phase, after slack≥θ_free for Y=8 and cooldown clear → ≥1 DOWN; colder replica preferred when consolidating |
| `need_horizontal` | Unlikely here (servers have spare cores before MS max); if MS max hit under Λ=300, separate `need_horizontal` lines are OK |
| Determinism | Identical `actions.csv` + logs across two reactive runs |
| Part A isolation | Static config has no scaler; full pytest green |

#### Manual review packet (Scenario B)

- Plateau drops: static ____ / reactive ____ (must improve)  
- Full-run drops: static ____ / reactive ____  
- UP count / DOWN count: ____ / ____  
- First UP at τ=____ on ____ (`cpu_old`→`cpu_new`)  
- First DOWN at τ=____ on ____  
- Any `need_horizontal` lines? ____  
- Pytest: `____ passed`

#### Scenario B gate

- [ ] Phased trace length and phase targets match the table  
- [ ] Plateau drop A/B **improves** under reactive  
- [ ] ≥1 UP in overload and ≥1 DOWN in reclaim (with locked params)  
- [ ] Determinism confirmed  
- [ ] No Part A regressions  

---

## Suggested PR slicing

| Slice | Steps | Focus |
|---|---|---|
| PR1 | 1–2 | Env actuation + hook |
| PR2 | 3–4 | Package + reactive units |
| PR3 | 5–6 | Integration + demos + **300-tick primary scenario** |

---

## Out of scope

- `spawn` / `terminate` bodies  
- Second production autoscaler  
- Vicinity / BEG / loans  
- Two autoscalers in one run  
- Plot pipeline changes (optional follow-up)
- Actually spawning horizontal capacity when `NEED_HORIZONTAL` fires — only a **separate log line** is in scope (Step 4)

---

## Decisions locked (was “open questions”)

### 1) What that first review question meant (plain language)

It was **not** asking you to change the algorithm. It only meant:

> With a short 60-tick trace, cooldown=5, and gradual 20% ups, the scaler might not finish growing before the overload ends. If the final scenario then *hard-fails* because total drops did not fall, that could be “params too slow for this trace,” not a code bug.

**Decision:** keep the locked params. Use **Scenario B (300-tick phased)** as the authoritative drop A/B gate. Keep Scenario A (60-tick) as optional smoke only. If B’s plateau A/B fails, investigate (bug vs unexpected packing/MS-max) — the horizon is sized so “too short” should not be the excuse.

### 2) `NEED_HORIZONTAL` logging

**Decision:** **separate log line** (not only a `reason` on a resize). Prefer a row in `actions.csv` with `action_type=need_horizontal` (and `ms_id`, `tau`, optional residual fields). No spawn in this milestone.

### 3) Result codes for resize

**Decision:** use a new **`ResizeResultCode`** enum for resize/apply results (`OK`, `UNKNOWN_CONTAINER`, …). Leave Part A `RejectReason` as the stub reason for unimplemented `spawn`/`terminate`. Do not overload `RejectReason` with `OK`.

---

## Document history

| Version | Change |
|---|---|
| v1 | Steps 0–6 with tests; realistic params; final two-container scenario |
| v2 | Review pass against plan v6 + current `env/` code. Resolved action-type ownership ambiguity (defined in `env`, re-exported by `autoscaler/common`); fixed `state.current_tau`-vs-hook ordering hazard; clarified `decision_every_k_ticks` threading (gates emission only, hook always fires); formalized `on_actions_applied` in the protocol with tests; added missing `DUPLICATE_IN_BATCH`, all-rejected-keeps-streaks, k-gating, tie-break, `NEED_HORIZONTAL`, env-non-import, and config-tolerance tests; clarified that packing/`SERVER_*` rejects need a dedicated shared-server fixture (not `02-demo_60_two_containers.yaml`) and are not exercised in the final scenario; flagged and fixed the `run_id` collision risk between static/reactive comparison runs; reconciled locked-defaults vs plan's illustrative example numbers. |
| v3 | Locked decisions: explained Q1; `NEED_HORIZONTAL` = separate log line; `ResizeResultCode`. |
| v4 | Added **Scenario B**: 300-tick phased trace (warm / ramp / overload plateau / ramp-down / idle); 60-tick becomes optional smoke; plateau drop A/B is authoritative. |
