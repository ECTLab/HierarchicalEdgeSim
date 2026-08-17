# Alibaba story plots — load, μ, forecast, CPU given vs needed

Overlay figures for **reactive_local vs TCN** on the same Alibaba world. They
answer: what was the load, what did the TCN predict, how much serving capacity
did each scaler have, how much CPU was enough, and how much did we actually
give.

Per-run PNGs (`trace_vs_log_requests.png`, `ladder_qos.png`, …) stay under
`analysis/demo_app/`. They do **not** overlay the two scalers and they do not
draw oracle / sweet-spot CPU. This folder does.

Numbers for the recorded pairs: [alibaba-tcn-s7-results.md](./alibaba-tcn-s7-results.md)
(MS_588), [alibaba-tcn-ms150-results.md](./alibaba-tcn-ms150-results.md) (MS_150).

---

## Where the files are

`results/` is gitignored. After you regenerate (below), each compared run
gets a copy:

```text
results/alibaba_proactive/<seed>_<UTC>/analysis/story/overview.png
results/alibaba_reactive_local/<seed>_<UTC>/analysis/story/overview.png
results/alibaba_ms150_proactive/<seed>_<UTC>/analysis/story/overview.png
results/alibaba_ms150_reactive_local/<seed>_<UTC>/analysis/story/overview.png
```

On the machine that produced the recorded pair, the overview plots are:

| Trace | Overview |
|---|---|
| MS_588 TCN | `results/alibaba_proactive/42_20260816T104101Z/analysis/story/overview.png` |
| MS_588 reactive | `results/alibaba_reactive_local/42_20260816T100437Z/analysis/story/overview.png` |
| MS_150 TCN | `results/alibaba_ms150_proactive/42_20260816T114309Z/analysis/story/overview.png` |
| MS_150 reactive | `results/alibaba_ms150_reactive_local/42_20260816T114246Z/analysis/story/overview.png` |

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

Same command as [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md)
§B6 / §B7. `compare_reactive_baseline.py` writes `analysis/story/` into **each**
compared run directory.

Needs torch on `PYTHONPATH` for the TCN hat panel (same as the rest of S7).

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

# MS_588
REACTIVE=$(python3 examples/run_with_autoscaler.py configs/demo_alibaba_reactive_local.yaml | sed -n 's/^Run complete. Outputs written to: //p')
PROACTIVE=$(python3 examples/run_with_autoscaler.py configs/demo_alibaba_proactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
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

MS_150: same, with `configs/demo_alibaba_ms150_reactive_local.yaml` and
`configs/demo_alibaba_ms150_proactive.yaml`.

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
| [implementation-plan.md](./implementation-plan.md) **§4.2** | Authoritative physics: floors buy no throughput; `μ = min(μ_cpu, μ_ram)`; `λ_served = min(λ_in, μ)` |
| [s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md) | Same formula with `ρ_cpu` / `ρ_ram`; why a RAM-floor replica still gets routed load |
| [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md) **§7** | Same idea on the 60-tick demo (`ρ_cpu=0.01`, `ρ_ram=0.5`) |
| [s7-proactive-front-end.md](./s7-proactive-front-end.md) | Decide uses `H = Σ(A − min)`; floors buy no μ |
| `src/hierarchical_edge_sim/env/usage.py` | `serving_capacity()` — the code |

The numbers **0.5, 0.0004, 256, 0.02** are the Alibaba MS spec in
`configs/demo_alibaba_proactive.yaml` (`cpu_min_cores`, `cpu_per_request_cores`,
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
burst. The win is `hold_down_ticks=55` (did not shrink in the valley), not
foresight.

Later spikes: TCN μ stays near the load (τ=501: μ=27,891 vs 27,221 incoming);
reactive is still ~8k μ. Whole run 15.44% vs 3.79%; after TCN is on (τ≥61)
15.11% vs 2.33%. First hour is identical (no hats).
