# Triangle ladder slices — four topologies, one trace

**Status:** rerun 2026-09-18 after user-delay eval (prefer-local, triangle RTTs, mix p99)  
**Trace:** `traces/demo/api_400_triangle.csv` (Λ 40 → 180 by τ=200, 180 → 5 by τ=320, hold at 5)  
**Physics:** `cpu_min=0.5`, `cpu_max=1.0` ⇒ μ_max = 50 req/tick; peak 180 needs four full replicas  
**Related:** [32-tex-followups.md](./32-tex-followups.md), [18-mu-matched-cpu-ram-scale.md](./18-mu-matched-cpu-ram-scale.md), [17-surplus-down-resource-quantum-and-seed-log.md](./17-surplus-down-resource-quantum-and-seed-log.md), [16-s6-scale-down-reclaim.md](./16-s6-scale-down-reclaim.md)

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

Every slice: reclaim to **one** live replica in cluster `c1`, last alloc `> cpu_min`, leftover RAM near `ram_min + μ · ρ_ram` (not `ram_max`), no UP after the last extra terminate. Packed extras spawn above the floor (`cpu_new>0.50`) with RAM matched to that μ, not `α_up · seed RAM`.

Horizontal-only is the exception on *which* replica survives. Vicinity extras are a cheaper loan tier, so they die first and `c-api-0` on `c1-w1` remains. In-cluster extras are the same tier as the seed; among equal μ the ranker is `(q, -slack, container_id)`, so `c-api-0` can be reclaimed and the leftover sits on the fat sibling (`c1-w2`). That still satisfies LAST_REPLICA and surplus hold. Do not treat it as a keep-seed failure.

Borrowed reclaim shrinks first (`vicinity_down` onto the floor), then `vicinity_terminate`. That is ScheduleReleases, not a packed kill of a full replica.

`cascade_home` is **off** on all four. Surplus down skips VerticalScaling while extras exist and reclaims remotes first, so cascade-home has nothing to pull. That is a separate policy question, not a fifth topology.

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

Plots (needs matplotlib on `PYTHONPATH`):

```bash
python3 examples/compare_trace_vs_log.py <run_dir>
```

Look at `analysis/demo_app/ladder_qos.png`, `replicas_by_site.png`, and
`user_latency.png`. Long `unmet_demand` windows are drawn as a span, not one
vertical line per tick.

Alibaba regression (same one-cluster world, not a VicinityRound test):
`configs/12-demo_alibaba_reactive_local.yaml`.

---

## Recorded runs (seed 42, 2026-09-18)

Trace conservation holds on every slice: **33,412 incoming = served + dropped**.
Packed extras spawn at **0.75 / 268.5** and fill to **1.00 / 281**
(`ram_min + 50 × 0.5`). Surplus hold leaves **0.58 cores / 259.85 MB**
(`ram_min + μ · ρ_ram` with μ ≈ 8). Drop rates match the 2026-09-17 paper-match
rerun; what is new is user delay (`user_latency.png`).

Configs 16 / 18 / 19 set `latency_ms`: c1–c2 **5 ms**, c1–c3 **40 ms**,
c2–c3 **38 ms**. Horizontal (config 17) is one cluster, so \(T_{\mathrm{net}}=0\).

| Slice | Run dir | Drop | SLA miss | Extra spawn | Extra terminate | Leftover |
|---|---|---|---|---|---|---|
| Horizontal | `results/09-triangle-post-match/horizontal/42_20260918T150707Z` | 28 / 0.08% | 12.13% | 3× `horizontal_spawn` on `c1-w2` | 3× `horizontal_terminate` (includes seed `c-api-0`) | `c-api-c1-w2-3` on `c1-w2` |
| Vicinity | `results/09-triangle-post-match/vicinity/42_20260918T150708Z` | 28 / 0.08% | 31.02% | 3× `vicinity_spawn` on `c2-w1` | 3× `vicinity_down` then `vicinity_terminate` | `c-api-0` on `c1-w1` |
| Skip → unmet | `results/09-triangle-post-match/skip_neighbor/42_20260918T150708Z` | 17,806 / 53.29% | 78.50% | none | none | `c-api-0` on `c1-w1` |
| Vicinity then unmet | `results/09-triangle-post-match/vicinity_then_unmet/42_20260918T150709Z` | 6,752 / 20.21% | 61.28% | 1× `vicinity_spawn` on `c2` | 1× `vicinity_down` + `vicinity_terminate` | `c-api-0` on `c1-w1` |

UTC stamps in folder names will not match another machine. Prefer the latest `{seed}_{UTC}` dir under `results/09-triangle-post-match/`. August 2026 global-rung runs live under `results/06-triangle-beg-era/`; do not quote those numbers as current.

Drop is overflow (did not fit). SLA miss is overflow **plus** served-but-slower-than \(T_{\mathrm{slo}}=1\,\mathrm{s}\). Same drop on horizontal vs fat-vicinity, higher SLA miss on vicinity: prefer-local fills the one home replica first (that slice of traffic waits), leftover goes next door (\(T_{\mathrm{net}}=5\,\mathrm{ms}\) on c2). At peak \(\tau=200\), horizontal mean / p95 / p99 is **0.20 / 0.60 / 0.92 s** with no RTT; vicinity is **0.33 / 1.00 / 1.00 s** and demand-weighted \(T_{\mathrm{net}}\) is **3.6 ms**. The 5 ms hop is small next to the 1 s timeout; the extra miss is the stuffed-home wait, not the RTT. Skip / unmet SLA miss is mostly the drops.

Peak leftover at τ=200: **3** req/tick when four replicas fit, **80** when two fit (180−100), **130** when only the seed fits (180−50). Horizontal and fat-vicinity drops are the `x_up_streak` / apply-next-tick lag, not a capacity miss.

Vicinity extras after ScheduleReleases (shrink, then kill):

```
257  resize     c-api-c2-w1-1  vicinity_down
265  terminate  c-api-c2-w1-1  vicinity_terminate
279  resize     c-api-c2-w1-2  vicinity_down
287  terminate  c-api-c2-w1-2  vicinity_terminate
302  resize     c-api-c2-w1-3  vicinity_down
310  terminate  c-api-c2-w1-3  vicinity_terminate
```

Skip-neighbor logs `unmet_demand` from τ=18 through τ=288 and never places on c2 or c3.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v6 | 2026-09-18 | Rerun after user-delay eval; same drops; SLA miss / \(T_{\mathrm{net}}\) / `user_latency.png` |
| v5 | 2026-09-17 | Rerun after paper match; no global rung; `vicinity_up` / `vicinity_down`; recorded drop rates |
| v4 | 2026-08-20 | μ-matched CPU/RAM scale; leftover RAM ≈ 260 not 512 |
| v3 | 2026-08-20 | Recorded run dirs after terminate-reason fix; vicinity / skip-BEG / BEG CSVs stamp `vicinity_terminate` / `beg_terminate` |
| v2 | 2026-08-20 | Reclaim reasons match spawn rungs (`beg_terminate` / `vicinity_terminate`) |
| v1 | 2026-08-20 | BEH / vicinity / skip-BEG slices next to the full-ladder triangle |
