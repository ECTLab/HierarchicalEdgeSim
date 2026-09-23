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
| `28-demo_alibaba_ms588_horizontal_tcn.yaml` | Paper predictor | same | TCN `models/tcn_delta_ms588_v2` |
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

## Recorded runs (seed 42)

Incoming **3,385,510** on every slice (conservation holds). Leftover μ floor is in the shared ladder, so quiet-end keepers sit above `cpu_min` (reactive 1.28 cores; TCN ~2.2–2.5 — asymmetric loss still over-predicts valleys).

TCN weights are the residual net in `models/tcn_delta_ms588_v2/` (RF=63, cyclic minute-of-hour, MS_588-only). Replay on this trace: t+1 MAE 1449 vs persistence 1343, but corr(actual)=**0.868** vs corr(lag-1)=0.559, and every hourly onset hat is ~27k (last-value ~4k).

| Slice | Run dir | Drop | After τ≥61 | SLA miss | Peak live | Extra spawn | Leftover |
|---|---|---|---|---|---|---|---|
| Horizontal reactive | `horizontal_reactive/42_20260920T070746Z` | 489,422 / **14.46%** | — | 21.03% | 2 at τ=384 | 2× `horizontal_spawn` on `c1-w1` | `c-api-1` 1.28 / 294.86 |
| Horizontal persistence | `horizontal_persistence/42_20260920T070747Z` | 244,909 / **7.23%** | 6.67% | 9.34% | 7 at τ=382 | 47× `horizontal_spawn` (`c1-w1/w2/w3`) | `c-api-c1-w3-9` 1.73 / 317.30 |
| Horizontal TCN | `horizontal_tcn/42_20260920T103619Z` | 39,097 / **1.15%** | **0.00%** | 1.76% | 8 at τ=257 | 61× `horizontal_spawn` (`c1-w1/w2/w3`) | `c-api-c1-w3-5` 2.49 / 355.63 |
| Vicinity reactive | `vicinity_reactive/42_20260920T070751Z` | 489,422 / **14.46%** | — | 21.03% | 2 at τ=384 | 2× `horizontal_spawn` on home; **no** `vicinity_spawn` | `c-api-1` 1.28 / 294.86 |
| Vicinity TCN | `vicinity_tcn/42_20260920T103632Z` | 39,097 / **1.15%** | **0.00%** | 1.77% | 8 at τ=135 | 6× home `horizontal_spawn` + **41× `vicinity_spawn` on c2** | `c-api-c1-w1-6` 2.20 / 340.91 |

Paths are under `results/11-alibaba-ms588-eval/`. Overlay: `horizontal_reactive/…/analysis/story/overview.png` (horizontal three-way) and `vicinity_tcn/…/analysis/story/overview.png`. Forecast: `forecast_vs_actual.png` on the three proactive dirs.

**What this shows.** Reactive never uses the extra 24 cores: two local extras, same 14.46% whether the pool is one cluster or a vicinity. Persistence already halves drops (7.23%) with last-value hats, but it still *follows* the spike. TCN now *leads* it: live≥5 from τ=75, six minutes before the τ=81 peak, so every post-warmup drop is **0**. The remaining 1.15% / ~1.76% SLA miss is the cold-start hour (including the τ≈21 spike with no hats). Vicinity TCN is the rung check: 41 loans on `c2` and 41× `vicinity_terminate` in the valleys; QoS matches in-cluster TCN because the 32-core pool is the same.

The previous TCN on this campaign (RF=7, `time_tick/720`, `42_20260920T070750Z` / `T070755Z`) was 5.40% / 5.36% with 4.66% still dropping after τ=61 — hats echoed the valley (~7k vs 24–30k). Do not mix that folder with the rows above.

August S7 on this world was reactive **15.44%** / TCN **7.48%**. Do not mix those folder names with campaign 11.

Vicinity TCN `unmet_demand` lines are leftover residual after a home-only window, not a capacity miss.

The first multi-MS follow-up is campaign 12 (MS_588 + MS_150): [35-alibaba-2ms-eval.md](./35-alibaba-2ms-eval.md).
