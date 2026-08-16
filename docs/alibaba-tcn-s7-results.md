# Alibaba MS_588 — Option A TCN vs reactive

721 one-minute ticks from Alibaba cluster-trace-microservices-v2021. Same world
(4×8 cores, `tick_sec=60`). TCN is 60×2 → 5-step delta (`models/tcn_delta_v1`).

The first S7 integration run dropped **69%** under TCN vs **15%** under
`reactive_local`. That was a control-path mismatch with the usage model, not a
broken engine and not mainly the predictor. The diagnosis and the four fixes
are in [s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md).

Trace vs sum(incoming) matched on every run below (max abs diff 0). Incoming
on all runs: 3,385,510.

## Current pair (after control fixes)

| | Drop rate | Served | Dropped | Lives | OK actions |
|---|---|---|---|---|---|
| `reactive_local` `42_20260816T100437Z` | **15.44%** | 2,862,823 | 522,687 | 2 | 49 |
| proactive TCN `42_20260816T102455Z` | **7.85%** | 3,119,652 | 265,858 | 7 | 74 |

Reactive’s one BEH spawn is now packed above min (`0.61 / 384`), so this
baseline is not identical to the first 15.11% recording.

### Actions (current pair)

| Kind | reactive_local | proactive TCN |
|---|---|---|
| BEV up | 23 | 38 |
| BEV down | 24 | 25 |
| BEH spawn | 1 | 6 |
| BEH terminate | 1 | 5 |

## Ladder of TCN runs

| Run | Drop rate | Zero-serve ticks | Notes |
|---|---|---|---|
| `42_20260816T083509Z` | 69.11% | 331 | First Option A wiring. RAM floor + min BEH. |
| `42_20260816T094113Z` | 45.29% | 0 | After decide-on-headroom + last-serving guard. |
| `42_20260816T100507Z` | 14.15% | 0 | After BEH-above-min. Still 202 RAM-dead attractor ticks. |
| `42_20260816T102455Z` | **7.85%** | 0 | After no CPU-weighted `μ=0` downs. |

## Run directories (local, gitignored)

- Reactive: `results/alibaba_reactive_local/42_20260816T100437Z/analysis/demo_app/`
- TCN: `results/alibaba_proactive/42_20260816T102455Z/analysis/demo_app/`
- Comparison: `results/alibaba_proactive/42_20260816T102455Z/analysis/baseline_comparison.png`
- TCN vs incoming: `…/analysis/demo_app/tcn_forecast.png`

How to regenerate: [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md) §B6.

## What was copied from alibaba-trace

| Artifact | Role |
|---|---|
| `models/tcn_delta_v1/tcn_delta_weights.pth` | Global TCN weights (~30 KB) |
| `models/tcn_delta_v1/meta.json` | 60×2 → 5, time/720, MS_588 min=932 max=29778 |
| `traces/alibaba/MS_588.csv` | 721 rows, `time_unit=time_tick+1`, `requests=total_requests` |

The 47 MB full CSV and processed npy tensors stayed in `alibaba-trace`.
