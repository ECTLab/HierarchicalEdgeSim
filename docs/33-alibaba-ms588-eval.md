# Alibaba MS_588 evaluation slices

**Trace:** `traces/alibaba/MS_588.csv` — 721 one-minute ticks, Λ 932–29778, sum 3,385,510  
**Physics:** `cpu_min=0.5`, `cpu_max=4.0`, \(\rho_{\mathrm{cpu}}=0.0004\) ⇒ \(\mu_{\max}=8750\) req/min per replica; peak needs ~3.4 packed replicas  
**Pool:** 32 cores in every slice (enough for the peak). The split is who owns them.  
**Campaign:** `results/11-alibaba-ms588-eval/`  
**Configs:** `26`–`30`  
**Related:** [29-alibaba-tcn-s7-results.md](./29-alibaba-tcn-s7-results.md) (original 4×8 S7 pair), [19-triangle-ladder-scenarios.md](./19-triangle-ladder-scenarios.md)

Five runs, not a full matrix. Horizontal world matches `12`/`13`. Vicinity is the same cores with home packed so VicinityRound is the only way to cover hourly spikes.

| Config | Isolates | Topology | Scaler |
|---|---|---|---|
| `26-demo_alibaba_ms588_horizontal_reactive.yaml` | Ladder, no hats | 4×8 in `c1` | `reactive_local` |
| `27-demo_alibaba_ms588_horizontal_persistence.yaml` | PredictAndDecide ablation | same | persistence, \(W=60\), \(H=5\) |
| `28-demo_alibaba_ms588_horizontal_tcn.yaml` | Paper predictor | same | TCN `models/tcn_delta_v1` |
| `29-demo_alibaba_ms588_vicinity_reactive.yaml` | VicinityRound on real spikes | `c1` 1×8 + `c2` 3×8 in `v1` | `reactive_local`, \(\theta_{\mathrm{route}}=0.80\) |
| `30-demo_alibaba_ms588_vicinity_tcn.yaml` | TCN + VicinityRound | same as 29 | TCN, \(\theta_{\mathrm{route}}=0.80\) |

Horizontal keeps `theta_high: 0.90` and `cascade_home: true` like `12`/`13`. Vicinity sets `theta_high` / `sim.theta_route` to **0.80** (prefer-local util cap) and `cascade_home: false` (one MS; avoids seed yank on descent). `sustained_steps: 99` and `cooldown_C: 5` match the S7 TCN control path.

Home in 29/30 holds at most two packed replicas (\(\mu\le 17500\)). Peak 29778 must loan onto `c2`. Must see `vicinity_spawn` / `vicinity_terminate` on 29–30; must not see them on 26–28.

## How to run

Needs torch on `PYTHONPATH` for 28 and 30. Persistence and reactive do not.

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

HR=$(.venv/bin/python examples/run_with_autoscaler.py configs/26-demo_alibaba_ms588_horizontal_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
HP=$(.venv/bin/python examples/run_with_autoscaler.py configs/27-demo_alibaba_ms588_horizontal_persistence.yaml | sed -n 's/^Run complete. Outputs written to: //p')
HT=$(.venv/bin/python examples/run_with_autoscaler.py configs/28-demo_alibaba_ms588_horizontal_tcn.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VR=$(.venv/bin/python examples/run_with_autoscaler.py configs/29-demo_alibaba_ms588_vicinity_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VT=$(.venv/bin/python examples/run_with_autoscaler.py configs/30-demo_alibaba_ms588_vicinity_tcn.yaml | sed -n 's/^Run complete. Outputs written to: //p')

for d in "$HR" "$HP" "$HT" "$VR" "$VT"; do
  .venv/bin/python examples/compare_trace_vs_log.py "$d"
done
.venv/bin/python examples/compare_reactive_baseline.py \
  --run reactive_local "$HR" \
  --run persistence "$HP" \
  --run proactive_tcn "$HT"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run vicinity_reactive "$VR" \
  --run vicinity_tcn "$VT" \
  --out "$VT/analysis/baseline_comparison.png"
```

Plots: `<run>/analysis/demo_app/ladder_qos.png`, `user_latency.png`, `replicas_by_site.png`. Proactive also `forecast_vs_actual.png`. Overlay: `analysis/story/overview.png`.

## Recorded runs (seed 42, 2026-09-20T070746Z–T070755Z)

Incoming **3,385,510** on every slice (conservation holds). Leftover μ floor is in the shared ladder, so quiet-end keepers sit above `cpu_min` (reactive 1.28 cores; TCN ~1.7).

| Slice | Run dir | Drop | After τ≥61 | SLA miss | Peak live | Extra spawn | Leftover |
|---|---|---|---|---|---|---|---|
| Horizontal reactive | `horizontal_reactive/42_20260920T070746Z` | 489,422 / **14.46%** | — | 21.03% | 2 at τ=384 | 2× `horizontal_spawn` on `c1-w1` | `c-api-1` 1.28 / 294.86 |
| Horizontal persistence | `horizontal_persistence/42_20260920T070747Z` | 244,909 / **7.23%** | 6.67% | 9.34% | 7 at τ=382 | 47× `horizontal_spawn` (`c1-w1/w2/w3`) | `c-api-c1-w3-9` 1.73 / 317.30 |
| Horizontal TCN | `horizontal_tcn/42_20260920T070750Z` | 182,918 / **5.40%** | **4.66%** | 7.37% | 7 at τ=82 | 47× `horizontal_spawn` | `c-api-c1-w3-9` 1.73 / 317.30 |
| Vicinity reactive | `vicinity_reactive/42_20260920T070751Z` | 489,422 / **14.46%** | — | 21.03% | 2 at τ=384 | 2× `horizontal_spawn` on home; **no** `vicinity_spawn` | `c-api-1` 1.28 / 294.86 |
| Vicinity TCN | `vicinity_tcn/42_20260920T070755Z` | 181,332 / **5.36%** | **4.61%** | 7.37% | 7 at τ=82 | 3× home `horizontal_spawn` + **39× `vicinity_spawn` on c2** | `c-api-c1-w1-3` 1.68 / 314.80 |

Paths are under `results/11-alibaba-ms588-eval/`. Overlay: `horizontal_tcn/…/analysis/story/overview.png` and `vicinity_tcn/…/analysis/story/overview.png`. Forecast: `forecast_vs_actual.png` on the three proactive dirs.

**What this shows.** Reactive never uses the extra 24 cores: two local extras, same 14.46% whether the pool is one cluster or a vicinity. Persistence already halves drops (7.23%) with last-value hats. TCN is best (5.40% / 5.36%) and hits peak replica count at τ=82, one minute after the trace peak (τ=81). Vicinity TCN is the rung check: loans on `c2`, then 39× `vicinity_terminate` in the valleys; QoS matches in-cluster TCN because the 32-core pool is the same.

August S7 on this world was reactive **15.44%** / TCN **7.48%**. This HEAD is a bit lower (leftover μ floor + current allocate). Do not mix those folder names with campaign 11.

Vicinity reactive logging one `unmet_demand` is leftover residual after a home-only window, not a capacity miss.
