# Alibaba MS_150 — Option A TCN vs reactive (transfer)

Same 4×8-core world as [MS_588](./alibaba-tcn-s7-results.md) (`tick_sec=60`,
seed 42, initial replica `2.0 / 1024`). Same global TCN weights. Only the
trace and the per-MS min–max change (`models/tcn_delta_v1_ms150/`, 240–40083).
The recorded 4.40% TCN run was before faster scale-down (`α_down=1.0`).
HEAD is **4.71%** (0.49% after τ≥61). The 55-minute hold was never what held
this plateau; faster shrink now walks down in the two real valleys.

MS_150 is a different shape: 15,655,433 incoming (~4.6× MS_588), mean ~21.7k,
peak 40,083 at τ=183, and **no** 60-minute periodicity. It opens at 24,209
requests on 2.0 cores (μ=3,750), so the first minute already drops ~20k.

How to regenerate: [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md) §B7.

Overlay plots: [alibaba-story-plots.md](./alibaba-story-plots.md)
(`results/alibaba_ms150_proactive/42_20260817T105251Z/analysis/story/overview.png`).

## Current pair

| | Drop rate | Served | Dropped | Lives | OK actions |
|---|---|---|---|---|---|
| `reactive_local` `42_20260817T105247Z` | **5.51%** | 14,793,013 | 862,420 | 5 | 34 |
| proactive TCN `42_20260817T105251Z` | **4.71%** | 14,917,593 | 737,840 | 15 | 77 |

Incoming on both runs: 15,655,433. Trace vs sum(incoming) matched (max abs
diff 0). Usage never exceeded alloc. TCN had no RAM-dead attractor ticks;
reactive had 64 (those guards are proactive-only).

### Actions

| Kind | reactive_local | proactive TCN |
|---|---|---|
| BEV up | 24 | 49 |
| BEV down | 5 | 4 |
| BEH spawn | 4 | 14 |
| BEH terminate | 1 | 10 |

### Cold start vs after TCN wake-up

The first 60 ticks are **identical** (0 tick mismatches). TCN has no window
yet, so it is the same reactive ladder.

| Window | Incoming | reactive drop | TCN drop |
|---|---|---|---|
| τ=1…60 | 1,600,428 | 669,534 (**41.83%**) | 669,534 (**41.83%**) |
| τ=61…721 | 14,055,005 | 192,887 (**1.37%**) | 68,306 (**0.49%**) |

Most of TCN’s remaining whole-run drops are still the shared cold start. After
τ=60, TCN drops about **35%** of what reactive drops. The headline 5.51% vs
4.71% understates the post-warmup gap.

Faster shrink shows up in the two load valleys (τ≈150–180 and τ≈650): TCN now
cuts more cores there, so the return spike (τ=183, 40,083 incoming) can drop
more than the old plateau run.

Plots shade τ=1…60 as **no TCN** and annotate drop rate after τ=61. Regenerating
plots: [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md) §B7.

## What this is not

- Not a claim that MS_150 is an easier or harder *forecast* than MS_588.
  The TCN still lags; after τ=60 the win is packed BEH + no μ=0 downs, not a
  55-minute hold (this trace has no hourly quiet valley).
- Not a retune. A 60-minute-periodic sibling would be a closer shape match
  than this persistently high series.
