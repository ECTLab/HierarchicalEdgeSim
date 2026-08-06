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
```

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
