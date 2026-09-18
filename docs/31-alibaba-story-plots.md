# Alibaba story plots — load, μ, forecast, CPU given vs needed

Overlay figures for **reactive_local vs TCN** on the same Alibaba world. They
answer: what was the load, what did the TCN predict, how much serving capacity
did each scaler have, how much CPU was enough, and how much did we actually
give.

Per-run PNGs (`trace_vs_log_requests.png`, `ladder_qos.png`, …) stay under
`analysis/demo_app/`. They do **not** overlay the two scalers and they do not
draw oracle / sweet-spot CPU. This folder does.

Numbers for the recorded pairs: [29-alibaba-tcn-s7-results.md](./29-alibaba-tcn-s7-results.md)
(MS_588), [30-alibaba-tcn-ms150-results.md](./30-alibaba-tcn-ms150-results.md) (MS_150).

---

## Where the files are

`results/` is gitignored. After you regenerate (below), each compared run
gets a copy:

```text
results/04-alibaba-ms588/proactive/<seed>_<UTC>/analysis/story/overview.png
results/04-alibaba-ms588/reactive_local/<seed>_<UTC>/analysis/story/overview.png
results/05-alibaba-ms150/proactive/<seed>_<UTC>/analysis/story/overview.png
results/05-alibaba-ms150/reactive_local/<seed>_<UTC>/analysis/story/overview.png
```

On the machine that produced the recorded pair, the overview plots are:

| Trace | Overview |
|---|---|
| MS_588 TCN | `results/04-alibaba-ms588/proactive/42_20260817T105250Z/analysis/story/overview.png` |
| MS_588 reactive | `results/04-alibaba-ms588/reactive_local/42_20260817T105246Z/analysis/story/overview.png` |
| MS_150 TCN | `results/05-alibaba-ms150/proactive/42_20260817T105251Z/analysis/story/overview.png` |
| MS_150 reactive | `results/05-alibaba-ms150/reactive_local/42_20260817T105247Z/analysis/story/overview.png` |

The two paths in a pair are the **same overlay** (reactive vs TCN on one figure),
copied into both run directories so you can open either.

Same folder also has the individual panels:

| File | What it shows |
|---|---|
| `overview.png` | All panels stacked (start here) |
| `serve_capacity.png` | Incoming vs serve μ. Drops when incoming is above the μ line |
| `cpu_needed_vs_provided.png` | Oracle CPU to serve all, 60% target (sweet spot), CPU each scaler gave |
| `tcn_forecast.png` | Incoming vs TCN t+1 / t+5 (hats start after lookback) |
| `dropped.png` | Reactive vs TCN dropped requests |
| `replicas.png` | Live replica count |

Grey band is τ≤60: TCN has no hats yet; both scalers are the reactive ladder.

---

## How to generate them

Same command as [00-how-to-rerun-tests-and-graphs.md](./00-how-to-rerun-tests-and-graphs.md)
§B6 / §B7. `compare_reactive_baseline.py` writes `analysis/story/` into **each**
compared run directory.

Needs torch on `PYTHONPATH` for the TCN hat panel (same as the rest of S7).

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

# MS_588
REACTIVE=$(python3 examples/run_with_autoscaler.py configs/12-demo_alibaba_reactive_local.yaml | sed -n 's/^Run complete. Outputs written to: //p')
PROACTIVE=$(python3 examples/run_with_autoscaler.py configs/13-demo_alibaba_proactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
python3 examples/compare_trace_vs_log.py "$REACTIVE"
python3 examples/compare_trace_vs_log.py "$PROACTIVE"
python3 examples/compare_reactive_baseline.py \
  --run reactive_local "$REACTIVE" \
  --run proactive_tcn "$PROACTIVE" \
  --out "$PROACTIVE/analysis/baseline_comparison.png"

# Then open:
#   $PROACTIVE/analysis/story/overview.png
#   $REACTIVE/analysis/story/overview.png
```

MS_150: same, with `configs/14-demo_alibaba_ms150_reactive_local.yaml` and
`configs/15-demo_alibaba_ms150_proactive.yaml`.

Code: `examples/analysis/story.py` (wired from `examples/analysis/compare.py`).
Tests: `tests/test_ladder_analysis.py` (`test_packed_cpu_and_serve_mu_match_alibaba_physics`,
`test_compare_runs_writes_png`).

---

## What μ is (and where that already lived)

The Alibaba story line

```text
μ = Σ min((CPU − 0.5) / 0.0004, (RAM − 256) / 0.02)
```

is **not** a new model. It is the locked Part A serving formula, with the
Alibaba YAML numbers plugged in. The sum is over **live replicas** that minute.

### Already in the docs

| Where | What it says |
|---|---|
| [03-implementation-plan.md](./03-implementation-plan.md) **§4.2** | Authoritative physics: floors buy no throughput; `μ = min(μ_cpu, μ_ram)`; `λ_served = min(λ_in, μ)` |
| [27-s7-proactive-drop-diagnosis.md](./27-s7-proactive-drop-diagnosis.md) | Same formula with `ρ_cpu` / `ρ_ram`; why a RAM-floor replica still gets routed load |
| [00-how-to-rerun-tests-and-graphs.md](./00-how-to-rerun-tests-and-graphs.md) **§7** | Same idea on the 60-tick demo (`ρ_cpu=0.01`, `ρ_ram=0.5`) |
| [26-s7-proactive-front-end.md](./26-s7-proactive-front-end.md) | Decide uses `H = Σ(A − min)`; floors buy no μ |
| `src/hierarchical_edge_sim/env/usage.py` | `serving_capacity()` — the code |

The numbers **0.5, 0.0004, 256, 0.02** are the Alibaba MS spec in
`configs/13-demo_alibaba_proactive.yaml` (`cpu_min_cores`, `cpu_per_request_cores`,
`ram_min_mb`, `ram_per_request_mb`). They are not universal.

The diagnosis that first applied this formula to the 69% TCN run is in
[S7 TCN drop diagnosis](5e08edd2-0047-469a-aba8-c9272a1417c0).

### Meaning, with the Alibaba coeffs

- **0.5 cores / 256 MB** — deployment floor. The replica must hold this to
  exist. It does **not** process requests.
- **Headroom** — `CPU − 0.5` and `RAM − 256`. Only this buys throughput.
- **0.0004 cores / request** — CPU to finish one request in one one-minute
  tick. So `μ_cpu = (CPU − 0.5) / 0.0004` requests per minute.
- **0.02 MB / request** — extra RAM per request that tick.
  `μ_ram = (RAM − 256) / 0.02`.
- **`min(μ_cpu, μ_ram)`** — whichever resource is tighter caps the replica.
  Alibaba demos are CPU-bound (`μ_cpu ≪ μ_ram`) unless RAM was walked to the
  floor (then `μ_ram = 0` and the replica serves nothing).
- **`Σ`** — add every live replica’s μ. That is the green/red step on
  `serve_capacity.png`.

Worked example, initial replica `2.0` cores / `1024` MB:

```text
μ_cpu = (2.0 − 0.5) / 0.0004 = 3750 req/min
μ_ram = (1024 − 256) / 0.02  = 38400 req/min
μ     = min(3750, 38400)     = 3750
```

MS_588 opens at 4,201 requests and MS_150 at 24,209. Both start on this 3,750
μ, so the first minutes drop even before any scaler runs. A replica sitting on
`0.5 / 256` has μ = 0.

If incoming > μ that minute, the extra is dropped. No queue.

### Oracle CPU vs 60% sweet spot (the other two lines)

Packed at `cpu_max = 4.0`, one replica’s max μ is `(4.0 − 0.5) / 0.0004 = 8750`.

- **Oracle (serve all):** `n = ceil(incoming / 8750)` replicas, total CPU
  `n × 0.5 + incoming × 0.0004`. Least packed allocation that could serve that
  minute with no drops.
- **Sweet spot (θ_target = 0.60):** same packing but for `incoming / 0.60`.
  That is what PredictAndDecide aims at, not a zero-drop floor.

Cluster cap in these demos is 32 cores (4 × 8).

---

## How to read the overlay (MS_588)

At the worst minute (τ=81, 29,778 incoming): oracle ≈ 13.9 cores, sweet spot
≈ 22.9. Reactive gave 2.65 cores (μ=5,375) and dropped 24k. TCN gave 6.10 cores
(μ=12,738) and dropped 17k. The TCN t+1 hat was 7,398 — it **missed** the
burst. Without `hold_down_ticks`, later spikes start lower: τ=501 TCN has 9.03
cores (μ=16,475 vs 27,221 incoming) and drops 10.7k. Whole run 15.44% vs
**6.50%**; after TCN is on (τ≥61) 15.11% vs **5.31%**. Mean TCN CPU after
warmup is 8.63 (was 14.2 with the 55-minute hold). First hour is identical
(no hats). HEAD with `α_down=1.0` is **7.48%** / **6.38%** (mean CPU 7.42).
