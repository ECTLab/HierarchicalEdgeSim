# S7 — Why TCN dropped 69% and what we changed

**Status:** control-path fixes (1)–(4) landed on `proactive-integration`  
**Configs:** `configs/demo_alibaba_proactive.yaml`, `configs/demo_alibaba_reactive_local.yaml`  
**Stage notes:** [s7-proactive-front-end.md](./s7-proactive-front-end.md)  
**Recorded numbers:** [alibaba-tcn-s7-results.md](./alibaba-tcn-s7-results.md)

After Option A TCN was wired onto the completed ladder, the Alibaba MS_588 demo
(721 one-minute ticks, 3,385,510 incoming) dropped **69%** of requests. The same
world under `reactive_local` dropped **15%**. This note is the diagnosis and the
four control-path changes that followed. The TCN weights were not retrained.

---

## What was not broken

`trace == sum(incoming)` and `incoming == served + dropped` on every recorded
run (max abs diff 0, conservation residual ~1e-9). The engine, logs, and usage
model did what the policy asked.

Serving is `μ = min((cpu − cpu_min) / ρ_cpu, (ram − ram_min) / ρ_ram)`. Floors
buy no throughput. Routing is CPU-headroom weighted: a replica at `cpu_min`
gets no share (equal-share only if *every* replica is at min). A replica with
CPU headroom and RAM at `ram_min` still **receives** load and then drops all of
it, because `μ_ram = 0`.

The TCN still lags the periodic 25–30k spikes (known from `alibaba-trace`).
That is secondary. At the first TCN spike (τ=81) the proactive run already had
more real CPU than reactive and **fewer** drops. The 226-minute blackout was
not a missed forecast.

---

## What was broken

Decide, BEV-down, and lite BEH disagreed with the usage model.

### Decide used `ΣA`, including floors

`C_full` and `A_req` used total allocation. Idle min-replicas added to `ΣA` but
not to `μ`. After a trough, `q_ms = used / EPS = 0`, so both measured and
RPS util looked idle → None/Down instead of Up. Residual then grew CPU because
`ΣRAM` already “looked enough.”

### BEV-down walked the last serving replica onto a floor

`prefer_consolidate_down` shrinks one replica per call. On the first TCN run,
τ=159–180 peeled `c-api-1` from 4.0 / 1280 to 0.56 / 312, then RAM hit **256**.
Later UPs grew CPU and left `μ_ram = 0`.

### Lite BEH spawned at `cpu_min` / `ram_min`

Those replicas add to `ΣA` and serve nothing until a later BEV. Apply order is
terminate → … → resize → spawn, so there is no same-tick BEV of a new id.

### RAM-dead replicas still attracted CPU-weighted routing

Even after the last-serving guard, BEV-down could floor **RAM** on an extra
replica while leaving CPU headroom. At τ=172 on the post-(3) run,
`c-api-c1-w1-1` sat at 3.0 CPU / 256 RAM, received 2362 requests, served 0.

### Snapshot at τ=300 (first TCN run, 69% drops)

| Replica | CPU | RAM | Incoming | Served | μ |
|---|---|---|---|---|---|
| `c-api-1` | 3.19 | **256** | 3182 | **0** | 0 |
| four BEH spawns | 0.50 | 256 | 0 | 0 | 0 |

Zero-serve blocks on that run: **216–441 (226 min)**, 520–561, 638–681, 703–721.
**331 / 721** ticks served nothing. 97.6% of TCN drops were after cold start;
only 16% sat on ≥15k spike ticks (reactive puts ~64% of its drops on spikes).

---

## Fixes (control first, then predictor)

| # | Change | Where | Why |
|---|---|---|---|
| 1 | Decide on serving headroom `H = Σ(A − min)`, not `ΣA` | `proactive_auto_scaler/decide.py`, `aggregate_ms` | `H ≈ 0` + load is saturated (Up). Residual is `A_req = n·min + (ρ · r* · tick_sec) / θ_target`, so the tight resource grows. `q_ms` is 1 when a modeled resource has no headroom and incoming > 0. |
| 2 | Do not BEV-down / terminate the last serving replica onto a floor | `distribute_down` / `beh_down` via `protect_last_serving` (proactive only) | A replica serves iff both resources sit strictly above min. The τ=159–180 shrink is what zeroed `μ`. |
| 3 | BEH packs leftover **above** min; BEV-up will not apply a resize that still has `μ = 0` | `beh.packed_spawn_size`, `distribute_up` | New replicas must take routed load on the next tick. Vicinity / BEG / cascade still place at minima. |
| 4 | Do not leave any replica at `μ = 0` with CPU headroom | `_safe_down_alloc` when `protect_last_serving` | Routing would send it load it cannot serve. Idle (CPU at floor) is allowed; a CPU-weighted zombie is not. |

TCN / hold-over-spike was **not** done. After (1)–(3) TCN already beat reactive
on the spikes. The remaining TCN-worse ticks were the RAM-dead attractors, which
(4) removed.

Reactive `distribute_down` is unchanged (flag off). Proactive cold-start and
TCN downs both pass `protect_last_serving=True`.

---

## Results on MS_588 (same 3,385,510 incoming)

| Run | Drop rate | Served | Zero-serve ticks | CPU-alive / RAM-dead ticks |
|---|---|---|---|---|
| TCN original (`42_20260816T083509Z`) | 69.11% | 1.05M | 331 | 344 (`c-api-1` at RAM 256) |
| TCN after (1)(2) (`42_20260816T094113Z`) | 45.29% | 1.85M | 0 | 59 |
| TCN after (3) (`42_20260816T100507Z`) | 14.15% | 2.91M | 0 | 202 |
| TCN after (4) (`42_20260816T102455Z`) | **7.85%** | 3.12M | 0 | **0** |
| reactive re-run (`42_20260816T100437Z`) | 15.44% | 2.86M | 5 | 10 |

Reactive moved slightly from the first recorded 15.11% because BEH now packs
the one spawn above min (`0.61 / 384` instead of `0.5 / 256`), which shifts
later downs. TCN after (4) still drops less on spikes than reactive (177k vs
334k). Remaining TCN drops are mostly those spikes (~66%).

After (3), every new TCN spawn served on its first live tick. After (4), no
BEV-down left RAM at 256 with CPU above min.

---

## Where to look

Plots are local and gitignored. Latest pair:

- TCN: `results/alibaba_proactive/42_20260816T102455Z/analysis/demo_app/`
  (`ladder_qos.png`, `tcn_forecast.png`, `trace_vs_log_requests.png`)
- Comparison: `results/alibaba_proactive/42_20260816T102455Z/analysis/baseline_comparison.png`
- Reactive: `results/alibaba_reactive_local/42_20260816T100437Z/analysis/demo_app/`

Regenerate:

```bash
export PYTHONPATH=/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples
export MPLCONFIGDIR=$PWD/.mplconfig
python3 examples/run_with_autoscaler.py configs/demo_alibaba_reactive_local.yaml
python3 examples/run_with_autoscaler.py configs/demo_alibaba_proactive.yaml
python3 examples/compare_trace_vs_log.py <reactive_run_dir>
python3 examples/compare_trace_vs_log.py <proactive_run_dir>
python3 examples/compare_reactive_baseline.py \
  --run reactive_local <reactive_run_dir> \
  --run proactive_tcn <proactive_run_dir>
```

---

## Still open

- Vicinity / BEG / cascade still spawn at MS minima (`place_minima_spawns`,
  `check_cascading_migration`). The Alibaba demo is single-cluster, so this
  did not affect the numbers above.
- TCN lag on the 60-minute spike cycle is unchanged. Chasing the last ~8%
  would be predictor / hold-over-spike work, not more usage-model patches.
- `sustained_tau: 99` stays BEV-first so a biased horizon does not skip
  vertical packing.
