# Alibaba MS_588 — Option A TCN vs reactive

721 one-minute ticks from Alibaba cluster-trace-microservices-v2021. Same world
(4×8 cores, `tick_sec=60`). TCN is 60×2 → 5-step delta (`models/tcn_delta_v1`).

The first S7 integration run dropped **69%** under TCN vs **15%** under
`reactive_local`. That was a control-path mismatch with the usage model, not a
broken engine and not mainly the predictor. The diagnosis and the four fixes
are in [27-s7-proactive-drop-diagnosis.md](./27-s7-proactive-drop-diagnosis.md).

Trace vs sum(incoming) matched on every run below (max abs diff 0). Incoming
on all runs: 3,385,510.

## Current pair (K8s-style down: 5 min after Up, then 100%)

Scale-up is not delayed; `cooldown_C=5` delays the **first** Down after an Up
(HPA 300s window). `α_down = 1.0` then allows the full residual (HPA 100%
policy). Details: [28-s7-k8s-scale-cooldown.md](./28-s7-k8s-scale-cooldown.md).
Conservation holds (trace = incoming = served + dropped).

| | Drop rate | Served | Dropped | Lives | OK actions |
|---|---|---|---|---|---|
| `reactive_local` `42_20260817T105246Z` | **15.44%** | 2,862,823 | 522,687 | 2 | 49 |
| proactive TCN `42_20260817T105250Z` | **7.48%** | 3,132,439 | 253,071 | 19 | 118 |

After τ≥61 (TCN has hats): reactive **15.11%**, TCN **6.38%**. Mean CPU in that
window: oracle 2.41, reactive 3.24, TCN **7.42**.

Reactive’s one BEH spawn is packed above min (`0.61 / 384`).

### Actions (current pair)

| Kind | reactive_local | proactive TCN |
|---|---|---|
| BEV up | 23 | 72 |
| BEV down | 24 | 11 |
| BEH spawn | 1 | 18 |
| BEH terminate | 1 | 17 |

## Ladder of TCN runs

| Run | Drop rate | Zero-serve ticks | Notes |
|---|---|---|---|
| `42_20260816T083509Z` | 69.11% | 331 | First Option A wiring. RAM floor + min BEH. |
| `42_20260816T094113Z` | 45.29% | 0 | After decide-on-headroom + last-serving guard. |
| `42_20260816T100507Z` | 14.15% | 0 | After BEH-above-min. Still 202 RAM-dead attractor ticks. |
| `42_20260816T102455Z` | 7.85% | 0 | After no CPU-weighted `μ=0` downs. |
| `42_20260816T104101Z` | **3.79%** | 0 | Hold-over-spike (`hold_down_ticks=55`) + hot-UP cooldown bypass. Historical. |
| `42_20260817T102407Z` | **6.50%** | 0 | No hold; `cooldown_C` after every apply; `α_down=0.10` (stairs). |
| `42_20260817T105250Z` | **7.48%** | 0 | HEAD: `α_down=1.0`; cooldown after Up only. |

## Regenerating plots

Run directories are gitignored (`results/`). The `42_…Z` ids above are labels
for the recorded numbers, not files in the repo. A fresh clone gets new UTC
stamps; the drop rates should match this table.

How to regenerate: [00-how-to-rerun-tests-and-graphs.md](./00-how-to-rerun-tests-and-graphs.md) §B6.

Overlay of load, serve μ, forecast, and CPU given vs needed:
[31-alibaba-story-plots.md](./31-alibaba-story-plots.md)
(`analysis/story/overview.png` in each run dir).

TCN figures shade τ=1…60 (lookback, no hats; first apply at τ=61) and annotate
drop rate on that post-warmup window as well as the whole run.

The drop rates in the current-pair table should match a fresh §B6 run. The
**3.79%** and **6.50%** rows are historical (hold, then 10% stairs).

## What was copied from alibaba-trace

| Artifact | Role |
|---|---|
| `models/tcn_delta_v1/tcn_delta_weights.pth` | Global TCN weights (~30 KB) |
| `models/tcn_delta_v1/meta.json` | 60×2 → 5, time/720, MS_588 min=932 max=29778 |
| `traces/alibaba/MS_588.csv` | 721 rows, `time_unit=time_tick+1`, `requests=total_requests` |

The 47 MB full CSV and processed npy tensors stayed in `alibaba-trace`.

Same controller on **MS_150** (transfer, not a retune):
[30-alibaba-tcn-ms150-results.md](./30-alibaba-tcn-ms150-results.md).
