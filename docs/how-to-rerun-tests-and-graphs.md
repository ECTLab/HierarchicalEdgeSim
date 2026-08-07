# Re-run Tests and Generate Graphs

This guide shows how to:

1. set up the venv and run the test suite
2. run demo simulations (env-only, reactive, **proactive decide+apply**)
3. analyze a result folder (requests, CPU/RAM, **scaling decisions**)

Proactive LSTM install / day‑80 trace notes: [how-to-run-proactive-lstm-tests.md](./how-to-run-proactive-lstm-tests.md).  
Decide+apply build plan: [proactive-decide-and-apply-plan.md](./proactive-decide-and-apply-plan.md).

---

## 1) Setup

```bash
cd /Users/ahmad/research/ehsan_moradi/HierarchicalEdgeSim
python3.14 -m venv .venv
.venv/bin/pip install -e ".[dev,lstm]"   # lstm required for proactive_auto_scaler
.venv/bin/pip install matplotlib
```

Ensure the model bundle exists (or copy trained artifacts — see the LSTM guide):

```text
models/rps_lstm_v1/
  lstm_edge_weights.pth
  traffic_scaler.pkl
  meta.json                 # feature_window must match YAML (default 10)
```

If Matplotlib complains about a cache dir:

```bash
export MPLCONFIGDIR=/tmp/mpl
```

---

## 2) Run tests

```bash
# full suite
.venv/bin/pytest tests/ -q

# proactive + shared packing (decide / allocate / common distribute)
.venv/bin/pytest tests/test_proactive_decide.py \
                 tests/test_proactive_allocate.py \
                 tests/test_proactive_auto_scaler.py \
                 tests/test_common_distribute.py \
                 tests/test_reactive_vertical.py -q
```

---

## 3) Demo scenarios

Each run command prints a path like `results/.../<run_id>`. Use that path for analysis.

### A) Env only (no autoscaler)

```bash
.venv/bin/python examples/run_env_only.py configs/demo_60.yaml
.venv/bin/python examples/run_env_only.py configs/demo_60_two_containers.yaml
.venv/bin/python examples/run_env_only.py configs/demo_60_two_clusters.yaml
```

### B) Reactive vertical (optional baseline demos)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_60_two_containers_reactive.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/demo_300_two_containers_reactive.yaml
```

### C) Proactive decide + apply (primary)

Defaults: `ttw_ticks=60`, `feature_window=10` → first scale opportunity after **10 TTWs** (e.g. τ=600 when `tick_sec=1`). Until then the container sits at its deployment floor (often zero headroom → drops are expected).

**Recommended — FIFA day 80, 1 hour, one container (up + down):**

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_wc_day80_proactive_1h_onec.yaml
# → results/proactive_wc_day80_1h_onec/<run_id>/
```

**Other proactive configs:**

| Config | Results dir prefix | Notes |
| --- | --- | --- |
| `configs/demo_3600_proactive_lstm.yaml` | `results/proactive_3600_lstm/` | Smooth hill, 3600 ticks |
| `configs/demo_wc_day80_proactive_lstm.yaml` | `results/proactive_wc_day80_lstm/` | Day 80, two containers |
| `configs/demo_300_proactive_auto_scaler.yaml` | (see YAML `results_dir`) | Short; override TTW/W if needed |

---

## 4) Analyze a result folder

**Preferred script** (requests + CPU/RAM + scaling decisions):

```bash
.venv/bin/python examples/compare_trace_vs_log.py <RUN_DIR>
```

Same entry via the package:

```bash
.venv/bin/python -m analysis <RUN_DIR>
# from examples/:  python -m analysis <RUN_DIR>
```

Optional RPS forecast figure (needs `rps_forecast.csv`):

```bash
.venv/bin/python examples/plot_rps_forecast.py <RUN_DIR>
```

Filter to one app:

```bash
.venv/bin/python examples/compare_trace_vs_log.py <RUN_DIR> --app demo_app
```

### End-to-end day‑80 example

```bash
cd /Users/ahmad/research/ehsan_moradi/HierarchicalEdgeSim
export MPLCONFIGDIR=/tmp/mpl

.venv/bin/python examples/run_with_autoscaler.py configs/demo_wc_day80_proactive_1h_onec.yaml
# copy the printed path, e.g. results/proactive_wc_day80_1h_onec/42_YYYYMMDDTHHMMSSZ

RUN_DIR=results/proactive_wc_day80_1h_onec/<run_id>
.venv/bin/python examples/compare_trace_vs_log.py "$RUN_DIR"
.venv/bin/python examples/plot_rps_forecast.py "$RUN_DIR"
open "$RUN_DIR/analysis/demo_app/scaling_decisions.png"   # macOS
```

### Output layout

```text
<RUN_DIR>/
  actions.csv                 # resize / need_horizontal (proactive_up / proactive_down)
  rps_forecast.csv            # lead=0 observations + lead=1..H forecasts
  run_meta.yaml
  apps/<app>/<ms>/<cid>.log.csv
  analysis/
    <app>/
      scaling_decisions.png   # RPS (if present) + CPU/RAM alloc/used + ▲ up / ▼ down
      trace_vs_log_requests.png
      <cid>_cpu.png
      <cid>_ram.png
    rps_forecast/             # from plot_rps_forecast.py
      <ms>_rps_forecast.png
```

### What to look for (healthy proactive run)

| Plot | Healthy signal |
| --- | --- |
| `scaling_decisions.png` | After warm-up: CPU **and** RAM alloc step with ▲/▼; **used** tracks load (not stuck at min) |
| `trace_vs_log_requests.png` | After first scale-up: `sum served` follows incoming; early ticks may drop while at floor |
| `*_cpu.png` / `*_ram.png` | Capacity ≠ usage when load is present; both series move after scale events |
| `actions.csv` | `proactive_up` / `proactive_down` with `result_code=OK` |

**Note:** Serving uses only headroom above `cpu_min` / `ram_min`. Decide sizes `A_req = min + ρ·r★·tick_sec/θ` so RAM/CPU floors are not omitted (otherwise RAM never grows and μ stays 0).

Code layout:

```text
examples/analysis/
  io.py          # traces, container logs, actions.csv, run_meta
  aggregate.py   # sum + group by app/ms
  plots.py       # requests / CPU / RAM / scaling_decisions
  report.py      # analyze_run(run_dir)
  __main__.py    # CLI
examples/compare_trace_vs_log.py   # thin wrapper → analyze_run
examples/plot_rps_forecast.py      # optional forecast-only figure
```

---

## 5) One-command two-cluster flow (env-only)

```bash
.venv/bin/pytest tests/ -q && \
RUN_DIR=$(.venv/bin/python examples/run_env_only.py configs/demo_60_two_clusters.yaml | sed -n 's/^Run complete. Outputs written to: //p') && \
.venv/bin/python examples/compare_trace_vs_log.py "$RUN_DIR"
```
