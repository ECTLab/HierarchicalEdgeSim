# Results catalog

Campaign folders are numbered by **when that experiment family started**.
**Higher number = later.** Inside a campaign, `{seed}_{UTC}` is chronological
(later stamp = newer run).

This file is the map. Run data itself is gitignored.

| If you want… | Open |
|---|---|
| **Latest** reactive triangle (leftover μ floor, 19 Sep 2026) | `09-triangle-post-match/` |
| **Latest** proactive triangle (persistence, 19 Sep 2026) | `10-triangle-proactive/` |
| QoS plots (reactive) | `09-triangle-post-match/<slice>/42_20260919T1709*/analysis/demo_app/ladder_qos.png` |
| QoS plots (proactive) | `10-triangle-proactive/<slice>/42_20260919T1842*/analysis/demo_app/ladder_qos.png` |
| Forecast vs trace (proactive) | `10-triangle-proactive/<slice>/42_20260919T1842*/analysis/demo_app/forecast_vs_actual.png` |
| **Latest** MS_588 eval (Sep 2026) | `11-alibaba-ms588-eval/` |
| Alibaba MS_588 (original S7 pair) | `04-alibaba-ms588/` |
| Alibaba MS_150 | `05-alibaba-ms150/` |
| Old global-rung triangle (BEG/BEH names) | `06-triangle-beg-era/` |
| How a config chooses its folder | `results_dir` in [../configs/README.md](../configs/README.md) |
| What the numbers mean | [../docs/19-triangle-ladder-scenarios.md](../docs/19-triangle-ladder-scenarios.md) |

---

## Campaigns

| # | Folder | When | What |
|---|---|---|---|
| 01 | `01-tiny-smoke/` | Aug 7–Sep 17 | `tiny.yaml` 5-tick dumps (safe to ignore) |
| 02 | `02-env-60tick/` | Aug 26 | Env-only 60-tick worlds (`demo_60`, two containers, two clusters) |
| 03 | `03-phased-300/` | Aug 15 | 300-tick static vs vertical vs local |
| 04 | `04-alibaba-ms588/` | Aug 16–17 | MS_588 `reactive_local` vs TCN |
| 05 | `05-alibaba-ms150/` | Aug 16–17 | MS_150 same world, heavier trace |
| 06 | `06-triangle-beg-era/` | Aug 18–20 | Triangle with the **old global rung** |
| 07 | `07-partition/` | Aug 26 | Algorithm 1 coords vs latency |
| 08 | `08-ladder-60tick/` | Aug 15–27 | 60-tick ladder smokes (local / vicinity / proactive) |
| 09 | `09-triangle-post-match/` | **Sep 17–19** | Four triangle slices, `reactive_local` |
| 10 | `10-triangle-proactive/` | **Sep 19** | Same four slices, `proactive_auto_scaler` (persistence) |
| 11 | `11-alibaba-ms588-eval/` | **Sep 20** | MS_588 horizontal vs vicinity (reactive / persistence / TCN) |

### 09 — current triangle, reactive (look here first)

| Slice | Config | Latest run |
|---|---|---|
| HorizontalScaling | `17-demo_400_triangle_horizontal.yaml` | `horizontal/42_20260919T170902Z` |
| Fat vicinity | `18-demo_400_triangle_vicinity.yaml` | `vicinity/42_20260919T170909Z` |
| Floor neighbor | `19-demo_400_triangle_skip_neighbor.yaml` | `skip_neighbor/42_20260919T170915Z` |
| Vicinity then unmet | `16-demo_400_triangle.yaml` | `vicinity_then_unmet/42_20260919T170919Z` |

Plots: `<run>/analysis/demo_app/ladder_qos.png` and `user_latency.png`.

### 10 — same triangle, proactive

Same topologies and trace as 09. Persistence front-end (`feature_window=10`), `sim.theta_route: 0.80`, ladder `cascade_home: false` / `use_near_saturation_up: true`.

| Slice | Config | Latest run |
|---|---|---|
| HorizontalScaling | `23-demo_400_triangle_horizontal_proactive.yaml` | `horizontal/42_20260919T184228Z` |
| Fat vicinity | `24-demo_400_triangle_vicinity_proactive.yaml` | `vicinity/42_20260919T184237Z` |
| Floor neighbor | `25-demo_400_triangle_skip_neighbor_proactive.yaml` | `skip_neighbor/42_20260919T184244Z` |
| Vicinity then unmet | `22-demo_400_triangle_proactive.yaml` | `vicinity_then_unmet/42_20260919T184248Z` |

Plots: `<run>/analysis/demo_app/ladder_qos.png`, `user_latency.png`, and `forecast_vs_actual.png` (trace vs persistence t+1 / t+3).

### 11 — MS_588 eval

Same 721-minute trace. Horizontal is the original 4×8 cluster. Vicinity splits those 32 cores into home 8 + fat neighbor 24.

| Slice | Config | Latest run |
|---|---|---|
| Horizontal reactive | `26-demo_alibaba_ms588_horizontal_reactive.yaml` | `horizontal_reactive/42_20260920T070746Z` |
| Horizontal persistence | `27-demo_alibaba_ms588_horizontal_persistence.yaml` | `horizontal_persistence/42_20260920T070747Z` |
| Horizontal TCN | `28-demo_alibaba_ms588_horizontal_tcn.yaml` | `horizontal_tcn/42_20260920T103619Z` |
| Vicinity reactive | `29-demo_alibaba_ms588_vicinity_reactive.yaml` | `vicinity_reactive/42_20260920T070751Z` |
| Vicinity TCN | `30-demo_alibaba_ms588_vicinity_tcn.yaml` | `vicinity_tcn/42_20260920T103632Z` |

What the numbers mean: [../docs/33-alibaba-ms588-eval.md](../docs/33-alibaba-ms588-eval.md).

---

## Where a new run goes

Each YAML sets `sim.results_dir` to a numbered campaign. The engine then
creates `{seed}_{UTC}` under that folder.

The next unused campaign number is **12**.
Do not dump new work into `01-tiny-smoke/` or `06-triangle-beg-era/`.
