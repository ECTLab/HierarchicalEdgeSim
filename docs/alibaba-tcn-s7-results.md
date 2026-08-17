# Alibaba MS_588 — Option A TCN vs reactive

721 one-minute ticks from Alibaba cluster-trace-microservices-v2021. Same world
(4×8 cores, `tick_sec=60`). TCN is 60×2 → 5-step delta (`models/tcn_delta_v1`).

The first S7 integration run dropped **69%** under TCN vs **15%** under
`reactive_local`. That was a control-path mismatch with the usage model, not a
broken engine and not mainly the predictor. The diagnosis and the four fixes
are in [s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md).

Trace vs sum(incoming) matched on every run below (max abs diff 0). Incoming
on all runs: 3,385,510.

## Current pair (no 55-minute hold)

Scale-up is not delayed; `cooldown_C=5` delays scale-down only (Kubernetes HPA:
0s up / 300s down). Why, and vs the old 55-minute hold:
[s7-k8s-scale-cooldown.md](./s7-k8s-scale-cooldown.md). Conservation holds
(trace = incoming = served + dropped).

| | Drop rate | Served | Dropped | Lives | OK actions |
|---|---|---|---|---|---|
| `reactive_local` `42_20260817T102402Z` | **15.44%** | 2,862,823 | 522,687 | 2 | 49 |
| proactive TCN `42_20260817T102407Z` | **6.50%** | 3,165,404 | 220,106 | 21 | 133 |

After τ≥61 (TCN has hats): reactive **15.11%**, TCN **5.31%**. Mean CPU in that
window: oracle 2.41, reactive 3.24, TCN 8.63 (was 14.2 with `hold_down_ticks=55`).

Reactive’s one BEH spawn is packed above min (`0.61 / 384`).

### Actions (current pair)

| Kind | reactive_local | proactive TCN |
|---|---|---|
| BEV up | 23 | 66 |
| BEV down | 24 | 27 |
| BEH spawn | 1 | 20 |
| BEH terminate | 1 | 20 |

## Ladder of TCN runs

| Run | Drop rate | Zero-serve ticks | Notes |
|---|---|---|---|
| `42_20260816T083509Z` | 69.11% | 331 | First Option A wiring. RAM floor + min BEH. |
| `42_20260816T094113Z` | 45.29% | 0 | After decide-on-headroom + last-serving guard. |
| `42_20260816T100507Z` | 14.15% | 0 | After BEH-above-min. Still 202 RAM-dead attractor ticks. |
| `42_20260816T102455Z` | 7.85% | 0 | After no CPU-weighted `μ=0` downs. |
| `42_20260816T104101Z` | **3.79%** | 0 | Hold-over-spike (`hold_down_ticks=55`) + hot-UP cooldown bypass. Historical. |
| `42_20260817T102407Z` | **6.50%** | 0 | HEAD: no hold. `cooldown_C=5` delays Down only. |

## Regenerating plots

Run directories are gitignored (`results/`). The `42_…Z` ids above are labels
for the recorded numbers, not files in the repo. A fresh clone gets new UTC
stamps; the drop rates should match this table.

How to regenerate: [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md) §B6.

Overlay of load, serve μ, forecast, and CPU given vs needed:
[alibaba-story-plots.md](./alibaba-story-plots.md)
(`analysis/story/overview.png` in each run dir).

TCN figures shade τ=1…60 (lookback, no hats; first apply at τ=61) and annotate
drop rate on that post-warmup window as well as the whole run.

The drop rates in the current-pair table should match a fresh §B6 run. The
**3.79%** row is historical (`hold_down_ticks=55`).

## What was copied from alibaba-trace

| Artifact | Role |
|---|---|
| `models/tcn_delta_v1/tcn_delta_weights.pth` | Global TCN weights (~30 KB) |
| `models/tcn_delta_v1/meta.json` | 60×2 → 5, time/720, MS_588 min=932 max=29778 |
| `traces/alibaba/MS_588.csv` | 721 rows, `time_unit=time_tick+1`, `requests=total_requests` |

The 47 MB full CSV and processed npy tensors stayed in `alibaba-trace`.

Same controller on **MS_150** (transfer, not a retune):
[alibaba-tcn-ms150-results.md](./alibaba-tcn-ms150-results.md).
