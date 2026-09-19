# Triangle ladder slices — four topologies, one trace

**Status:** reactive rerun 2026-09-19 after leftover μ floor; proactive counterparts 2026-09-19 (`10-triangle-proactive/`)  
**Trace:** `traces/demo/api_400_triangle.csv` (Λ 40 → 180 by τ=200, 180 → 5 by τ=320, hold at 5)  
**Physics:** `cpu_min=0.5`, `cpu_max=1.0` ⇒ μ_max = 50 req/tick; peak 180 needs four full replicas  
**Reactive scaler:** `use_near_saturation_up: true`, `theta_high: 0.80` (also the prefer-local routing cap)  
**Proactive scaler:** `proactive_auto_scaler` persistence (`feature_window=10`, `theta_target=0.60`); same ladder knobs; `sim.theta_route: 0.80`  
**Related:** [32-tex-followups.md](./32-tex-followups.md), [08-reactive-local-params.md](./08-reactive-local-params.md), [18-mu-matched-cpu-ram-scale.md](./18-mu-matched-cpu-ram-scale.md), [17-surplus-down-resource-quantum-and-seed-log.md](./17-surplus-down-resource-quantum-and-seed-log.md), [16-s6-scale-down-reclaim.md](./16-s6-scale-down-reclaim.md)

The original triangle demo (`16-demo_400_triangle.yaml`) is one topology: one
tiny home worker, one tiny neighbor, and an outside cluster that is **not**
used (leftover is `unmet_demand`). That is the **vicinity-terminal** control.
It does not prove local HorizontalScaling, a fat vicinity, or skipping a
floor-only neighbor. Those are separate slices.

Do **not** grow this into a large matrix. Four synthetics plus the existing
Alibaba `reactive_local` re-run are enough to trust packed spawn, VicinityRound,
and surplus reclaim. 60-tick demos still exist as smoke; they do not hold long
enough for surplus reclaim.

The paper’s ladder stops at VicinityRound. There is no BEG / global spawn.
Action reasons are `vertical_*`, `horizontal_*`, `vicinity_*`, `unmet_demand`.

---

## The four synthetics

| Config | Isolates | Topology | Must see | Must not see |
|---|---|---|---|---|
| `17-demo_400_triangle_horizontal.yaml` | In-cluster HorizontalScaling | c1-w1 filled (1.0); empty sibling c1-w2 (8.0); no vicinities | `horizontal_spawn` / `horizontal_terminate` on `c1-w2`; leftover on c1 | `vicinity_*`, `unmet_demand` |
| `18-demo_400_triangle_vicinity.yaml` | Packed VicinityRound | c1 filled; fat c2 (8.0) in v1; no c3 | `vicinity_spawn` / `vicinity_up` / `vicinity_terminate` on c2, `cpu_new>0.50` | `horizontal_spawn` |
| `19-demo_400_triangle_skip_neighbor.yaml` | Floor skip → unmet | c1 filled; c2=0.4 (below min); fat c3 outside v1 | `unmet_demand`; no spawn on c2 or c3 | `vicinity_spawn` |
| `16-demo_400_triangle.yaml` | Vicinity then unmet | c1 1.0 + c2 1.0 + unused c3 | one vicinity spawn **and** terminate; `unmet_demand` | spawn on c3 |

Proactive twins (same worlds): `23` / `24` / `25` / `22`. Fat vicinity may log a few one-tick `unmet_demand` leftovers from a large PredictAndDecide residual; drops stay zero.

Every slice: reclaim to **one** live replica in cluster `c1`, last alloc `> cpu_min`, leftover RAM near `ram_min + μ · ρ_ram` (not `ram_max`), no UP after the last extra terminate. Packed extras spawn above the floor (`cpu_new>0.50`) with RAM matched to that μ, not `α_up · seed RAM`.

Horizontal-only is the exception on *which* replica survives. Vicinity extras are a cheaper loan tier, so they die first and `c-api-0` on `c1-w1` remains. In-cluster extras are the same tier as the seed; rank is
`(μ, q, -slack, container_id)`, so `c-api-0` can be peeled and then
reclaimed and the leftover sits on the fat sibling (`c1-w2`). That still satisfies LAST_REPLICA and surplus hold. Do not treat it as a keep-seed failure.

Borrowed reclaim shrinks first (`vicinity_down` onto the floor), then `vicinity_terminate`. That is ScheduleReleases, not a packed kill of a full replica.

`cascade_home` is **off** on all four. Surplus down peels the extra we would
reclaim, then terminates it **next tick** once it is at the floor (even during
cooldown). Remotes still go first via ScheduleReleases, so cascade-home has
nothing to pull. That is a separate policy question, not a fifth topology.

---

## Terminate reasons match spawn rungs

Scale-up stamps the rung (`horizontal_spawn` / `vicinity_spawn`). Scale-in stamps the same key. Grow on an existing loan is `vicinity_up`; shrink before terminate is `vicinity_down`.

| Loan rung | Spawn | Grow | Terminate |
|---|---|---|---|
| Vicinity | `vicinity_spawn` | `vicinity_up` | `vicinity_down` then `vicinity_terminate` |
| In-cluster extra | `horizontal_spawn` | `vertical_up` | `horizontal_terminate` |

`cascade_terminate` is migrate-home, not this reclaim path.

---

## How to run

```bash
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/17-demo_400_triangle_horizontal.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/18-demo_400_triangle_vicinity.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/19-demo_400_triangle_skip_neighbor.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/16-demo_400_triangle.yaml
```

Proactive counterparts (same worlds, persistence, `sim.theta_route: 0.80`): `23` / `24` / `25` / `22`. Outputs: `results/10-triangle-proactive/<slice>/`.

Plots (needs matplotlib on `PYTHONPATH`):

```bash
python3 examples/compare_trace_vs_log.py <run_dir>
```

Look at `analysis/demo_app/ladder_qos.png`, `replicas_by_site.png`, and
`user_latency.png`. Proactive runs also write `forecast_vs_actual.png` (trace
vs t+1 / t+H hats; grey band is cold start with no forecast). Long
`unmet_demand` windows are drawn as a span, not one vertical line per tick.

Alibaba regression (same one-cluster world, not a VicinityRound test):
`configs/12-demo_alibaba_reactive_local.yaml`.

---

## Recorded runs (seed 42, 2026-09-19T170902Z–T170919Z)

Trace conservation holds on every slice: **33,412 incoming = served + dropped**.
Near-saturation up (`theta_high=0.80`) plus prefer-local **util cap** (home to \(0.80\mu\), leftover to loans, leftover home band only if loans are full). Packed extras spawn at **0.75 / 268.5** and fill to **1.00 / 281**. Surplus hold now leaves **0.75 cores / 268.50 MB** (μ=25 = `min_mu_step`): relative \(\theta_{\mathrm{free}}\) alone would have parked leftover at μ≈8, where M/M/1 p99 is ~1.5 s. First extra (or first `unmet_demand`) is **τ=3** because start Λ=40 already sits on \(\theta_{\mathrm{high}}\) of the seed (μ=50).

Configs 16 / 18 / 19 set `latency_ms`: c1–c2 **5 ms**, c1–c3 **40 ms**,
c2–c3 **38 ms**. Horizontal (config 17) is one cluster, so \(T_{\mathrm{net}}=0\).

| Slice | Run dir | Drop | SLA miss | Extra spawn | Extra terminate | Leftover |
|---|---|---|---|---|---|---|
| Horizontal | `results/09-triangle-post-match/horizontal/42_20260919T170902Z` | 4 / 0.01% | 0.51% | 4× `horizontal_spawn` on `c1-w2` | peel then next-tick `horizontal_terminate` (includes seed `c-api-0`) | `c-api-c1-w2-3` on `c1-w2` |
| Vicinity | `results/09-triangle-post-match/vicinity/42_20260919T170909Z` | 0 / 0.00% | 0.02% | 4× `vicinity_spawn` on `c2-w1` | 4× `vicinity_down` then `vicinity_terminate` | `c-api-0` on `c1-w1` |
| Skip → unmet | `results/09-triangle-post-match/skip_neighbor/42_20260919T170915Z` | 17,806 / 53.29% | 78.42% | none | none | `c-api-0` on `c1-w1` |
| Vicinity then unmet | `results/09-triangle-post-match/vicinity_then_unmet/42_20260919T170919Z` | 6,743 / 20.18% | 53.25% | 1× `vicinity_spawn` on `c2` | 1× `vicinity_down` + `vicinity_terminate` | `c-api-0` on `c1-w1` |

Compare to greedy fill-to-μ with the same scaler (`42_20260919T1608*`): drops unchanged; fat-vicinity SLA miss **25.21% → 0.02%**. Quiet-hold SLA miss on that vicinity run was ~6.5% (μ=8 leftover); it is now **0%** (μ=25, p99=0.23 s). At τ=16 (Λ=51, home μ=50, one packed loan) home gets **40** and the loan **11** (was 50 / 1). Drop-only fill-to-μ from 18 Sep is `42_20260918T1916*` (28 drops, vicinity SLA 31.02%).

UTC stamps in folder names will not match another machine. Prefer the latest `{seed}_{UTC}` dir under `results/09-triangle-post-match/`. August 2026 global-rung runs live under `results/06-triangle-beg-era/`; do not quote those numbers as current.

Drop is overflow (did not fit). SLA miss is overflow **plus** served-but-slower-than \(T_{\mathrm{slo}}=1\,\mathrm{s}\). Horizontal is one pool (no prefer-local split), so the util cap does not apply; remaining 0.51% SLA is the early extra-spawn wobble. Fat vicinity now keeps home at \(\rho=0.80\) while loans have room: at peak \(\tau=200\), demand-weighted mean / p95 / p99 is **0.08 / 0.22 / 0.34 s** (horizontal) and **0.12 / 0.34 / 0.52 s** (vicinity, including 5 ms \(T_{\mathrm{net}}\)). Skip / unmet SLA miss is still mostly the drops. Vicinity-then-unmet improves only while the one loan has spare μ; after that both replicas run full and leftover is unmet.

Peak leftover at τ=200: **0** req/tick when five replicas cover 180 at 80% (horizontal / fat vicinity), **80** when two fit (180−100), **130** when only the seed fits (180−50). Horizontal’s 4 drops are the `x_up_streak` / apply-next-tick lag, not a capacity miss.

Horizontal extras after next-tick floor-kill (fourth extra dies first; leftover still `c-api-c1-w2-3`):

```
221  resize     c-api-c1-w2-4   vertical_down     0.97 → 0.79
229  terminate  c-api-c1-w2-4   horizontal_terminate
241  resize     c-api-0         vertical_down     1.00 → 0.85
249  resize     c-api-0         vertical_down     0.85 → 0.68
257  resize     c-api-0         vertical_down     0.68 → 0.50
258  terminate  c-api-0         horizontal_terminate
266  resize     c-api-c1-w2-1   vertical_down     1.00 → 0.79
274  resize     c-api-c1-w2-1   vertical_down     0.79 → 0.61
282  resize     c-api-c1-w2-1   vertical_down     0.61 → 0.50
283  terminate  c-api-c1-w2-1   horizontal_terminate
291  resize     c-api-c1-w2-2   vertical_down     1.00 → 0.72
299  resize     c-api-c1-w2-2   vertical_down     0.72 → 0.55
307  resize     c-api-c1-w2-2   vertical_down     0.55 → 0.50
308  terminate  c-api-c1-w2-2   horizontal_terminate
316  resize     c-api-c1-w2-3   vertical_down     1.00 → 0.75   leftover hold
```

Vicinity extras after ScheduleReleases (four loans; shrink, then kill):

```
246  resize     c-api-c2-w1-1  vicinity_down
254  terminate  c-api-c2-w1-1  vicinity_terminate
268  resize     c-api-c2-w1-2  vicinity_down
276  terminate  c-api-c2-w1-2  vicinity_terminate
291  resize     c-api-c2-w1-3  vicinity_down
299  terminate  c-api-c2-w1-3  vicinity_terminate
307  resize     c-api-c2-w1-4  vicinity_down
315  terminate  c-api-c2-w1-4  vicinity_terminate
323  resize     c-api-0        vertical_down      1.00 → 0.75   leftover hold
```

Skip-neighbor logs `unmet_demand` from τ=3 through τ=296 and never places on c2 or c3.

---

## Proactive recorded runs (seed 42, 2026-09-19T184228Z–T184248Z)

Same four topologies and trace; scaler is `proactive_auto_scaler` with **persistence** (`feature_window=10`, `forecast_horizon=3`, `theta_target=0.60`). Ladder knobs match the reactive slices (`cascade_home: false`, `use_near_saturation_up: true`, `theta_high: 0.80`, leftover μ floor). Routing cap is `sim.theta_route: 0.80` because proactive has no top-level `theta_high`. Cold start is reactive streaks until τ=10; first extra is still **τ=3**.

Configs: `23` horizontal, `24` fat vicinity, `25` skip, `22` vicinity then unmet. Outputs under `results/10-triangle-proactive/`.

| Slice | Run dir | Drop | SLA miss | Extra spawn | Extra terminate | Leftover |
|---|---|---|---|---|---|---|
| Horizontal | `results/10-triangle-proactive/horizontal/42_20260919T184228Z` | 0 / 0.00% | 0.11% | 6× `horizontal_spawn` on `c1-w2` | peel then next-tick `horizontal_terminate` (includes seed `c-api-0`) | `c-api-c1-w2-5` on `c1-w2` |
| Vicinity | `results/10-triangle-proactive/vicinity/42_20260919T184237Z` | 0 / 0.00% | 0.00% | 4× `vicinity_spawn` on `c2-w1` | 4× `vicinity_down` / `vicinity_terminate` | `c-api-0` on `c1-w1` |
| Skip → unmet | `results/10-triangle-proactive/skip_neighbor/42_20260919T184244Z` | 17,806 / 53.29% | 78.42% | none | none | `c-api-0` on `c1-w1` |
| Vicinity then unmet | `results/10-triangle-proactive/vicinity_then_unmet/42_20260919T184248Z` | 6,743 / 20.18% | 53.25% | 1× `vicinity_spawn` on `c2` | 1× `vicinity_down` + `vicinity_terminate` | `c-api-0` on `c1-w1` |

Skip / vicinity-then-unmet drop and SLA match reactive: those slices are capacity-bound (seed μ=50, or seed+one loan μ=100). Horizontal and fat vicinity cover the climb with **zero drops**. Quiet hold is again **0.75 / 268.50** (μ=25, p99=0.23 s).

`theta_target=0.60` asks for more serving μ than reactive `theta_high=0.80`, so horizontal packed **six** extras (two in one window at τ=147) instead of four. Fat vicinity still stops at four loans once measured \(q\) sits between \(\theta_{\mathrm{target}}\) and \(\theta_{\mathrm{up}}\). Three one-tick `unmet_demand` logs on fat vicinity (τ=58, 96, 147) are leftover residual after that window’s packed spawn; the next window continues and **no request drops**. Horizontal logs three `need_vicinity_help` on the same ticks (no \(V\) to send them to).

Peak \(\tau=200\) demand-weighted mean / p95 / p99: **0.12 / 0.35 / 0.52 s** (horizontal) and **0.09 / 0.27 / 0.41 s** (vicinity).

---

## Document history

| Version | Date | Note |
|---|---|---|
| v12 | 2026-09-19 | Proactive persistence counterparts (`22`–`25`); `10-triangle-proactive/` (`42_20260919T184228Z`–`T184248Z`) |
| v11 | 2026-09-19 | Leftover μ floor (`min_mu_step` + p99 ≤ \(T_{\mathrm{slo}}/2\)); hold p99 1.5 s → 0.23 s (`42_20260919T170902Z`–`T170919Z`) |
| v10 | 2026-09-19 | Prefer-local util cap + `theta_high=0.80`; vicinity SLA 25% → 0.09% (`42_20260919T162711Z`–`T162728Z`) |
| v9 | 2026-09-18 | Next-tick floor-kill on local extras (`42_20260918T191645Z`–`T191647Z`); vicinity/skip/unmet unchanged |
| v8 | 2026-09-18 | Rerun after `min_mu_step`; identical to v7 (`42_20260918T184024Z` / `T184025Z`) |
| v7 | 2026-09-18 | Peel-then-terminate on local extras; same drops/SLA; horizontal descent stairs |
| v6 | 2026-09-18 | Rerun after user-delay eval; same drops; SLA miss / \(T_{\mathrm{net}}\) / `user_latency.png` |
| v5 | 2026-09-17 | Rerun after paper match; no global rung; `vicinity_up` / `vicinity_down`; recorded drop rates |
| v4 | 2026-08-20 | μ-matched CPU/RAM scale; leftover RAM ≈ 260 not 512 |
| v3 | 2026-08-20 | Recorded run dirs after terminate-reason fix; vicinity / skip-BEG / BEG CSVs stamp `vicinity_terminate` / `beg_terminate` |
| v2 | 2026-08-20 | Reclaim reasons match spawn rungs (`beg_terminate` / `vicinity_terminate`) |
| v1 | 2026-08-20 | BEH / vicinity / skip-BEG slices next to the full-ladder triangle |
