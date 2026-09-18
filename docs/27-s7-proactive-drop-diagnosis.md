# S7 — Why TCN dropped 69% and what we changed

**Status:** control-path fixes (1)–(4) landed on `proactive-integration`  
**Configs:** `configs/13-demo_alibaba_proactive.yaml`, `configs/12-demo_alibaba_reactive_local.yaml`  
**Stage notes:** [26-s7-proactive-front-end.md](./26-s7-proactive-front-end.md)  
**Algorithm 3 mapping:** [24-predict-and-decide.md](./24-predict-and-decide.md)  
**Recorded numbers:** [29-alibaba-tcn-s7-results.md](./29-alibaba-tcn-s7-results.md)

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

`rps_capacity` and `A_req` used total allocation. Idle min-replicas added to `ΣA` but
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
| 1 | Decide on serving headroom `headroom = Σ(A − min)`, not `ΣA` | `proactive_auto_scaler/decide.py`, `aggregate_ms` | Headroom ≈ 0 + load is saturated (Up). Residual is `A_req = n·min + (cpu_per_request · peak_rps · tick_sec) / θ_target`, so the tight resource grows. `q_ms` is 1 when a modeled resource has no headroom and incoming > 0. |
| 2 | Surplus scale-down (do not walk the last replica through μ=0) | `down_delta` / `beh_down` | Target `μ = Λ / (1-θ_free)`. Release only surplus; extras die only if remaining μ still covers that target. |
| 3 | BEH / vicinity / BEG pack leftover **above** min; BEV-up will not apply a resize that still has `μ = 0` | `beh.packed_spawn_size`, `place_packed_spawns`, `distribute_up` | New replicas must take routed load on the next tick. Cascade-home still places at minima (swap into just-freed floor room). |
| 4 | Coupled CPU/RAM surplus | `down_delta` | Idle RAM must not justify killing CPU the load still needs. |

TCN / hold-over-spike was **not** done. After (1)–(3) TCN already beat reactive
on the spikes. The remaining TCN-worse ticks were the RAM-dead attractors, which
(4) removed via surplus down (the old `protect_last_serving` floor clamp is gone).

---

## Results on MS_588 (same 3,385,510 incoming)

Same controller on MS_150: [30-alibaba-tcn-ms150-results.md](./30-alibaba-tcn-ms150-results.md).

| Run | Drop rate | Served | Zero-serve ticks | CPU-alive / RAM-dead ticks |
|---|---|---|---|---|
| TCN original (`42_20260816T083509Z`) | 69.11% | 1.05M | 331 | 344 (`c-api-1` at RAM 256) |
| TCN after (1)(2) (`42_20260816T094113Z`) | 45.29% | 1.85M | 0 | 59 |
| TCN after (3) (`42_20260816T100507Z`) | 14.15% | 2.91M | 0 | 202 |
| TCN after (4) (`42_20260816T102455Z`) | 7.85% | 3.12M | 0 | **0** |
| TCN after hold-over-spike (`42_20260816T104101Z`) | **3.79%** | 3.26M | 0 | 0 |
| reactive re-run (`42_20260816T100437Z`) | 15.44% | 2.86M | 5 | 10 |

Reactive moved slightly from the first recorded 15.11% because BEH now packs
the one spawn above min (`0.61 / 384` instead of `0.5 / 256`), which shifts
later downs. TCN after (4) still drops less on spikes than reactive (177k vs
334k). Remaining TCN drops are mostly those spikes (~66%).

After (3), every new TCN spawn served on its first live tick. After (4), no
BEV-down left RAM at 256 with CPU above min.

---

## Remaining ~8% (after (1)–(4))

Of the 7.85% at `42_20260816T102455Z`, **79% of drops were capacity-short**
(`μ < incoming`), not zombies. Conservation still held.

| Bucket | Drops | Share of 7.85% |
|---|---|---|
| Cold start τ=1–60 (TCN blind) | 56k | 1.66 pp — same as reactive |
| ≥15k spike ticks | 177k | 4.7 pp |
| Other | 33k | 1.0 pp (near-floor RAM 258 MB stealing CPU-weighted share) |

The TCN **does not see the spike in its 5-step horizon**. Hats 5 minutes before
a 25–30k spike are ~7–9k (MISS on 13/18). The one HINT at τ=76 was then
**blocked by `cooldown_C=5`** after an UP at τ=72. Grow landed *on* the spike
tick (apply τ+1), so the first minute still dropped. Then BEV-down 15–40 ticks
later stripped capacity, and the next 60-minute spike started low.

Holding peak μ for 60 ticks was worth ~4.25 pp on that run. Cluster max (8×4.0)
can serve every spike; nothing is physically unservable.

### Fixes for that remainder

| Change | Where | Why |
|---|---|---|
| Cooldown does not block scale-up | `policy.py` | Kubernetes HPA: scaleUp stabilization 0s. `cooldown_C` delays Down only. |
| Down sizes from surplus of serving capacity | `down_delta` | Stops RAM≈258 + CPU 2.8 (μ=140) from taking a full routing share. |

`hold_down_ticks` (block Down for 55 min after hot) was added here and later
**removed**. It is not Kubernetes CDT. HEAD uses `cooldown_C=5` for scale-down
only (HPA default 300s). The **3.79%** figure is the held run, not HEAD.

After the held run, remaining drops were almost entirely cold-start
(τ=21 still 18k on 2.0 cores) plus the first minute of later spikes. TCN
weights were not retrained.

---

Recorded totals for that 3.79% pair are in
[29-alibaba-tcn-s7-results.md](./29-alibaba-tcn-s7-results.md). Plots live under
gitignored `results/` and are not in git. Regenerate from HEAD:
[00-how-to-rerun-tests-and-graphs.md](./00-how-to-rerun-tests-and-graphs.md) §B6.

---

## Still open

- Cascade-home still spawns at MS minima (`check_cascading_migration`): the tick only proved floor room was freed. Vicinity / BEG now use `packed_spawn_size`.
- TCN still lags the 60-minute spike (5-step hats stay ~7–9k). The removed
  hold-over-spike covered the *next* cycle without using the forecast.
  Retrain / a longer horizon is the lever, not a 55-minute freeze.
- `sustained_steps: 99` stays BEV-first so a biased horizon does not skip
  vertical packing.
