# Alibaba 8-MS vicinity evaluation (campaign 14)

**Traces:** eight 721-minute Alibaba series in `traces/alibaba/`  
**Physics:** same as campaign 11 (`cpu_min=0.5`, `cpu_max=4.0`, \(\rho_{\mathrm{cpu}}=0.0004\))  
**Pool:** 64 cores — home `c1` 4×8, neighbor `c2` 4×8, vicinity `v1`  
**Campaign:** `results/14-alibaba-8ms-eval/`  
**Configs:** `31` reactive, `32` persistence  
**Related:** [33-alibaba-ms588-eval.md](./33-alibaba-ms588-eval.md) (single MS_588), [35-alibaba-2ms-eval.md](./35-alibaba-2ms-eval.md) (MS_588 + MS_150)

One app, eight microservices, persistence PredictAndDecide. No TCN. Home is sized below concurrent peak (~64 cores of headroom at \(\theta=0.60\)), so VicinityRound has to loan onto `c2`. `cascade_home: true` so a shrink on one MS can pull a *different* MS’s loan home.

| Config | Isolates |
|---|---|
| `31-demo_alibaba_8ms_vicinity_reactive.yaml` | Ladder + Reserve + vicinity, no hats |
| `32-demo_alibaba_8ms_vicinity_persistence.yaml` | Same world, last-value hats, \(W=60\), \(H=5\) |

| MS | Shape | Role |
|---|---|---|
| `ms588` | Hourly needle, minute 20 | Persistence lags (campaign 11 contrast) |
| `ms215` | Hourly needle, minute ~8 | Complementary spike; p90 overlap with 588 is 0 |
| `ms150` | Always-on heavy | Reserve hog |
| `ms133` | Flat ~1.6k | Lender |
| `ms693` | Slow hour-scale wave | Persistence should track |
| `ms859` | Medium diurnal | Smooth second wave |
| `ms460` | Mixed medium | Everyday load |
| `ms205` | Irregular bursts | Persistence lags for a different reason |

Prefer-local \(\theta_{\mathrm{route}}=\theta_{\mathrm{high}}=0.80\). Cold start on 32 is reactive until \(\tau=60\) (history length \(W\)).

Must see `vicinity_spawn` / `vicinity_terminate` on both slices (home 32 cores cannot cover the eight-way peak). Must not need a third cluster.

## How to run

Persistence does not need torch.

```bash
export PYTHONPATH="$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

VR=$(.venv/bin/python examples/run_with_autoscaler.py configs/31-demo_alibaba_8ms_vicinity_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VP=$(.venv/bin/python examples/run_with_autoscaler.py configs/32-demo_alibaba_8ms_vicinity_persistence.yaml | sed -n 's/^Run complete. Outputs written to: //p')

.venv/bin/python examples/compare_trace_vs_log.py "$VR"
.venv/bin/python examples/compare_trace_vs_log.py "$VP"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run vicinity_reactive "$VR" \
  --run vicinity_persistence "$VP"
```

Plots: per-MS `ladder_qos_<ms>.png`, `forecast_vs_actual_<ms>.png` (persistence), `replicas_by_site.png`, overlay `analysis/baseline_comparison.png`.

## Recorded runs (seed 42, 2026-09-20T132205Z / T132210Z)

Incoming **42,157,830** on both slices (conservation holds). Peak live 28 reactive vs 36 persistence, all on home+vicinity (none outside `v1`).

| Slice | Run dir | Drop | After τ≥61 | SLA miss | Peak live | Vicinity spawn | Cascade |
|---|---|---|---|---|---|---|---|
| Vicinity reactive | `vicinity_reactive/42_20260920T132205Z` | 3,624,740 / **8.60%** | 8.04% | 16.41% | 28 at τ=369 (15 home / 13 c2) | 51 | 4 spawn / 4 terminate |
| Vicinity persistence | `vicinity_persistence/42_20260920T132210Z` | 2,260,550 / **5.36%** | **4.43%** | 9.16% | 36 at τ=410 (15 home / 21 c2) | **179** | 11 spawn / 13 terminate |

Per-MS drop (whole run):

| MS | Reactive | Persistence |
|---|---|---|
| ms133 (lender) | 0.03% | **0.00%** |
| ms150 (hog) | 1.16% | **0.98%** |
| ms205 (bursts) | 4.26% | **0.98%** |
| ms215 (offset hourly) | **31.18%** | 43.53% |
| ms460 (typical) | 2.97% | **1.11%** |
| ms588 (hourly) | 12.52% | **9.18%** |
| ms693 (slow wave) | 40.36% | **5.33%** |
| ms859 (diurnal) | 1.10% | 1.10% |

**What this shows.** Home 32 cores saturates (15 live at peak on both slices); VicinityRound is the overflow (51 vs 179 loans on `c2`). Cascade actually fires because eight MS share `c1`. Persistence wins **overall** because last-value tracks slow waves (`ms693` 40% → 5%) and stays sticky after a spike (`ms588` 12.5% → 9.2%). It does **not** win everywhere: complementary needle `ms215` is *worse* under persistence (31% → 44%) — lag-1 hats plus leftover replicas from other MS occupy the pool when minute ~8 arrives. That is the point of the eight-way mix, not a bug in the ladder.

Do not mix these folders with campaign 11 (single MS_588) or campaign 12 (MS_588 + MS_150). Campaign 13 is reserved for 3–4 MS.
