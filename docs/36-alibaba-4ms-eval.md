# Alibaba 4-MS vicinity evaluation (campaign 13)

**Traces:** `MS_150.csv` (always-on hog), `MS_588.csv` (hourly needle, minute 20), `MS_215.csv` (hourly plateau, onset at minute 3), `MS_693.csv` (3-minute high/mid/low sawtooth), 721 minutes  
**Physics:** same as campaign 11 (`cpu_min=0.5`, `cpu_max=4.0`, \(\rho_{\mathrm{cpu}}=0.0004\))  
**Pool:** 56 cores — home `c1` 3×8, neighbor `c2` 4×8, vicinity `v1`  
**Campaign:** `results/13-alibaba-4ms-eval/`  
**Configs:** `38` reactive, `39` persistence, `40` per-MS TCN, `41` Kubernetes HPA, `42` ProScale-style  
**Related:** [35-alibaba-2ms-eval.md](./35-alibaba-2ms-eval.md) (two MS), [34-alibaba-8ms-eval.md](./34-alibaba-8ms-eval.md) (eight MS)

One app, four microservices. Reactive ladder, persistence, one residual TCN per microservice, Kubernetes HPA (home only), and a reduced ProScale clone (fixed-size replicas, two-point moving average, greedy home then neighbor). Same seeds (2.0/1024), \(\theta_{\mathrm{route}}=0.80\), and 5.0 ms between `c1` and `c2` on every slice. `cascade_home: true` on the ladder configs. Cold start on 39 and 40 is reactive until \(\tau=60\). HPA and ProScale scale from the first tick and never resize.

Home is 24 cores because the hog’s packed sweet-spot mean at \(\theta=0.60\) is 16.8 and its p95 is 22.2, so the hog fits, while the two needles together peak at 26.1 and cannot both fit on home. The four-way sweet-spot max is 52.5, so 24+32 covers it and a third cluster is not required. The hog sits alone on `c1-w2`; `ms215` and `ms693` share `c1-w3`.

| Config | Isolates |
|---|---|
| `38-demo_alibaba_4ms_vicinity_reactive.yaml` | Ladder + vicinity, no hats |
| `39-demo_alibaba_4ms_vicinity_persistence.yaml` | Same world, last-value hats, \(W=60\), \(H=5\) |
| `40-demo_alibaba_4ms_vicinity_tcn.yaml` | Same ladder as 39; one checkpoint per MS |
| `41-demo_alibaba_4ms_vicinity_hpa.yaml` | Kubernetes HPA replica formula, home `c1` only |
| `42-demo_alibaba_4ms_vicinity_proscale.yaml` | SMA \(N=2\), seed-sized pods, greedy `c1` then `c2`, no reserve |

| MS | Shape | Checkpoint |
|---|---|---|
| `ms150` | Always-on hog (mean 21.7k, peak 40,083) | `models/tcn_delta_ms150_v3` (rebound) |
| `ms588` | Hourly needle, minute 20 (peak 29,778) | `models/tcn_delta_ms588_v2` (cyclic minute) |
| `ms215` | Hourly plateau, jump at minute 3 (peak 32,050) | `models/tcn_delta_ms215_v1` (cyclic minute, this trace only) |
| `ms693` | 3-minute sawtooth, about 8k / 6k / 2.5k | `models/tcn_delta_ms693_v1` (cyclic minute, this trace only) |

`ms693` is not a smooth hour-scale wave. Lag-1 autocorrelation is −0.48 and lag-3 error is 190 requests, so last-value misses the next phase (t+1 MAE 3,788). The cyclic-minute net’s full-trace t+1 MAE is 269, and on troughs its horizon max covers the next peak on 218/218 minutes. `ms215`’s minute-3 jumps are led on 11/11 hours (horizon-max MAE 1,262 versus 24,637 for last-value). That net’s quiet minutes sit about 4,700 requests above the next five-minute max, about 3 cores at \(\theta=0.60\), and its overall t+1 MAE (2,696) is worse than last-value (1,603). Weights are fit on these same 12 hours.

## How to run

Configs 38, 39, 41, and 42 do not need torch. Config 40 does.

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

VR=$(.venv/bin/python examples/run_with_autoscaler.py configs/38-demo_alibaba_4ms_vicinity_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VP=$(.venv/bin/python examples/run_with_autoscaler.py configs/39-demo_alibaba_4ms_vicinity_persistence.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VT=$(.venv/bin/python examples/run_with_autoscaler.py configs/40-demo_alibaba_4ms_vicinity_tcn.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VH=$(.venv/bin/python examples/run_with_autoscaler.py configs/41-demo_alibaba_4ms_vicinity_hpa.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VS=$(.venv/bin/python examples/run_with_autoscaler.py configs/42-demo_alibaba_4ms_vicinity_proscale.yaml | sed -n 's/^Run complete. Outputs written to: //p')

.venv/bin/python examples/compare_trace_vs_log.py "$VR"
.venv/bin/python examples/compare_trace_vs_log.py "$VP"
.venv/bin/python examples/compare_trace_vs_log.py "$VT"
.venv/bin/python examples/compare_trace_vs_log.py "$VH"
.venv/bin/python examples/compare_trace_vs_log.py "$VS"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run vicinity_tcn "$VT" \
  --run vicinity_hpa "$VH" \
  --run vicinity_reactive "$VR" \
  --run vicinity_proscale "$VS" \
  --run vicinity_persistence "$VP"
```

Plots: per-MS `user_latency_<ms>.png` under each run’s `analysis/demo_app/`, plus `analysis/baseline_comparison.png` and `analysis/story/`.

## Recorded runs (seed 42)

Incoming **26,405,685** on every slice (MS_150 15,655,433 + MS_588 3,385,510 + MS_215 3,261,851 + MS_693 4,102,891; conservation holds). Reactive, persistence, and TCN drop the same requests for \(\tau\le 60\) (465,438). HPA and ProScale do not share that cold start.

| Slice | Run dir | Drop | After τ≥61 | SLA miss | Peak live | Vicinity spawn | Mean cores |
|---|---|---|---|---|---|---|---|
| Vicinity HPA | `vicinity_hpa/42_20260923T205312Z` | 4,531,462 / **17.16%** | 16.07% | 39.30% | 12 at τ=4 (12 home / 0 c2) | **0** | 23.6 |
| Vicinity reactive | `vicinity_reactive/42_20260923T201554Z` | 3,476,911 / **13.17%** | 12.63% | 21.85% | 16 at τ=307 (10 home / 6 c2) | 37 | 24.7 |
| Vicinity ProScale | `vicinity_proscale/42_20260923T205314Z` | 1,439,932 / **5.45%** | 5.57% | 24.24% | 20 at τ=429 (12 home / 8 c2) | 179 | 24.2 |
| Vicinity persistence | `vicinity_persistence/42_20260923T201557Z` | 1,214,228 / **4.60%** | 3.14% | 7.41% | 25 at τ=384 (11 home / 14 c2) | 188 | 36.6 |
| Vicinity TCN | `vicinity_tcn/42_20260923T202311Z` | 821,933 / **3.11%** | **1.50%** | 5.06% | 25 at τ=493 (9 home / 16 c2) | 160 | **41.4** |

HPA logged **801** `unmet_demand` and never left `c1` (c2 CPU 0, peak allocated CPU 24). ProScale logged no `unmet_demand` and no resize; it spawned on `c2` 179 times and terminated all 179. Its c2 mean is 2.5 cores and its c2 peak is 16, so it borrows and returns. Persistence and TCN both fill the neighbor (c2 peak 32) and the whole pool (peak allocated CPU 56). Persistence c2 mean is 13.7 cores; TCN c2 mean is 18.0. Mean cores are the average over ticks of the sum of container `cpu_capacity`.

Per-MS drop (whole run):

| MS | HPA | Reactive | ProScale | Persistence | TCN |
|---|---|---|---|---|---|
| ms150 (hog) | 14.01% | 1.67% | 3.52% | 1.09% | **0.90%** |
| ms588 (minute 20) | 10.69% | 13.77% | 8.48% | 7.48% | **1.15%** |
| ms215 (minute 3) | 60.33% | 33.52% | 12.11% | 16.16% | 15.72% |
| ms693 (sawtooth) | **0.19%** | 40.36% | 5.05% | 6.40% | **3.15%** |

Offered-delay mean (demand-weighted), ms150 / ms588 / ms215 / ms693: HPA 635 / 248 / 789 / 57 ms, reactive 125 / 333 / 586 / 740 ms, ProScale 399 / 244 / 460 / 414 ms, persistence 78 / 165 / 264 / 198 ms, TCN 66 / 64 / 284 / 106 ms. TCN per-MS SLA is 2.13% / 2.22% / 21.93% / 5.16%. HPA per-MS SLA is 46.95% / 17.74% / 73.33% / 0.83%. ProScale per-MS SLA is 23.09% / 16.04% / 32.80% / 28.61%.

HPA’s sawtooth is the one series that fits in seed-sized pods on the 24-core home (after τ≥61 its ms693 drop is 0). The hog and both needles do not, and the leftover is `unmet_demand`, which is why ms215 drops 60%. ProScale’s whole-run ms215 drop (12.11%) is below persistence (16.16%) because ProScale scales from tick 1: first-60 ms215 drop is 40,540 versus 197,460 on the ladder. After τ≥61 the order flips — ms215 drop is ProScale 354,456, persistence 329,516, TCN 315,254 — and ProScale’s offered delay stays high because each pod is stuck at 2.0 cores. Same pattern on the hog: after τ≥61 ProScale still drops 518,532 requests against persistence’s 71,819, at almost the same mean cores as reactive (24.2 versus 24.7).

The ms588 and ms693 gains are the forecast. ms215’s replay leads every minute-3 jump, and the first such hour in the sim (τ=64) drops nothing under TCN, but later plateaus still drop because `c2` is already at 32 cores. Persistence sometimes leaves `c2` partly empty during those hours (τ=664, c2 peak 10) and drops more there; TCN fills the neighbor and the other three forecasts are already sitting on it, so ms215’s total barely moves (16.16% → 15.72%) and its offered delay is slightly worse. The extra 4.8 mean cores (41.4 versus 36.6) are that headroom, not a solved needle.
