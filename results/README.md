# Results catalog

Campaign folders are numbered by **when that experiment family started**.
**Higher number = later.** Inside a campaign, `{seed}_{UTC}` is chronological
(later stamp = newer run).

This file is the map. Run data itself is gitignored.

| If you want… | Open |
|---|---|
| **Latest** triangle (post user-delay eval, 18 Sep 2026) | `09-triangle-post-match/` |
| QoS plots for that campaign | `09-triangle-post-match/<slice>/42_20260918T15*/analysis/demo_app/ladder_qos.png` |
| Alibaba MS_588 | `04-alibaba-ms588/` |
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
| 09 | `09-triangle-post-match/` | **Sep 17–18** | **Current** four triangle slices |

### 09 — current triangle (look here first)

| Slice | Config | Latest run |
|---|---|---|
| HorizontalScaling | `17-demo_400_triangle_horizontal.yaml` | `horizontal/42_20260918T150707Z` |
| Fat vicinity | `18-demo_400_triangle_vicinity.yaml` | `vicinity/42_20260918T150708Z` |
| Floor neighbor | `19-demo_400_triangle_skip_neighbor.yaml` | `skip_neighbor/42_20260918T150708Z` |
| Vicinity then unmet | `16-demo_400_triangle.yaml` | `vicinity_then_unmet/42_20260918T150709Z` |

Plots: `<run>/analysis/demo_app/ladder_qos.png` and `user_latency.png`.

---

## Where a new run goes

Each YAML sets `sim.results_dir` to a numbered campaign. The engine then
creates `{seed}_{UTC}` under that folder.

The next unused campaign number is **10** (for example
`results/10-alibaba-post-match/` when you re-run Alibaba after the paper match).
Do not dump new work into `01-tiny-smoke/` or `06-triangle-beg-era/`.
