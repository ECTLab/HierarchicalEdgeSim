# Surplus scale-down, resource quantum, and seed action log

**Status:** landed on `code-review`  
**Date:** 2026-08-18  
**Related:** [s6-scale-down-reclaim.md](./s6-scale-down-reclaim.md), [s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md), [s2-reactive-local-ladder.md](./s2-reactive-local-ladder.md)

This note covers why scale-down still walked the last replica onto `μ = 0`, why `actions.csv` started mid-run, why CPU/RAM values were long floats, and what replaced those behaviors.

---

## 1. Scale-down walked the last replica through μ = 0

### Problem

Scale-up already sized from **dropped demand** (`need = D × ρ`, capped by `α_up`). Scale-down did not have a matching rule. It released a **multiplicative** chunk every down tick:

`Δ = max(δ_min, α_down · ΣA)`

On a descending load that is still enough for one replica, that step does not know when to stop. After vicinity/BEG extras are gone, the leftover `δ_min` (0.25 cores / 128 MB) keeps eating the home seed until it sits on the deployment floor (`cpu_min`, `ram_min`). Floors buy **no** serving capacity, so `μ = 0`. Routing still sends the replica load (CPU-headroom weighted), and the next ticks bounce **UP** again.

A later clamp, `protect_last_serving` plus `_safe_down_alloc`, tried to refuse the last serving replica’s floor. It was a symptom fix:

- It only applied on the proactive path.
- It still let **independent** CPU and RAM shrinks create a CPU-weighted zombie (CPU above min, RAM at min → receives load, drops it).
- It did not size the last replica from current `Λ`. After remotes died, the seed either sat oversized or was walked to the floor.

Same-tick **BEV shrink + BEH terminate** made it worse: extras died and the seed was shrunk in one decision, leaving `μ` below the remaining load, which retriggered UP.

`up_mode: deficit | multiplicative` was also leftover. Every live config used deficit; the multiplicative UP branch was unused.

### Solution — surplus of serving capacity

Down is now the counterpart of deficit-up. Target utilization is the slack threshold already in YAML:

`μ_tgt = Λ / (1 − θ_free)`  
`surplus_μ = max(0, μ − μ_tgt)`  
`Δ_cpu = surplus_μ · ρ_cpu`, `Δ_ram = surplus_μ · ρ_ram` (coupled)

Then:

- **One replica:** apply that surplus, but never take `δ_min` *past* it. A tiny leftover surplus shrinks by that leftover, not by 0.25 cores. At the target, `Δ = 0` (hold).
- **Several replicas:** reclaim **count first**. Skip BEV on the seed in the same tick as a terminate. BEH may kill an extra only if remaining `μ` still covers `μ_tgt`. Rank extras by loan tier, then by how little `μ` they add (floor replicas first).
- **Floor extras that add no μ:** still get a rate-cap token so BEH can terminate them.
- CPU and RAM stay coupled so idle RAM cannot justify killing CPU the load still needs.

Removed as unused: `protect_last_serving`, `_safe_down_alloc`, `up_mode` / `down_mode`. UP is always deficit. `reactive_vertical` (BEV-only baseline) still shrinks with the old multiplicative `Δ`; surplus lives on the **ladder** (`reactive_local.allocate.down_delta` / `ladder_down`), which proactive also calls.

`cascade_home` is unchanged as a flag (default true). The triangle demo turns it **off**: pulling a BEG replica onto a 1-core home worker would shrink the seed to minima and restart UP/DOWN chatter.

### Triangle demo (proof harness)

`configs/demo_400_triangle_beg.yaml` + `traces/demo/api_400_triangle.csv`

400 ticks: `Λ` 40 → 180 by τ=200, 180 → 5 by τ=320, hold at 5. Topology forces the full up ladder (home full → vicinity on c2 → BEG on c3) and then reclaim to one local seed. Assertions: live set is `c-api-0` on `c1-w1`, alloc stays **above** `cpu_min`, no UP after the last remote terminate, no later down onto the floor.

```bash
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_400_triangle_beg.yaml
```

Outputs: `results/triangle_beg/<seed>_<utc>/`.

---

## 2. Action log started at the first scaler mutation

### Problem

`actions.csv` only recorded autoscaler `apply_actions` rows. YAML-placed replicas exist at world build, before τ=1, and were never logged. In the triangle run the first mutation is `vicinity_spawn` around **τ=18**, so the file looked like the application started then. The seed’s life (`c-api-0` from init through the last shrink) was missing.

Per-tick usage for that seed was already in `c-api-0.log.csv` from τ=1. The gap was the **lifecycle** log, not the usage log. Quiet ticks still have no action rows; that is intentional.

### Solution — seed spawn at τ=0

`Env.__post_init__` writes one `ActionLogRow` per YAML container:

| Field | Value |
|---|---|
| `tau` | `0` |
| `action_type` | `spawn` |
| `reason` | `seed` |
| `autoscaler_name` | empty |
| `cpu_new` / `ram_new` | initial alloc |
| `result_code` | `OK` |

Rows are sorted by container id. Scaler actions follow at their real ticks. A run with no scaler still writes the seed row(s).

---

## 3. CPU/RAM were long floats in the simulator, not only in logs

### Problem

Surplus math, routing splits, and `round`-less `alloc ± Δ` produced values such as `0.5769230769230769` cores. Formatting the CSV would have hidden them; live alloc, the next tick’s `μ`, and later actions would still carry the binary float.

### Solution — 0.01 quantum on cores and MB

`RESOURCE_DECIMALS = 2` in `env/config.py`:

- `quantize_resource(x)` → `round(float(x), 2)` (in-memory)
- `format_resource(x)` → `"0.58"` / `""` if missing (CSV)

Applied at every **alloc/usage write**:

| Path | What snaps |
|---|---|
| `Container.__post_init__` | live + initial alloc |
| `Env.resize` / `Env.spawn` | targets before clamp / `NO_CHANGE` |
| `usage.apply_tick` | `cpu_usage_cores` / `ram_usage_mb` |
| `distribute_up` / `distribute_down` | BEV targets; skip resize if quantized alloc is unchanged |
| `packed_spawn_size` | spawn cpu/ram and resulting headroom |
| leftover residuals in `apply_actions` | `need_*` log columns |
| `metrics_log` | action/container CSV via `format_resource`; meta JSON keeps quantized **numbers** |

**Not** quantized: `cpu_per_request_cores` / `ram_per_request_mb` (Alibaba uses `0.0004`), request counts, `q`, `θ`. Rounding those to two decimals would zero the cost model.

So `0.5769…` becomes **0.58** in memory, in later ticks, and on disk.

---

## How to verify

```bash
python3 -m pytest tests/ -q
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_400_triangle_beg.yaml
```

In the new `results/triangle_beg/<run_id>/`:

- `actions.csv` starts with `tau=0`, `reason=seed`, `c-api-0`, `cpu_new=1.00`, `ram_new=512.00`
- CPU/RAM columns are two decimals (`0.50`, `0.58`, `490.73`), not long floats
- After the last `beh_terminate`, the seed is not resized onto `cpu_min` and does not bounce UP
- `apps/demo_app/api/c-api-0.log.csv` still has usage from τ=1 through the horizon

Older `triangle_beg` folders from before this working set still start at τ=18 and show unquantized values.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-18 | Surplus down; drop protect/up_mode; 0.01 resource quantum; seed action at τ=0; triangle BEG demo |
