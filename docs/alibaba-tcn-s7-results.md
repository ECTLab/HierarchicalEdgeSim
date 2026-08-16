# Alibaba MS_588 — Option A TCN vs reactive

Recorded from the S7 integration runs (same numbers as the session canvas).
721 one-minute ticks from Alibaba cluster-trace-microservices-v2021. Same world
(4×8 cores, `tick_sec=60`). TCN is 60×2 → 5-step delta (`models/tcn_delta_v1`).

Trace vs sum(incoming) matched on both runs (max abs diff 0). Physics is honest;
the gap is policy + forecast, not a missing log.

| | Drop rate | Served | Dropped | Lives logged | OK actions |
|---|---|---|---|---|---|
| `reactive_local` | **15.11%** | 2,874,064 | 511,446 | 2 | 51 |
| proactive TCN | **69.11%** | 1,045,771 | 2,339,739 | 7 | 60 |

Incoming on both: 3,385,510.

## Actions

| Kind | reactive_local | proactive TCN |
|---|---|---|
| BEV up | 24 | 35 |
| BEV down | 25 | 14 |
| BEH spawn | 1 | 6 |
| BEH terminate | 1 | 5 |

Reactive first grow at τ=27 (cold-start streak). One spawn, one terminate.
Capacity stays on the home replica.

Proactive: same cold-start ups at τ=27 and 32. First TCN apply at τ=60 (window
full). Hits `cpu_max` at τ=72 and spawns; a trough then BEV-downs the serving
replica (τ=159–180).

## Why TCN loses on this series

The TCN still lags spikes and sits high on the baseline (asymmetric training).
That turns into extra BEV-down after each burst and `cpu_min` BEH replicas that
cannot serve until a later BEV. Reactive only grows on observed drops and
shrinks on an 8-tick streak, so it holds capacity through the periodic 25–30k
spikes.

Full decide residual was clipped to one `α` step per decision. Without that
clip, lite BEH spawned `remain/cpu_min` idle replicas (~80% drops, 300+ lives).

## Run directories (local, gitignored)

- Reactive: `results/alibaba_reactive_local/42_20260816T083130Z/analysis/demo_app/`
- TCN: `results/alibaba_proactive/42_20260816T083509Z/analysis/demo_app/`
- Comparison: `results/alibaba_proactive/42_20260816T083509Z/analysis/baseline_comparison.png`
- TCN vs incoming: `…/analysis/demo_app/tcn_forecast.png`

## What was copied from alibaba-trace

| Artifact | Role |
|---|---|
| `models/tcn_delta_v1/tcn_delta_weights.pth` | Global TCN weights (~30 KB) |
| `models/tcn_delta_v1/meta.json` | 60×2 → 5, time/720, MS_588 min=932 max=29778 |
| `traces/alibaba/MS_588.csv` | 721 rows, `time_unit=time_tick+1`, `requests=total_requests` |

The 47 MB full CSV and processed npy tensors stayed in `alibaba-trace`.
