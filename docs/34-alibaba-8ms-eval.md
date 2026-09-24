# Alibaba 8-MS vicinity evaluation (campaign 14)

**Traces:** eight 721-minute Alibaba series in `traces/alibaba/`  
**Physics:** same as campaign 11 (`cpu_min=0.5`, `cpu_max=4.0`, \(\rho_{\mathrm{cpu}}=0.0004\))  
**Pool:** 80 cores — home `c1` 5×8, neighbor `c2` 5×8, vicinity `v1`  
**Campaign:** `results/14-alibaba-8ms-eval/`  
**Configs:** `43` reactive, `44` persistence, `45` Kubernetes HPA, `46` ProScale-style, `47` per-MS TCN  
**Related:** [36-alibaba-4ms-eval.md](./36-alibaba-4ms-eval.md) (four MS)

One app, eight microservices. The pool is written from the packed sweet spot at \(\theta=0.60\): the sitting group (ms150, ms133, ms693, ms859, ms460) averages 36.0 cores, so a 40-core home fits that mean, and the two needles still peak together at 26.1 and cannot both sit there with the sitters. Neighbor 40 cores makes the pool 80, which covers the eight-way sweet-spot max of 75. Same seeds (2.0/1024), \(\theta_{\mathrm{route}}=0.80\), and 5.0 ms between `c1` and `c2` on every slice. `cascade_home: true` on the ladder. Cold start on 44 and 47 is reactive until \(\tau=60\). HPA and ProScale scale from the first tick and never resize. The hog has its own worker.

| Config | Isolates |
|---|---|
| `43-demo_alibaba_8ms_sized_reactive.yaml` | Ladder + vicinity, no hats |
| `44-demo_alibaba_8ms_sized_persistence.yaml` | Same world, last-value hats, \(W=60\), \(H=5\) |
| `45-demo_alibaba_8ms_sized_hpa.yaml` | Kubernetes HPA replica formula, home `c1` only |
| `46-demo_alibaba_8ms_sized_proscale.yaml` | SMA \(N=2\), seed-sized pods, greedy `c1` then `c2`, no reserve |
| `47-demo_alibaba_8ms_sized_tcn.yaml` | Same ladder as 44; one residual TCN per MS |

| MS | Shape | Forecast |
|---|---|---|
| `ms150` | Always-on hog | `models/tcn_delta_ms150_v3` (rebound) |
| `ms588` | Hourly needle, minute 20 | `models/tcn_delta_ms588_v2` |
| `ms215` | Hourly plateau, minute 3 | `models/tcn_delta_ms215_v1` |
| `ms693` | 3-minute sawtooth | `models/tcn_delta_ms693_v1` |
| `ms133` | Flat ~1.6k | `models/tcn_delta_ms133_v1` |
| `ms205` | Four irregular bursts, no stable minute | `models/tcn_delta_ms205_v1` (rebound) |
| `ms460` | Mixed, 16 rises above 4k | `models/tcn_delta_ms460_v1` (rebound) |
| `ms859` | Smooth diurnal, lag-1 0.995 | `models/tcn_delta_ms859_v1` |

Full-trace replay, same denormalization the simulator uses. ms133 is nearly last-value (t+1 MAE 106 vs 101; horizon-max 108 vs 132). ms859 does not beat last-value (t+1 188 vs 112; horizon-max bias about +200 requests). ms205’s rebound net misses all four jumps at t+1 (0/4 half-lead) and sits about +2400 requests high on the horizon max in calm minutes. ms460 leads 10 of 13 jumps above 4k and cuts horizon-max error from 1762 to 997. Same-day fit, as on the other four networks.

## How to run

Configs 43–46 do not need torch. Config 47 does.

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

VR=$(.venv/bin/python examples/run_with_autoscaler.py configs/43-demo_alibaba_8ms_sized_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VP=$(.venv/bin/python examples/run_with_autoscaler.py configs/44-demo_alibaba_8ms_sized_persistence.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VH=$(.venv/bin/python examples/run_with_autoscaler.py configs/45-demo_alibaba_8ms_sized_hpa.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VS=$(.venv/bin/python examples/run_with_autoscaler.py configs/46-demo_alibaba_8ms_sized_proscale.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VT=$(.venv/bin/python examples/run_with_autoscaler.py configs/47-demo_alibaba_8ms_sized_tcn.yaml | sed -n 's/^Run complete. Outputs written to: //p')

.venv/bin/python examples/compare_trace_vs_log.py "$VR"
.venv/bin/python examples/compare_trace_vs_log.py "$VP"
.venv/bin/python examples/compare_trace_vs_log.py "$VH"
.venv/bin/python examples/compare_trace_vs_log.py "$VS"
.venv/bin/python examples/compare_trace_vs_log.py "$VT"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run vicinity_tcn "$VT" \
  --run vicinity_hpa "$VH" \
  --run vicinity_reactive "$VR" \
  --run vicinity_proscale "$VS" \
  --run vicinity_persistence "$VP"
```

Plots: per-MS `user_latency_<ms>.png` under each run’s `analysis/demo_app/`, plus `analysis/baseline_comparison.png` and `analysis/story/`.

## Recorded runs (seed 42)

Incoming **42,157,830** on every slice (MS_133 1,134,212 + MS_150 15,655,433 + MS_205 2,792,732 + MS_215 3,261,851 + MS_460 5,231,829 + MS_588 3,385,510 + MS_693 4,102,891 + MS_859 6,593,372; conservation holds). Reactive, persistence, and TCN drop the same requests for \(\tau\le 60\) (590,766). HPA and ProScale do not share that cold start.

| Slice | Run dir | Drop | After τ≥61 | SLA miss | Peak live | Vicinity spawn | Mean cores |
|---|---|---|---|---|---|---|---|
| Vicinity HPA | `vicinity_hpa/42_20260924T095523Z` | 6,334,875 / **15.03%** | 14.52% | 33.24% | 20 at τ=4 (20 home / 0 c2) | **0** | 39.7 |
| Vicinity reactive | `vicinity_reactive/42_20260924T095349Z` | 4,022,411 / **9.54%** | 9.09% | 16.89% | 23 at τ=127 (16 home / 7 c2) | 36 | 39.3 |
| Vicinity ProScale | `vicinity_proscale/42_20260924T095526Z` | 1,661,708 / **3.94%** | 3.99% | 19.00% | 29 at τ=8 (20 home / 9 c2) | 171 | 40.0 |
| Vicinity persistence | `vicinity_persistence/42_20260924T095353Z` | 1,338,546 / **3.18%** | 1.98% | 5.77% | 41 at τ=367 (19 home / 22 c2) | 233 | 58.7 |
| Vicinity TCN | `vicinity_tcn/42_20260924T104509Z` | 1,036,962 / **2.46%** | **1.18%** | 4.48% | 37 at τ=435 (16 home / 21 c2) | 172 | **66.2** |

HPA logged **1,460** `unmet_demand` and never left `c1` (c2 CPU 0, peak allocated CPU 40, which is 20 seed-sized pods). ProScale logged no `unmet_demand` and no resize; it spawned on `c2` 171 times and terminated all 171. Its c2 mean is 4.1 cores and its c2 peak is 18. Persistence and TCN both fill the pool (peak allocated CPU 80, c2 peak 40). Persistence c2 mean is 19.6 cores; TCN c2 mean is 26.6. Persistence logs 184 `unmet_demand` and the eight-net TCN logs 227, on minutes when the horizon asks for more than 80 cores. Mean cores are the average over ticks of the sum of container `cpu_capacity`.

Per-MS drop (whole run):

| MS | HPA | Reactive | ProScale | Persistence | TCN |
|---|---|---|---|---|---|
| ms133 (flat) | 0.00% | 0.03% | 0.00% | **0.00%** | **0.00%** |
| ms150 (hog) | 19.42% | 1.67% | 3.52% | 0.98% | **0.66%** |
| ms205 (bursts) | 7.47% | 5.01% | 2.63% | 0.94% | **0.26%** |
| ms215 (minute 3) | 61.48% | 39.27% | **12.11%** | 17.23% | 19.17% |
| ms460 (mixed) | 11.98% | 3.07% | 2.59% | 1.16% | **1.07%** |
| ms588 (minute 20) | 10.65% | 13.30% | 8.48% | 7.17% | **1.28%** |
| ms693 (sawtooth) | 1.20% | 40.36% | 5.05% | 5.41% | **3.15%** |
| ms859 (diurnal) | 0.65% | 1.10% | **0.19%** | 1.10% | 1.10% |

Persistence takes ms215 from 39.27% to 17.23%. The eight-net TCN does not: ms215 is 19.17%. After τ≥61 the ms215 counts are ProScale 354,456, persistence 364,479, TCN 427,717. The extra loss is the shared pool. ms205’s rebound horizon sits about 2,400 requests high in calm minutes and does not lead its four jumps, so those cores are taken before the minute-3 needle. ms588 after τ≥61 is 4,144 requests under the TCN against 203,680 under persistence. ms693’s entire TCN drop is the shared cold start (129,372; after τ≥61 the drop is 0). ms859’s 1.10% on the ladder and the TCN is also entirely τ≤60 (72,427 requests); ProScale’s 0.19% is from scaling on tick 1. ms205’s whole-run drop falls from 0.94% under persistence to 0.26%, and ms460 from 1.16% to 1.07%. Offered-delay means for ms150 / ms588 / ms215 / ms693: reactive 111 / 301 / 621 / 740 ms, ProScale 394 / 244 / 460 / 414 ms, persistence 86 / 166 / 324 / 164 ms, TCN 61 / 102 / 393 / 106 ms. Mean cores are 66.2 against persistence’s 58.7. Weights for all eight networks are fit on these same 12 hours.
