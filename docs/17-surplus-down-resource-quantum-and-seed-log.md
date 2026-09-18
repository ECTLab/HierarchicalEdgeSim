# Surplus scale-down, resource quantum, and seed action log

**Status:** landed on `code-review`  
**Date:** 2026-08-18  
**Related:** [18-mu-matched-cpu-ram-scale.md](./18-mu-matched-cpu-ram-scale.md) (v3 RAM wallets), [16-s6-scale-down-reclaim.md](./16-s6-scale-down-reclaim.md), [27-s7-proactive-drop-diagnosis.md](./27-s7-proactive-drop-diagnosis.md), [14-s4-vicinity-help.md](./14-s4-vicinity-help.md), [15-s5-global-help.md](./15-s5-global-help.md)

This note covers why scale-down still walked the last replica onto `μ = 0`, why `actions.csv` started mid-run, why CPU/RAM values were long floats, and the two process holes the triangle plots then showed (remote spawns at μ=0, RAM-dust downs).

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
- **Several replicas:** peel the extra we would reclaim (toward `cpu_min`) before terminating it. Do not shrink keepers in the same tick as a terminate. BEH may kill an extra only if it is at the floor or remaining `μ` still covers `μ_tgt`. Rank extras by how little `μ` they add (floor replicas first), then `q`, slack, id.
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

Outputs: `results/06-triangle-beg-era/full_ladder/<seed>_<utc>/`.

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

## 4. Triangle plots: remote μ=0 spawns and RAM-dust downs

After v1, `compare_trace_vs_log.py` on the triangle run was conservation-clean, but two policy holes were visible in `actions.csv` / `ladder_qos.png`.

### Problem A — vicinity / BEG spawned at the floor

Local BEH already packed leftover **above** `cpu_min` so a new replica has μ>0 on the next tick. Vicinity and BEG still called `place_minima_spawns` and placed at `cpu_min` / `ram_min` (`0.50` / `256`).

Routing is CPU-headroom weighted. Headroom 0 ⇒ share 0, so the new replica took **no** load until a later BEV-up (~5 ticks). Those windows are the red spikes on `ladder_qos` (91 drops, 0.27%, max 6 in a tick). On a worker whose cap **is** the floor, BEV-up can never grow it — a permanent μ=0 replica.

### Solution A — same packer as BEH

`place_packed_spawns` uses `packed_spawn_size`: `alloc = MS floor + leftover headroom`, quantized. A server that can only fit the floor is skipped. `HelpRequest` carries `min_head_cpu` / `min_head_ram` from `delta_*_min` so the sliver matches YAML.

The first remote spawn is **not** a hardcoded `0.70` / `358.40`. At τ=18 home is full (seed 1.0 / 512), so the whole UP delta is leftover. `up_delta` takes one serving-μ step, rate-limited by the **CPU** wallet (`α_up · ΣA_cpu`), then converts both resources through ρ. Independent `α_up · 512` / `δ_ram_min=128` wallets are not used on the way up.

`α_up=0.20` on the seed:

| | Formula | Value |
|---|---|---|
| CPU leftover | `0.20 × 1.0` | 0.20 cores |
| μ step | `0.20 / 0.01` | 20 req/tick |
| RAM leftover | `20 × 0.5` | **10 MB** |
| packed CPU | `0.50 + 0.20` | **0.70** |
| packed RAM | `256 + 10` | **266** |

Later BEG rows can land on the same pair because BEV first spends the last 0.05 cores filling `0.95 → 1.00`, leftover `δ_min − 0.05 = 0.20` (and the matching RAM). BEV-up then walks CPU toward `cpu_max` and RAM only as far as `ram_min + μ · ρ_ram` (~281 MB at μ=50), not `ram_max`.

**Cascade-home** still places at minima: that tick only proved floor room was freed, so packing more might not fit.

### Problem B — RAM dust after the CPU quantum

Hold target is `μ_tgt = Λ / (1−θ_free)`. For Λ=5, `θ_free=0.35`: `μ_tgt ≈ 7.69`. Quantized last alloc `0.58` cores ⇒ μ=8. Leftover surplus ≈ 0.31 req/tick:

- `Δ_cpu = 0.0031` cores → round keeps **0.58**
- `Δ_ram = 0.15` MB → RAM still moves (`490.88 → 489.53` …)

CPU is binding, so shaving RAM does not reduce μ and the surplus never finishes. `actions.csv` repeated `bev_down` `0.58 → 0.58` until τ=400.

### Solution B — skip dust; still trim idle RAM to μ · ρ

v2 skipped any down that did not cut serving μ, so leftover RAM stayed near `ram_max` (490.88) while CPU sat at 0.58. v3 sizes each resource's headroom to `μ_tgt · ρ` independently: idle RAM above `ram_min + μ · ρ_ram` is released in `δ_ram_min` chunks. Sub-MB RAM-only dust is still skipped.

### Triangle result

| | v1 (floor spawn) | v2 (packed + μ-skip) | v3 (μ-matched ρ) |
|---|---|---|---|
| First remote spawn | `0.50` / `256` (μ=0 until BEV-up) | `0.70` / `358.40` | `0.70` / `266` |
| Dropped | 91 (0.27%) | 27 (0.08%) | same order (~0.08%) |
| Hold RAM | floor walk | `490.88` (idle) | `ram_min + μ · ρ_ram` (~260) |

---

## How to verify

```bash
python3 -m pytest tests/ -q
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_400_triangle_beg.yaml
# then: python3 examples/compare_trace_vs_log.py results/06-triangle-beg-era/full_ladder/<run_id>
```

In the new `results/06-triangle-beg-era/full_ladder/<run_id>/`:

- `actions.csv` starts with `tau=0`, `reason=seed`, `c-api-0`, `cpu_new=1.00`, `ram_new=512.00`
- CPU/RAM columns are two decimals (`0.70`, `0.58`, `266.00`), not long floats
- First packed spawn RAM is `256 + μ_step · ρ_ram`, not `α_up · 512`
- After the last extra terminate (`beg_terminate` / `vicinity_terminate` / `beh_terminate`), the leftover replica is not resized onto `cpu_min` and does not bounce UP
- Vicinity / BEG spawns have `cpu_new > 0.50` (they serve on the next tick)
- Leftover RAM matches serving μ (`≈ 256 + 8 × 0.5`), not `ram_max`
- `apps/demo_app/api/c-api-0.log.csv` still has usage from τ=1 through the horizon
- `analysis/demo_app/ladder_qos.png` drop callout should be ~0.08% after v2

Older `triangle_beg` folders from before this working set still start at τ=18 and show unquantized values.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v3 | 2026-08-20 | Scale CPU/RAM from one μ step through ρ; idle-trim leftover RAM |
| v2 | 2026-08-18 | Vicinity/BEG packed spawns; skip BEV-down that does not reduce μ |
| v1 | 2026-08-18 | Surplus down; drop protect/up_mode; 0.01 resource quantum; seed action at τ=0; triangle BEG demo |
