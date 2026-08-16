# Alibaba MS_150 — Option A TCN vs reactive (transfer)

Same 4×8-core world as [MS_588](./alibaba-tcn-s7-results.md) (`tick_sec=60`,
seed 42, initial replica `2.0 / 1024`). Same global TCN weights. Only the
trace and the per-MS min–max change (`models/tcn_delta_v1_ms150/`, 240–40083).
`hold_down_ticks=55` is the MS_588 controller transferred, not retuned.

MS_150 is a different shape: 15,655,433 incoming (~4.6× MS_588), mean ~21.7k,
peak 40,083 at τ=183, and **no** 60-minute periodicity. It opens at 24,209
requests on 2.0 cores (μ=3,750), so the first minute already drops ~20k.

How to regenerate: [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md) §B7.

## Current pair

| | Drop rate | Served | Dropped | Lives | OK actions |
|---|---|---|---|---|---|
| `reactive_local` `42_20260816T114246Z` | **5.51%** | 14,793,013 | 862,420 | 5 | 34 |
| proactive TCN `42_20260816T114309Z` | **4.40%** | 14,966,340 | 689,093 | 8 | 38 |

Incoming on both runs: 15,655,433. Trace vs sum(incoming) matched (max abs
diff 0). Usage never exceeded alloc. TCN had no RAM-dead attractor ticks;
reactive had 64 (those guards are proactive-only).

### Actions

| Kind | reactive_local | proactive TCN |
|---|---|---|
| BEV up | 24 | 22 |
| BEV down | 5 | 6 |
| BEH spawn | 4 | 7 |
| BEH terminate | 1 | 3 |

### Cold start vs after TCN wake-up

The first 60 ticks are **identical** (0 tick mismatches). TCN has no window
yet, so it is the same reactive ladder.

| Window | Incoming | reactive drop | TCN drop |
|---|---|---|---|
| τ=1…60 | 1,600,428 | 669,534 (**41.83%**) | 669,534 (**41.83%**) |
| τ=61…721 | 14,055,005 | 192,887 (**1.37%**) | 19,559 (**0.14%**) |

97% of TCN’s remaining whole-run drops are that shared cold start. After
τ=60, TCN drops about **10%** of what reactive drops. The headline 5.51% vs
4.40% understates the post-warmup gap.

The leftover TCN red spike is the return from the τ≈150–180 valley: hold
lets BEV-down walk sum CPU from ~21 to ~11, then τ=183 hits 40,083. Reactive
drops 20,673 there; TCN drops 11,237.

Plots shade τ=1…60 as **no TCN** and annotate drop rate after τ=61. Regenerating
plots: [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md) §B7.

## What this is not

- Not a claim that MS_150 is an easier or harder *forecast* than MS_588.
  The TCN still lags; the win after τ=60 is hold + packed BEH + no μ=0 downs.
- Not a retune. A 60-minute-periodic sibling would be a closer shape match
  than this persistently high series.
