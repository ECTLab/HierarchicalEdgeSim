# Alibaba 2-MS split owner (campaign 15)

**Traces:** `MS_588.csv` (hourly needle) + `MS_150.csv` (always-on hog), 721 minutes  
**Physics:** same as campaign 12 (`cpu_min=0.5`, `cpu_max=4.0`, \(\rho_{\mathrm{cpu}}=0.0004\))  
**Pool:** 48 cores — `c1` 1×8 owns `ms588`, `c2` 1×8 owns `ms150`, `c3` 4×8 hosts no app  
**Campaign:** `results/15-alibaba-2ms-split-owner/`  
**Configs:** `50` reactive, `51` persistence \(\theta=0.60\), `52` Kubernetes HPA, `53` ProScale-style, `54` per-MS TCN \(\theta=0.60\)  
**Related:** [35-alibaba-2ms-eval.md](./35-alibaba-2ms-eval.md) (same traces, one app owned by `c1`)

The owner stamp is per app, taken from that app’s seed replica. Campaign 12 puts both services in one app, so `c1` owns both. This campaign uses two apps: `app_ms588` is seeded on `c1-w1`, `app_ms150` on `c2-w1`. Each home is one 8-core worker. That is below the hog’s reactive peak (~14 cores) and below both forecast peaks at \(\theta_{\mathrm{target}}=0.60\) (~23 cores for the needle, ~31 for the hog), so overflow has to leave home. `c3` is the empty 32-core spare in the same vicinity. Vicinity members are listed `[c3, c1, c2]`, so ProScale fills the spare before the other service’s home. Every pair is 5.0 ms. Seeds are 2.0 cores / 1024 MB. `cascade_home` is on, and with one service per app it has nothing to pull.

An earlier reactive world in this campaign gave `c1` 16 cores and `c2` 32. Neither service borrowed, because the ladder never asked for more than those homes held. That run is not the result below.

| Config | Isolates |
|---|---|
| `50-demo_alibaba_2ms_split_owner_reactive.yaml` | Ladder, no hats |
| `51-demo_alibaba_2ms_split_owner_persistence.yaml` | Same world, last-value hats, \(W=60\), \(H=5\), \(\theta_{\mathrm{target}}=0.60\) |
| `52-demo_alibaba_2ms_split_owner_hpa.yaml` | Kubernetes HPA, each service’s own home only |
| `53-demo_alibaba_2ms_split_owner_proscale.yaml` | SMA \(N=2\), seed-sized pods, greedy home then `c3` |
| `54-demo_alibaba_2ms_split_owner_tcn.yaml` | Same ladder as 51; `ms588` uses `models/tcn_delta_ms588_v2`, `ms150` uses `models/tcn_delta_ms150_v3` |

## How to run

Configs 50–53 do not need torch. Config 54 does: put an interpreter that can `import torch` on `PYTHONPATH` (this machine: the `alibaba-trace` venv site-packages).

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

VR=$(.venv/bin/python examples/run_with_autoscaler.py configs/50-demo_alibaba_2ms_split_owner_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VP=$(.venv/bin/python examples/run_with_autoscaler.py configs/51-demo_alibaba_2ms_split_owner_persistence.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VH=$(.venv/bin/python examples/run_with_autoscaler.py configs/52-demo_alibaba_2ms_split_owner_hpa.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VS=$(.venv/bin/python examples/run_with_autoscaler.py configs/53-demo_alibaba_2ms_split_owner_proscale.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VT=$(.venv/bin/python examples/run_with_autoscaler.py configs/54-demo_alibaba_2ms_split_owner_tcn.yaml | sed -n 's/^Run complete. Outputs written to: //p')

.venv/bin/python examples/compare_trace_vs_log.py "$VR"
.venv/bin/python examples/compare_trace_vs_log.py "$VP"
.venv/bin/python examples/compare_trace_vs_log.py "$VH"
.venv/bin/python examples/compare_trace_vs_log.py "$VS"
.venv/bin/python examples/compare_trace_vs_log.py "$VT"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run vicinity_tcn "$VT" --run vicinity_hpa "$VH" --run vicinity_reactive "$VR" \
  --run vicinity_proscale "$VS" --run vicinity_persistence "$VP" \
  --app app_ms150 --out "$VT/analysis/app_ms150/baseline_comparison.png"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run vicinity_tcn "$VT" --run vicinity_hpa "$VH" --run vicinity_reactive "$VR" \
  --run vicinity_proscale "$VS" --run vicinity_persistence "$VP" \
  --app app_ms588 --out "$VT/analysis/app_ms588/baseline_comparison.png"
```

Per-app plots land under `analysis/app_ms150/` and `analysis/app_ms588/`. The five-way overlay for each app is `baseline_comparison.png` in that folder, with `story/` beside it.

## Recorded runs (seed 42)

Incoming **19,040,943** on every slice (MS_150 15,655,433 + MS_588 3,385,510; conservation holds). Reactive, persistence, and TCN drop the same 141,174 requests at τ≤60.

| Slice | Run dir | Drop | After τ≥61 | SLA miss | Peak live | Vicinity spawn | `c3` mean / peak |
|---|---|---|---|---|---|---|---|
| Vicinity HPA | `vicinity_hpa/42_20261003T133644Z` | 5,904,987 / **31.01%** | 30.14% | 57.98% | 8 at τ=23 (8 home / 0 spare) | **0** | 0 / 0 |
| Vicinity reactive | `vicinity_reactive/42_20261003T133644Z` | 856,414 / **4.50%** | 4.17% | 15.85% | 7 at τ=646 (3 home / 4 spare) | 7 | 4.6 / 6.4 |
| Vicinity ProScale | `vicinity_proscale/42_20261003T133646Z` | 837,604 / **4.40%** | 4.56% | 26.59% | 15 at τ=83 (8 home / 7 spare) | 171 | 5.1 / 14 |
| Vicinity persistence | `vicinity_persistence/42_20261003T133644Z` | 407,206.5 / **2.14%** | 1.55% | 4.31% | 14 at τ=202 (4 home / 10 spare) | 63 | 12.1 / 32 |
| Vicinity TCN | `vicinity_tcn/42_20261003T133657Z` | 159,671 / **0.84%** | **0.11%** | 2.42% | 15 at τ=135 (5 home / 10 spare) | 50 | 15.6 / 32 |

HPA logged **647** `unmet_demand`. Persistence logged 33, TCN 36, reactive 7. ProScale logged none. No replica of either service was placed on the other service’s home. Loans landed on `c3`.

| Slice | SLA miss | Mean CPU | Mean RAM |
|---|---|---|---|
| HPA | 57.98% | 13.1 cores | 6,704 MB |
| Reactive | 15.85% | 15.2 cores | 2,249 MB |
| ProScale | 26.59% | 16.2 cores | 8,314 MB |
| Persistence | 4.31% | 24.2 cores | 3,555 MB |
| TCN | 2.42% | 29.5 cores | 4,236 MB |

Per-MS drop, SLA miss, and offered mean (ms150 / ms588):

| Slice | ms150 drop | ms588 drop | SLA miss | Offered mean |
|---|---|---|---|---|
| HPA | 36.11% | 7.45% | 68.08% / 11.24% | 810 / 154 ms |
| Reactive | 2.34% | 14.46% | 14.73% / 21.03% | 292 / 279 ms |
| ProScale | 3.52% | 8.48% | 28.87% / 16.03% | 453 / 242 ms |
| Persistence | 1.02% | 7.30% | 3.25% / 9.20% | 84 / 126 ms |
| TCN | **0.77%** | **1.15%** | 2.56% / 1.76% | 73 / 39 ms |

**Who borrowed.** The reactive hog leaves `c2`: mean 7.6 cores at home, 4.6 on `c3`, away on 706 of 721 ticks, peak live 6 with 4 of them on the spare. The reactive needle stays on `c1`. Its peak allocation is 6.0 cores, so an 8-core home still holds it, and its drop (14.46%) matches the earlier split-owner run and campaign 12. The hourly spike is gone before the up-streak of 3 fills the home. Persistence and TCN borrow for both services. The hog’s away peak is about 23 cores; the needle’s is about 14. ProScale borrows for both as well, but the needle’s loan is thin (22 ticks, away peak 6 cores). HPA never leaves home, so `c3` stays empty and the hog, capped at 8 cores, drops 36%.

**Against campaign 12** (same traces, same 48-core budget, one owner). TCN’s drop is almost unchanged (0.84% here, 0.83% there) and persistence is close (2.14% vs 2.22%). SLA miss is a bit higher (TCN 2.42% vs 2.17%, persistence 4.31% vs 4.11%) because each home is pinned at 8 cores and the overflow pays 5.0 ms. ProScale’s drop count is the same 837,604; its SLA miss rises from 22.68% to 26.59%. Reactive drop improves slightly (4.50% vs 4.83%) because the hog has a spare that is not also the needle’s home, while its SLA miss rises from 12.25% to 15.85%. HPA is the row that changes shape: campaign 12’s 16-core shared home held a lot of the hog, and drop was 10.09%. Here HPA cannot see `c3`, so drop is 31.01%. Persistence and TCN still pin the pool at the joint peak (peak CPU 48; 6 and 9 ticks on that cap).

Same-day fit still applies: these TCN checkpoints were trained on this trace. Keep this folder separate from campaign 12.
