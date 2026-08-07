# Re-run Tests and Generate Graphs

This guide shows how to:

1. run the test suite
2. run demo simulations (1 container, 2 containers, 2 clusters / 2 apps)
3. generate per-application analysis plots

---

## 1) Setup

```bash
cd /Users/ahmad/research/ehsan_moradi/HierarchicalEdgeSim
python3.14 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pip install matplotlib
# optional — required for predictor: lstm demos / LSTM unit tests:
# .venv/bin/pip install -e ".[lstm]"
```

Proactive LSTM + FIFA day‑80 walkthrough: [how-to-run-proactive-lstm-tests.md](./how-to-run-proactive-lstm-tests.md).

---

## 2) Run tests

```bash
.venv/bin/pytest tests/ -v
```

---

## 3) Demo scenarios

### A) Single container

```bash
.venv/bin/python examples/run_env_only.py configs/demo_60.yaml
```

### B) Two containers, one app (heterogeneous routing)

```bash
.venv/bin/python examples/run_env_only.py configs/demo_60_two_containers.yaml
```

### B2) Same world with reactive vertical autoscaler (60-tick smoke)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_60_two_containers_reactive.yaml
```

### B3) Long phased scenario (300 ticks) — static vs reactive

```bash
.venv/bin/python examples/run_env_only.py configs/demo_300_two_containers.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/demo_300_two_containers_reactive.yaml
# Compare dropped_requests in the two run dirs; reactive writes actions.csv
```

### B4) Proactive RPS forecast log (no actions)

Full LSTM / FIFA day‑80 / model-install guide:  
**[how-to-run-proactive-lstm-tests.md](./how-to-run-proactive-lstm-tests.md)**

**300-tick phased** (few TTWs if `ttw_ticks` is large — may not fill `feature_window`):

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_300_proactive_auto_scaler.yaml
```

**1-hour smooth hill** (`ttw_ticks=60`, `feature_window=10` — forecasts after TTW 10):

```bash
# LSTM one-step predictor (needs models/rps_lstm_v1/ + pip install -e ".[lstm]")
.venv/bin/python examples/run_with_autoscaler.py configs/demo_3600_proactive_lstm.yaml
.venv/bin/python examples/plot_rps_forecast.py results/proactive_3600_lstm/<run_id>
```

**FIFA day 80 (1 Hz, first 1 hour / 3600 ticks)** — trace `traces/demo/api_wc_day80_1s.csv`:

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_wc_day80_proactive_lstm.yaml
.venv/bin/python examples/plot_rps_forecast.py results/proactive_wc_day80_lstm/<run_id>
```

### C) Two clusters, one app per cluster (this guide's focus)

```bash
.venv/bin/python examples/run_env_only.py configs/demo_60_two_clusters.yaml
```

Topology:

| Cluster | Servers | App | MS | Container |
|---|---|---|---|---|
| `c1` | 2 (`c1-w1`, `c1-w2`) | `web_app` | `api` | `c-web-api-1` on `c1-w1` |
| `c2` | 1 (`c2-w1`) | `media_app` | `ingest` | `c-media-ingest-1` on `c2-w1` |

Traces (both N=60):

- `traces/demo/api_60.csv`
- `traces/demo/ingest_60.csv`

Each command prints `<RUN_DIR>`, e.g. `results/42_YYYYMMDDTHHMMSSZ`.

---

## 4) Analysis helper (modular)

Code lives under `examples/analysis/`:

```text
examples/analysis/
  io.py          # read traces / logs / run_meta
  aggregate.py   # sum + group by app/ms
  plots.py       # request / CPU / RAM figures
  report.py      # analyze_run(run_dir) orchestration
  __main__.py    # CLI entry
```

Thin wrapper (preferred):

```bash
.venv/bin/python examples/compare_trace_vs_log.py <RUN_DIR>
```

Optional: analyze only one app

```bash
.venv/bin/python examples/compare_trace_vs_log.py <RUN_DIR> --app web_app
```

### Output layout (per application)

```text
<RUN_DIR>/analysis/
  web_app/
    trace_vs_log_requests.png
    c-web-api-1_cpu.png
    c-web-api-1_ram.png
  media_app/
    trace_vs_log_requests.png
    c-media-ingest-1_cpu.png
    c-media-ingest-1_ram.png
```

For each app the requests plot checks:

- MS trace == sum(incoming) over that app's containers for that MS
- per container: incoming == served + dropped

---

## 5) One-command two-cluster flow

```bash
.venv/bin/pytest tests/ -q && \
RUN_DIR=$(.venv/bin/python examples/run_env_only.py configs/demo_60_two_clusters.yaml | sed -n 's/^Run complete. Outputs written to: //p') && \
.venv/bin/python examples/compare_trace_vs_log.py "$RUN_DIR"
```
