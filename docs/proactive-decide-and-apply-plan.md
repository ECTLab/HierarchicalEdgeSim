# Plan: Proactive Decide + Apply (simple v1, reuse-first)

**Audience:** onboarding / implementation planning  
**Constraint:** do **not** add files or logic that duplicate what already exists; do **not** modify `autoscaler/reactive_vertical/`  
**Scope:** proactive scale decisions + apply; reactive warm-up by **calling** existing reactive code; no confidence / κ  
**Out of scope:** MAPE/κ, BEV/BEH, spawn/terminate, predictor quality, moving helpers into `common/`  

**Decide formulas:** [rps-forecast-predict-and-decide.md](./rps-forecast-predict-and-decide.md) §4.1–4.4 (**ignore** §4.5 confidence)  
**Forecast already done:** [proactive-auto-scaler-implementation.md](./proactive-auto-scaler-implementation.md) Steps 1–2

---

## 0. One-sentence goal

When YAML selects `proactive_auto_scaler`, keep sensing/forecast as today; while RPS history is short, **delegate scaling to the existing** `ReactiveVerticalAutoscaler`; once history is full, run **new** proactive decide math and turn residuals into actions by **reusing** existing `distribute_up` / `distribute_down`. Pure reactive runs stay `autoscaler.name: reactive_vertical` (already works). Env apply path stays unchanged.

---

## 1. Codebase scan — reuse inventory

### 1.1 Reuse as-is (do not reinvent)

| Capability | Where | How we use it |
| --- | --- | --- |
| Tick → `on_tick_end` → `apply_actions` → `on_actions_applied` | `env/api.py` (`_invoke_autoscaler`, `Env.run`) | Unchanged applicator |
| `ResizeAction`, `NeedHorizontalAction`, results | `env/api.py`; re-export `autoscaler/common/actions.py` | Import; **no new action types** |
| Name-based scaler selection | `common/load.py`, `common/supported.py`, `common/params_base.py` | `reactive_vertical` vs `proactive_auto_scaler` already selects the circuit |
| Reactive decide + cooldown + streaks | `reactive_vertical/policy.py` (`ReactiveVerticalAutoscaler`, `build`) | Embed instance; call `on_tick_end` / `on_actions_applied` for warm-up |
| Vertical packing of MS deltas onto containers | `reactive_vertical/distribute.py` (`ReplicaView`, `distribute_up`, `distribute_down`) | Import for proactive allocate; **do not copy** |
| TTW RPS, history, forecast, predictors, `rps_forecast.csv` | `proactive_auto_scaler/{ttw_rps,history,forecast,predictors,policy}` | Keep; only extend `policy.py` wiring |
| Forecast CSV flush pattern | `env` / `metrics_log` via `scaler.rps_forecast_log` | Same pattern if we add an optional decision buffer later |

### 1.2 Must stay untouched

- Entire tree `autoscaler/reactive_vertical/` (no allowlist param, no reason-string edits, no move of `distribute_*` into `common/`).
- Env apply/hook contracts (covered by `tests/test_apply_actions_hook.py`).

### 1.3 Truly missing (only these are new)

| Gap | Why it cannot be reused |
| --- | --- |
| Forecast → Up/Down/None + demand residuals | No util/θ/`r★` decide anywhere today |
| Warm-up handoff inside proactive | Proactive always `return []`; never embeds reactive |
| Decide/cooldown YAML knobs on proactive params | `validate_params` is forecast-only and **rejects** unknown keys |

### 1.4 What an earlier draft of this plan would have wasted

| Rejected idea | Why redundant / wrong |
| --- | --- |
| New `hybrid_warmup_scaler.py` | Env already loads one object by `autoscaler.name`. Embed reactive inside existing `ProactiveAutoScaler` (`policy.py`). |
| New top-level `scaling_mode` **in addition to** `name` | Pure reactive is already `name: reactive_vertical`. Proactive+warmup is `name: proactive_auto_scaler`. A second switch duplicates selection. |
| New action dataclasses | Use `common.actions` / env types |
| New `distribute_*` fork / greedy reimplementation | Import `reactive_vertical.distribute` |
| Reimplement reactive policy for warm-up | Call `ReactiveVerticalAutoscaler.on_tick_end` |
| Rebuild TTW/history/forecast/predictors | Already in `proactive_auto_scaler/` |
| `confidence.py` / κ / MAPE | Out of scope |
| Separate `decision_log.py` module | Optional list attribute on the scaler (same style as `rps_forecast_log`); flush helper can live next to existing forecast CSV writer — no new package file required for v1 |

---

## 2. Working circuit (selection without a second mode flag)

Use the **existing** YAML selector:

```yaml
autoscaler:
  name: reactive_vertical      # pure reactive — today's path; proactive not constructed
  # ...
```

```yaml
autoscaler:
  name: proactive_auto_scaler  # proactive run: reactive warm-up → proactive steady state
  params:
    feature_window: 30         # warm-up length = history fullness
    # ... forecast + NEW decide knobs ...
    reactive:                  # optional nested dict → reactive_vertical.build(...)
      # same keys as a reactive_vertical params block; defaults if omitted
```

| `autoscaler.name` | Circuit |
| --- | --- |
| `reactive_vertical` | Only reactive (unchanged). Proactive code not in the loop. |
| `proactive_auto_scaler` | Sense/forecast always; **warm-up:** reactive actions for MS with `not hist.is_full()`; **steady:** proactive decide + reuse `distribute_*` for MS with full history. |

If you prefer the word `scaling_mode` in docs/UI, treat it as an **alias of `name`**, not a second config key (`reactive` ↔ `reactive_vertical`, `proactive` ↔ `proactive_auto_scaler`). Do not implement two knobs.

---

## 3. Warm-up → steady handoff

```text
hist.is_full()  # len >= feature_window  (already on RpsHistory)
```

- **Before full (per MS):** scaling actions from embedded `ReactiveVerticalAutoscaler` only.
- **After full (per MS):** scaling actions from proactive decide + `distribute_*` only; filter out any reactive actions for that `ms_id`.
- **No κ:** never fall back to reactive after that MS is ready.
- **Recommendation:** per-MS gate (A can be proactive while B still warms).

### Calling reactive without editing it

`on_tick_end` has no MS allowlist. v1 approach (plan lock):

```text
raw = self._reactive.on_tick_end(env, tau)
keep = [a for a in raw if not self._histories[a.ms_id].is_full()]
# append proactive actions for ready MS (TTW close only)
```

Forward `on_actions_applied` to reactive so its existing cooldown/streaks still update for warm-up ticks. Separately arm proactive TTW cooldown only for MS that emitted proactive resizes.

---

## 4. Target loop (proactive name)

```text
each tick τ:
  # existing sensing (refactor body of today's on_tick_end into a helper)
  accumulate λ_in; on TTW close: append r_t, forecast+log if hist full

  if scaling via proactive_auto_scaler:
    actions = []

    # warm-up: reuse reactive as-is
    if any MS not hist.is_full():
      actions += filter(reactive.on_tick_end(env, τ), ms still warming)

    # steady: only on TTW close, only for MS with hist.is_full()
    if is_ttw_close:
      for ms ready:
        if cooldown: continue
        (Δ, δ_cpu, δ_ram, ...) = predict_and_decide(r_t, r_hat, ...)   # NEW math
        if Δ in {Up, Down}:
          actions += allocate_via_existing_distribute(...)              # REUSE distribute

    return actions   # env.apply_actions already applies

on_actions_applied(results):
  reactive.on_actions_applied(results)           # reuse
  arm proactive next_allowed_ttw for pending MS  # small new state on proactive scaler
```

---

## 5. Minimal file touch list

```text
autoscaler/proactive_auto_scaler/
  policy.py      # CHANGE — embed reactive; handoff; call decide + distribute
  params.py      # CHANGE — theta_*, sustained_tau, cooldown_C; optional nested reactive dict
  decide.py      # NEW — only place for PredictAndDecide math (no env packing)
  # optional thin allocate helper: either allocate.py OR private funcs in policy.py
  #     → build ReplicaView list + call distribute_up/down + remap reason via dataclasses.replace
  # unchanged: ttw_rps, history, forecast, predictors/*
  # NO: hybrid_warmup_scaler.py, confidence.py, decision_log.py, new action types

autoscaler/reactive_vertical/   # ZERO edits
autoscaler/common/load.py       # likely ZERO edits if proactive.build() embeds reactive
env/                            # ZERO edits for apply path; optional later: decisions.csv writer only
```

| Artifact | Role |
| --- | --- |
| `decide.py` | **Only new policy math** — direction, residuals, sustained |
| `policy.py` | Orchestration + handoff (extends existing class) |
| `params.py` | Extend existing dataclass/validator |
| Allocate glue | Prefer **functions in `policy.py`** or one small `allocate.py` that **only** (1) builds `ReplicaView`s from env, (2) calls `distribute_up`/`distribute_down`, (3) remaps `reason` to `proactive_up`/`proactive_down` via `dataclasses.replace` — because distribute hardcodes `reactive_*` reasons and we will not edit reactive |

### Unavoidable small overlap (acknowledged)

`_aggregate_ms` in reactive `policy.py` is **private**. We will not edit reactive to export it. Allocate glue needs a short local snapshot that fills `ReplicaView` (cpu/ram alloc, room up/down, drop, q, slack) — same *data*, not a second distribute algorithm. Do not copy streak/intent/cooldown logic.

---

## 6. Sample shapes (reuse-aware)

### 6.1 Embed reactive in existing builder

```python
# proactive_auto_scaler/policy.py — conceptual build()
from hierarchical_edge_sim.autoscaler.reactive_vertical import build as build_reactive

def build(params: dict, decision_every_k_ticks: int = 1) -> ProactiveAutoScaler:
    validated = validate_params(params)  # pops/validates nested "reactive" if present
    reactive = build_reactive(
        validated.reactive_params_dict,  # {} → reactive defaults
        decision_every_k_ticks=decision_every_k_ticks,
    )
    return ProactiveAutoScaler(
        params=validated,
        _predictor=_make_predictor(validated),
        _reactive=reactive,
    )
```

`common/load.py` can stay as today: it already calls `proactive_auto_scaler.build(...)`.

### 6.2 Decide (new — no equivalent in repo)

```python
# decide.py — pure functions; no ResizeAction, no distribute
class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    NONE = "none"

def predict_and_decide(*, r_t, r_hat, A_cpu, A_ram, rho_cpu, rho_ram, u_meas,
                       theta_up, theta_down, theta_target, sustained_tau):
    # util bridge + Δ from u_obs / max û  (design §4.2)
    # r_star = max(r_t, max(r_hat))       (design §4.4)
    # δ = A_req - A ; clamp by direction
    # sustained from count of û_h >= theta_up
    ...
```

### 6.3 Allocate via existing distribute (no fork)

```python
# policy.py or allocate.py — glue only
from dataclasses import replace
from hierarchical_edge_sim.autoscaler.reactive_vertical.distribute import (
    ReplicaView,
    distribute_up,
    distribute_down,
)

def allocate_vertical(env, *, ms_id, tau, direction, delta_cpu, delta_ram, reactive_params):
    replicas = _snapshot_replica_views(env, ms_id, tau)  # fills ReplicaView; local helper
    spec = env.get_ms_spec(ms_id)
    if direction is Direction.UP:
        actions = distribute_up(
            env=env, ms_id=ms_id, spec=spec, params=reactive_params,
            replicas=replicas, delta_cpu=delta_cpu, delta_ram=delta_ram, tau=tau,
        )
        reason = "proactive_up"
    else:
        actions = distribute_down(...)
        reason = "proactive_down"
    # distribute hardcodes reactive_* reasons; remap without editing reactive:
    return [
        replace(a, reason=reason) if getattr(a, "type", "") == "resize" else a
        for a in actions
    ]
```

`NeedHorizontalAction` from leftover Up residual stays as emitted by `distribute_up` (already correct type).

### 6.4 `on_tick_end` sketch

```python
def on_tick_end(self, env: Env, tau: int) -> list[Any]:
    self._sense_and_forecast(env, tau)  # today's body; still returns early mid-TTW for forecast side

    actions: list[Any] = []

    if self._any_warming():
        raw = self._reactive.on_tick_end(env, tau)
        actions.extend(a for a in raw if not self._histories[a.ms_id].is_full())

    if not is_ttw_close(tau, self.params.ttw_ticks):
        return actions  # proactive steady-state only decides on TTW close

    for ms_id in env.list_microservices():
        if not self._histories[ms_id].is_full():
            continue
        if self._in_proactive_cooldown(ms_id, tau):
            continue
        # r_t / r_hat from sensing; capacity from env
        d = predict_and_decide(...)
        if d.delta is Direction.NONE:
            continue
        ms_actions = allocate_vertical(...)
        if any(getattr(a, "type", "") == "resize" for a in ms_actions):
            self._pending_proactive_ms.add(ms_id)
        actions.extend(ms_actions)
    return actions
```

---

## 7. YAML (extend proactive params only)

```yaml
autoscaler:
  name: proactive_auto_scaler
  decision_every_k_ticks: 1    # still applies to embedded reactive warm-up
  params:
    # existing (unchanged meaning)
    ttw_ticks: 1
    feature_window: 30
    horizon_H: 3
    predictor: average

    # NEW decide / cooldown (proactive steady state)
    theta_up: 0.80
    theta_down: 0.30
    theta_target: 0.60
    sustained_tau: 2
    cooldown_C: 3

    # optional: params forwarded to reactive_vertical.build (warm-up + distribute weights)
    reactive: {}
```

Pure reactive demos keep:

```yaml
autoscaler:
  name: reactive_vertical
  params: { ... }
```

**Absent:** `kappa_*`, `mape_*`, `rps_floor`, separate `scaling_mode`, new scaler name in `SUPPORTED_AUTOSCALERS` (unless you explicitly want an alias — default: **no**).

---

## 8. Logging

- Keep `rps_forecast.csv` as today.
- Keep `actions.csv` via env; distinguish phases by remapped `reason` (`reactive_*` vs `proactive_*`).
- Optional v1: `decision_log: list[...]` on the scaler (like `rps_forecast_log`). CSV flush only if useful; **do not** invent a parallel logging framework.

---

## 9. Build order (still reuse-first)

### Slice A — Handoff only (no proactive actions yet)

1. `ProactiveAutoScaler` embeds `ReactiveVerticalAutoscaler` via `build_reactive`.
2. After sensing, if any MS warming → call reactive, filter by `is_full()`.
3. Ready MS still get `[]` from proactive branch.
4. Tests: before window full, capacity can change via reactive reasons; after full, reactive actions for that MS stop. **No reactive package edits.**

### Slice B — `decide.py` unit tests only

Pure math; no env.

### Slice C — Wire allocate via `distribute_*` + cooldown

1. Replica snapshot helper + call distribute + `replace` reasons.
2. TTW cooldown on proactive success.
3. Fixture: post-warmup resize changes alloc on τ+1.

### Slice D — Demo YAML knobs + optional decision buffer

Update a proactive demo config with θ / `cooldown_C` / optional `reactive: {}`.

### Explicitly do not do

| Do not | Reason |
| --- | --- |
| Edit `reactive_vertical/` | User lock |
| Add `hybrid_warmup_scaler.py` | Redundant with `policy.py` embed |
| Add second mode flag beside `name` | Selection already exists |
| Fork `distribute_up`/`down` | Import instead |
| Add κ / confidence | Scope |
| New action types | Use `common.actions` |

---

## 10. Picture

```text
autoscaler.name
     │
     ├─ reactive_vertical ──► ReactiveVerticalAutoscaler ──► env.apply_actions
     │         (package untouched; also used as library from proactive)
     │
     └─ proactive_auto_scaler ──► ProactiveAutoScaler (extended policy.py)
              │
              ├─ reuse: ttw / history / forecast / rps_forecast.csv
              ├─ warm-up: call embedded ReactiveVerticalAutoscaler, filter by is_full()
              └─ steady: decide.py (new) → distribute_up/down (reuse) → apply_actions
```

---

## 11. Acceptance

1. `name: reactive_vertical` — unchanged behavior; no proactive construction required.
2. `name: proactive_auto_scaler` — early actions use reactive path (existing reasons); after `feature_window` TTWs per MS, new actions use `proactive_*` reasons from decide+distribute.
3. No files under `reactive_vertical/` modified.
4. No duplicate distribute/action/forecast modules added.
5. No κ/confidence code.
6. Post-warmup rising load → successful resizes in `actions.csv`; next-tick capacity changes.
7. Existing forecast tests updated only where they assert “always `[]` / unknown `cooldown_C`” — those expectations intentionally change.

---

## 12. PR boundaries

| PR | Contents |
| --- | --- |
| **PR1** | Slice A — embed reactive + filter handoff |
| **PR2** | Slices B+C — `decide.py` + distribute glue + cooldown |
| **PR3** | Slice D — demo YAML (+ optional decision log flush) |

---

## 13. Remaining choices (narrow)

1. **Allocate glue location:** private helpers in `policy.py` vs one small `allocate.py` (either is fine; prefer **one file max**, no third logging module).
2. **Nested `params.reactive`:** empty dict → reactive defaults; enough for warm-up and for `distribute_*` weights.
3. **Cadence:** after warm-up, proactive decisions only on TTW close; mid-TTW ticks may still run reactive only for MS still warming.
4. **Per-MS vs global flip:** prefer **per-MS**.

Nothing else should expand the file count or reimplement existing behavior.
