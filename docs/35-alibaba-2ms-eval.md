# Alibaba 2-MS vicinity evaluation (campaign 12)

**Traces:** `MS_588.csv` (hourly needle) + `MS_150.csv` (always-on heavy), 721 minutes  
**Physics:** same as campaign 11 (`cpu_min=0.5`, `cpu_max=4.0`, \(\rho_{\mathrm{cpu}}=0.0004\))  
**Pool:** 48 cores — home `c1` 2×8, neighbor `c2` 4×8, vicinity `v1`  
**Campaign:** `results/12-alibaba-2ms-eval/`  
**Configs:** `33` reactive, `34` persistence \(\theta=0.60\), `35` Kubernetes HPA, `36` ProScale-style, `37` per-MS TCN \(\theta=0.60\), `48` persistence \(\theta=0.75\), `49` per-MS TCN \(\theta=0.75\)  
**Related:** [33-alibaba-ms588-eval.md](./33-alibaba-ms588-eval.md) (single MS_588), [34-alibaba-8ms-eval.md](./34-alibaba-8ms-eval.md) (eight-MS, campaign 14)

One app, two microservices. Persistence PredictAndDecide vs the reactive ladder vs Kubernetes HPA (home only) vs a reduced ProScale clone (fixed-size replicas, two-point moving average, greedy home then neighbor) vs one residual TCN per microservice. This is the first multi-MS step after campaign 11. Four-MS results are in [36-alibaba-4ms-eval.md](./36-alibaba-4ms-eval.md). Do not jump to campaign 14.

Home is sized below concurrent peak (~39 cores of headroom at \(\theta=0.60\); max concurrent 58,787 at \(\tau=81\)). MS_150 mean already wants ~14.5 cores, so a 16-core home is the hog’s sitting room; the MS_588 needle and MS_150’s own peaks must loan onto `c2`. `cascade_home: true` so a shrink on one MS can pull the *other* MS’s loan home.

| Config | Isolates |
|---|---|
| `33-demo_alibaba_2ms_vicinity_reactive.yaml` | Ladder + Reserve + vicinity, no hats |
| `34-demo_alibaba_2ms_vicinity_persistence.yaml` | Same world, last-value hats, \(W=60\), \(H=5\) |
| `35-demo_alibaba_2ms_vicinity_hpa.yaml` | Kubernetes HPA replica formula, home `c1` only |
| `36-demo_alibaba_2ms_vicinity_proscale.yaml` | SMA \(N=2\), seed-sized pods, greedy `c1` then `c2`, no reserve |
| `37-demo_alibaba_2ms_vicinity_tcn.yaml` | Same ladder as 34; `ms588` uses `models/tcn_delta_ms588_v2`, `ms150` uses `models/tcn_delta_ms150_v3` |
| `48-demo_alibaba_2ms_vicinity_persistence_theta75.yaml` | Same ladder as 34 with \(\theta_{\mathrm{target}}=0.75\) |
| `49-demo_alibaba_2ms_vicinity_tcn_theta75.yaml` | Same ladder as 37 with \(\theta_{\mathrm{target}}=0.75\) |

| MS | Shape | Role |
|---|---|---|
| `ms150` | Always-on heavy (mean 21.7k, peak 40,083) | Reserve hog; occupies home in the valleys |
| `ms588` | Hourly needle, minute 20 (peak 29,778) | Persistence lags; contends with 150 at \(\tau=81\) |

Prefer-local \(\theta_{\mathrm{route}}=0.80\). Persistence and TCN size the residual at \(\theta_{\mathrm{target}}=0.60\) in configs 34 and 37. Configs 48 and 49 change only that target to 0.75; \(\theta_{\mathrm{up}}=0.80\) and \(\theta_{\mathrm{down}}=0.30\) stay put, so the up/down gate is the same and the requested CPU and RAM on a scale step are smaller. HPA has no \(\theta_{\mathrm{target}}\) and uses the same \(\theta_{\mathrm{route}}=0.80\) as its routing cap. Cold start on 34 is reactive until \(\tau=60\) (history length \(W\)). Seeds at 2.0/1024, one per home worker. HPA and ProScale clone that seed size and never resize. ProScale’s count is \(\lceil \mathrm{SMA}_2 / \mu_{\mathrm{seed}} \rceil\) with \(\mu_{\mathrm{seed}}=3750\) req/min. Microservice ids are placed in sorted order against raw free cores, so `ms150` is seated before `ms588`. There is no DAG makespan and no cloud offload.

Must see `vicinity_spawn` / `vicinity_terminate` on 33/34/36/37/48/49 (home 16 cores cannot cover MS_150 peak, let alone both). Must **not** see them on 35: HPA is cluster-local, leftover is `unmet_demand`. Must not need a third cluster.

## How to run

Configs 33–36 and 48 do not need torch. Configs 37 and 49 do: put an interpreter that can `import torch` on `PYTHONPATH` (this machine: the `alibaba-trace` venv site-packages).

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

VR=$(.venv/bin/python examples/run_with_autoscaler.py configs/33-demo_alibaba_2ms_vicinity_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VP=$(.venv/bin/python examples/run_with_autoscaler.py configs/34-demo_alibaba_2ms_vicinity_persistence.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VH=$(.venv/bin/python examples/run_with_autoscaler.py configs/35-demo_alibaba_2ms_vicinity_hpa.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VS=$(.venv/bin/python examples/run_with_autoscaler.py configs/36-demo_alibaba_2ms_vicinity_proscale.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VT=$(.venv/bin/python examples/run_with_autoscaler.py configs/37-demo_alibaba_2ms_vicinity_tcn.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VP75=$(.venv/bin/python examples/run_with_autoscaler.py configs/48-demo_alibaba_2ms_vicinity_persistence_theta75.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VT75=$(.venv/bin/python examples/run_with_autoscaler.py configs/49-demo_alibaba_2ms_vicinity_tcn_theta75.yaml | sed -n 's/^Run complete. Outputs written to: //p')

.venv/bin/python examples/compare_trace_vs_log.py "$VR"
.venv/bin/python examples/compare_trace_vs_log.py "$VP"
.venv/bin/python examples/compare_trace_vs_log.py "$VH"
.venv/bin/python examples/compare_trace_vs_log.py "$VS"
.venv/bin/python examples/compare_trace_vs_log.py "$VT"
.venv/bin/python examples/compare_trace_vs_log.py "$VP75"
.venv/bin/python examples/compare_trace_vs_log.py "$VT75"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run vicinity_tcn_theta75 "$VT75" \
  --run vicinity_tcn "$VT" \
  --run vicinity_persistence_theta75 "$VP75" \
  --run vicinity_persistence "$VP" \
  --run vicinity_proscale "$VS" \
  --run vicinity_hpa "$VH" \
  --run vicinity_reactive "$VR"
```

Plots: per-MS `ladder_qos_<ms>.png`, `user_latency_<ms>.png`, `forecast_vs_actual_<ms>.png`, `replicas_by_site.png`, overlay `analysis/baseline_comparison.png` and `analysis/story/`.

## Recorded runs (seed 42)

Incoming **19,040,943** on every slice (MS_150 15,655,433 + MS_588 3,385,510; conservation holds).

| Slice | Run dir | Drop | After τ≥61 | SLA miss | Peak live | Vicinity spawn | Cascade |
|---|---|---|---|---|---|---|---|
| Vicinity HPA | `vicinity_hpa/42_20260921T064646Z` | 1,920,475 / **10.09%** | 9.29% | 39.14% | 8 at τ=6 (**8 home / 0 c2**) | **0** | 0 |
| Vicinity reactive | `vicinity_reactive/42_20260920T134640Z` | 919,938 / **4.83%** | 4.56% | 12.25% | 8 at τ=149 (5 home / 3 c2) | 10 | 1 spawn / 1 terminate |
| Vicinity persistence, \(\theta=0.60\) | `vicinity_persistence/42_20260920T134642Z` | 422,164 / **2.22%** | **1.65%** | 4.11% | 16 at τ=202 (5 home / 11 c2) | **81** | 3 spawn / 3 terminate |
| Vicinity ProScale | `vicinity_proscale/42_20260922T073902Z` | 837,604 / **4.40%** | 4.56% | 22.68% | 15 at τ=83 (8 home / 7 c2) | 154 | 0 |
| Vicinity TCN, \(\theta=0.60\) | `vicinity_tcn/42_20260923T180029Z` | 157,203 / **0.83%** | **0.11%** | 2.17% | 18 at τ=677 (6 home / 12 c2) | 64 | 3 spawn / 3 terminate |
| Vicinity persistence, \(\theta=0.75\) | `vicinity_persistence_theta75/42_20260924T111051Z` | 442,801 / **2.33%** | 1.77% | 4.29% | 15 at τ=442 (6 home / 9 c2) | 50 | 3 spawn / 3 terminate |
| Vicinity TCN, \(\theta=0.75\) | `vicinity_tcn_theta75/42_20260924T111059Z` | 177,392 / **0.93%** | 0.23% | 2.36% | 17 at τ=82 (5 home / 12 c2) | 63 | 1 spawn / 1 terminate |

HPA also logged **654** `unmet_demand` (Pending-pod analogue). Clusters used: `c1` only. ProScale logged no `unmet_demand` and no resize. The \(\theta=0.75\) persistence slice logged 45 `unmet_demand`; the \(\theta=0.75\) TCN slice logged 57. Mean allocated CPU and RAM (average over ticks of the sum of container capacity):

| Slice | \(\theta_{\mathrm{target}}\) | SLA miss | Mean CPU | Mean RAM |
|---|---|---|---|---|
| HPA | — | 39.14% | 15.5 cores | 7,911 MB |
| Reactive | — | 12.25% | 15.3 cores | 2,205 MB |
| ProScale | — | 22.68% | 16.2 cores | 8,314 MB |
| Persistence | 0.60 | 4.11% | 24.6 cores | 3,974 MB |
| Persistence | 0.75 | 4.29% | **22.3 cores** | **3,679 MB** |
| TCN | 0.60 | 2.17% | 30.4 cores | 4,503 MB |
| TCN | 0.75 | 2.36% | **28.1 cores** | **4,267 MB** |

HPA and ProScale RAM stays near 8 GB because every pod is the 1024 MB seed and they never resize. Persistence and TCN resize RAM with the same \(\theta_{\mathrm{target}}\) as CPU. TCN and persistence, at both targets, drop the same requests for τ≤60 (138,606).

Per-MS drop at \(\theta_{\mathrm{target}}=0.60\):

| MS | HPA | Reactive | ProScale | Persistence | TCN |
|---|---|---|---|---|---|
| ms150 (hog) | 9.99% | 2.75% | 3.52% | 1.17% | **0.75%** |
| ms588 (hourly) | 10.55% | 14.43% | 8.48% | 7.08% | **1.15%** |

At \(\theta=0.75\), persistence is 1.10% / 7.99% and TCN is 0.88% / 1.15% (MS_150 / MS_588). Offered-delay means (timeouts included): HPA 610 / 242 ms, reactive 229 / 284 ms, ProScale 407 / 252 ms, persistence 82 / 144 ms, TCN 69 / 55 ms. The 0.75 pair is persistence 84 / 164 ms and TCN 72 / 48 ms. Per-MS SLA miss for the 0.60 TCN is 2.20% / 2.02%; at 0.75 it is 2.45% / 1.95%.

**What this shows.** HPA is the industry row: replica formula on CPU usage/request, seed-sized pods, home cluster only. It packs `c1` to 8×2.0 cores by τ=6 and never loans onto `c2`, so leftover is unmet. Overall drop **10.09%** vs the ladder **4.83%** / persistence **2.22%**. The hog is where vicinity pays: ms150 9.99% under HPA vs 2.75% / 1.17% once loans exist. The needle is mixed — HPA’s +4 scale-up grabs a few home replicas for ms588 (10.55%) while reactive 588 waits behind the hog then loans (14.43%); persistence still wins that MS (7.08%). That is a related-work figure, not a bug: HPA is not VicinityRound.

ProScale is the row that may use `c2` without the ladder. At the same ~16-core budget as HPA and reactive, drop is **4.40%**: better than HPA on both MS, better than reactive on the needle (8.48% vs 14.43%), slightly worse than reactive on the hog (3.52% vs 2.75%). It does not hold capacity. At τ=81, MS_588 still drops 22,278 against μ=7,500; τ=82 and τ=83 drop 0, and the live count peaks at 15 one minute later. The 154 neighbor spawns are matched by 154 terminates (mean `c2` CPU 1.8 cores, peak 14). Seed-sized pods keep MS_150’s offered mean at 407 ms and its SLA miss at 24.03%, above the reactive ladder’s 229 ms / 10.29%. Persistence still has the lowest drop and the lowest delay among the non-TCN rows, at 24.6 mean cores.

TCN is the same ladder as persistence with a different hat per MS (`tcn_delta_ms588_v2` on the needle, `tcn_delta_ms150_v3` on the hog). After the shared cold start, drop is **0.11%** and the whole-run drop is **0.83%**, with offered means 69 / 55 ms. That costs **30.4** mean cores against persistence’s 24.6, and the live count peaks at 18 with `c2` full. Almost all of the remaining 157,203 drops are the 138,606 requests lost at τ≤60, before either forecast is applied.

Raising \(\theta_{\mathrm{target}}\) from 0.60 to 0.75 asks for \(0.60/0.75=80\%\) of the variable CPU and RAM on each scale step. Floors and the unchanged 0.30–0.80 deadband keep the realized cut smaller than that. Persistence falls by 2.2 cores and 295 MB, and SLA miss rises from 4.11% to 4.29%. TCN falls by 2.3 cores and 236 MB, and SLA miss rises from 2.17% to 2.36%. The needle’s TCN drop stays 1.15%. Persistence’s needle drop moves from 7.08% to 7.99%. Peak allocated CPU drops from 48 to 40 under persistence and from 48 to 43.5 under TCN, so the tighter target stops pinning the whole 48-core pool.

Do not mix these folders with campaign 11 (single MS_588) or campaign 14 (eight MS).
