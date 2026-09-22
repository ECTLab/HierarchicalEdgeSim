# Alibaba 2-MS vicinity evaluation (campaign 12)

**Traces:** `MS_588.csv` (hourly needle) + `MS_150.csv` (always-on heavy), 721 minutes  
**Physics:** same as campaign 11 (`cpu_min=0.5`, `cpu_max=4.0`, \(\rho_{\mathrm{cpu}}=0.0004\))  
**Pool:** 48 cores — home `c1` 2×8, neighbor `c2` 4×8, vicinity `v1`  
**Campaign:** `results/12-alibaba-2ms-eval/`  
**Configs:** `33` reactive, `34` persistence, `35` Kubernetes HPA  
**Related:** [33-alibaba-ms588-eval.md](./33-alibaba-ms588-eval.md) (single MS_588), [34-alibaba-8ms-eval.md](./34-alibaba-8ms-eval.md) (eight-MS, campaign 14)

One app, two microservices. Persistence PredictAndDecide vs the reactive ladder vs Kubernetes HPA (the industry external row). No TCN. This is the first multi-MS step after campaign 11. Campaign 13 (3–4 MS) is next if these slices look right; do not jump to campaign 14.

Home is sized below concurrent peak (~39 cores of headroom at \(\theta=0.60\); max concurrent 58,787 at \(\tau=81\)). MS_150 mean already wants ~14.5 cores, so a 16-core home is the hog’s sitting room; the MS_588 needle and MS_150’s own peaks must loan onto `c2`. `cascade_home: true` so a shrink on one MS can pull the *other* MS’s loan home.

| Config | Isolates |
|---|---|
| `33-demo_alibaba_2ms_vicinity_reactive.yaml` | Ladder + Reserve + vicinity, no hats |
| `34-demo_alibaba_2ms_vicinity_persistence.yaml` | Same world, last-value hats, \(W=60\), \(H=5\) |
| `35-demo_alibaba_2ms_vicinity_hpa.yaml` | Kubernetes HPA replica formula, home `c1` only |

| MS | Shape | Role |
|---|---|---|
| `ms150` | Always-on heavy (mean 21.7k, peak 40,083) | Reserve hog; occupies home in the valleys |
| `ms588` | Hourly needle, minute 20 (peak 29,778) | Persistence lags; contends with 150 at \(\tau=81\) |

Prefer-local \(\theta_{\mathrm{route}}=0.80\). HPA has no \(\theta_{\mathrm{high}}\) of its own, so it uses that same routing cap. Cold start on 34 is reactive until \(\tau=60\) (history length \(W\)). Seeds at 2.0/1024, one per home worker. HPA clones that seed size and never resizes.

Must see `vicinity_spawn` / `vicinity_terminate` on 33/34 (home 16 cores cannot cover MS_150 peak, let alone both). Must **not** see them on 35: HPA is cluster-local, leftover is `unmet_demand`. Must not need a third cluster.

## How to run

Persistence does not need torch.

```bash
export PYTHONPATH="$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

VR=$(.venv/bin/python examples/run_with_autoscaler.py configs/33-demo_alibaba_2ms_vicinity_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VP=$(.venv/bin/python examples/run_with_autoscaler.py configs/34-demo_alibaba_2ms_vicinity_persistence.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VH=$(.venv/bin/python examples/run_with_autoscaler.py configs/35-demo_alibaba_2ms_vicinity_hpa.yaml | sed -n 's/^Run complete. Outputs written to: //p')

.venv/bin/python examples/compare_trace_vs_log.py "$VR"
.venv/bin/python examples/compare_trace_vs_log.py "$VP"
.venv/bin/python examples/compare_trace_vs_log.py "$VH"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run vicinity_hpa "$VH" \
  --run vicinity_reactive "$VR" \
  --run vicinity_persistence "$VP"
```

Plots: per-MS `ladder_qos_<ms>.png`, `forecast_vs_actual_<ms>.png` (persistence), `replicas_by_site.png`, overlay `analysis/baseline_comparison.png`.

## Recorded runs (seed 42)

Incoming **19,040,943** on every slice (MS_150 15,655,433 + MS_588 3,385,510; conservation holds).

| Slice | Run dir | Drop | After τ≥61 | SLA miss | Peak live | Vicinity spawn | Cascade |
|---|---|---|---|---|---|---|---|
| Vicinity HPA | `vicinity_hpa/42_20260921T064646Z` | 1,920,475 / **10.09%** | 9.29% | 39.14% | 8 at τ=6 (**8 home / 0 c2**) | **0** | 0 |
| Vicinity reactive | `vicinity_reactive/42_20260920T134640Z` | 919,938 / **4.83%** | 4.56% | 12.25% | 8 at τ=149 (5 home / 3 c2) | 10 | 1 spawn / 1 terminate |
| Vicinity persistence | `vicinity_persistence/42_20260920T134642Z` | 422,164 / **2.22%** | **1.65%** | 4.11% | 16 at τ=202 (5 home / 11 c2) | **81** | 3 spawn / 3 terminate |

HPA also logged **654** `unmet_demand` (Pending-pod analogue). Clusters used: `c1` only.

Per-MS drop (whole run):

| MS | HPA | Reactive | Persistence |
|---|---|---|---|
| ms150 (hog) | 9.99% | 2.75% | **1.17%** |
| ms588 (hourly) | 10.55% | 14.43% | **7.08%** |

**What this shows.** HPA is the industry row: replica formula on CPU usage/request, seed-sized pods, home cluster only. It packs `c1` to 8×2.0 cores by τ=6 and never loans onto `c2`, so leftover is unmet. Overall drop **10.09%** vs the ladder **4.83%** / persistence **2.22%**. The hog is where vicinity pays: ms150 9.99% under HPA vs 2.75% / 1.17% once loans exist. The needle is mixed — HPA’s +4 scale-up grabs a few home replicas for ms588 (10.55%) while reactive 588 waits behind the hog then loans (14.43%); persistence still wins that MS (7.08%). That is a related-work figure, not a bug: HPA is not VicinityRound.

Do not mix these folders with campaign 11 (single MS_588) or campaign 14 (eight MS). Campaign 13 is reserved for 3–4 MS.
