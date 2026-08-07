# How to Run Proactive LSTM + Decide/Apply Demos

End-to-end guide for **tests**, **model install**, **proactive demos** (forecast + vertical scale), and **analysis plots**.

Related:

- Decide+apply plan: [proactive-decide-and-apply-plan.md](./proactive-decide-and-apply-plan.md)
- Implementation steps: [proactive-decide-and-apply-implementation-steps.md](./proactive-decide-and-apply-implementation-steps.md)
- General demos/plots: [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md)
- Training / FIFA CSV pipeline: sibling repo `microservice-workload-predictor/`

---

## 1) Setup

```bash
cd /Users/ahmad/research/ehsan_moradi/HierarchicalEdgeSim
python3.14 -m venv .venv
.venv/bin/pip install -e ".[dev,lstm]"   # torch, sklearn, joblib — required for proactive
.venv/bin/pip install matplotlib
export MPLCONFIGDIR=/tmp/mpl             # optional; avoids cache permission issues
```

---

## 2) Unit / integration tests

```bash
# full suite
.venv/bin/pytest tests/ -q

# proactive-focused
.venv/bin/pytest tests/test_proactive_decide.py \
                 tests/test_proactive_allocate.py \
                 tests/test_proactive_auto_scaler.py \
                 tests/test_common_distribute.py -q
```

LSTM-specific cases in `test_proactive_auto_scaler.py` skip cleanly if `models/rps_lstm_v1/` weights are missing.

---

## 3) Model bundle

Default location:

```text
models/rps_lstm_v1/
  lstm_edge_weights.pth
  traffic_scaler.pkl
  meta.json
```

YAML (defaults already match a typical bundle):

```yaml
autoscaler:
  name: proactive_auto_scaler
  params:
    ttw_ticks: 60
    feature_window: 10          # must match meta.json
    horizon_H: 3
    theta_up: 0.70
    theta_down: 0.45
    theta_target: 0.50
    sustained_tau: 2
    cooldown_C: 1
    model_path: models/rps_lstm_v1/lstm_edge_weights.pth
    scaler_path: models/rps_lstm_v1/traffic_scaler.pkl
    meta_path: models/rps_lstm_v1/meta.json
```

`model_path` / `scaler_path` / `meta_path` may be omitted to use `models/rps_lstm_v1/` by default.

### Install a newly trained model

```bash
cd /Users/ahmad/research/ehsan_moradi/microservice-workload-predictor
python train_lstm.py \
  --data dataset/fifa98_bursts_1m_combined.csv \
  --out-dir artifacts/fifa_1m \
  --feature-window 10

cp artifacts/fifa_1m/lstm_edge_weights.pth \
   artifacts/fifa_1m/traffic_scaler.pkl \
   artifacts/fifa_1m/meta.json \
   ../HierarchicalEdgeSim/models/rps_lstm_v1/
```

Checklist: `meta.json` `feature_window` == YAML; scaler unit family matches online TTW RPS (`ttw_ticks=60`, `tick_sec=1` ≈ minute averages).

---

## 4) Demo configs

| Config | Trace | Length | Role |
| --- | --- | --- | --- |
| **`configs/demo_wc_day80_proactive_1h_onec.yaml`** | `api_wc_day80_1s.csv` | 3600 | **Primary:** 1 container, decide+apply, expect up+down |
| `configs/demo_wc_day80_proactive_lstm.yaml` | same | 3600 | 2 containers |
| `configs/demo_3600_proactive_lstm.yaml` | smooth hill | 3600 | Hill load |
| `configs/demo_300_proactive_auto_scaler.yaml` | phased 300 | 300 | Short smoke (may need smaller TTW/W) |

### FIFA day‑80 1 Hz trace

Sim file: `traces/demo/api_wc_day80_1s.csv` (first 3600 seconds).  
`ttw_ticks: 60` → one RPS sample / decide per simulated minute; `feature_window: 10` → first decide at TTW 10 (τ=600).

Regenerate the 1‑hour prefix from the sibling repo if needed (see older snippet in git history / training docs).

---

## 5) Run demos + analyze

Always from HierarchicalEdgeSim root.

### Primary: day 80, one container, scale up/down

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_wc_day80_proactive_1h_onec.yaml
# prints: Run complete. Outputs written to: results/proactive_wc_day80_1h_onec/<run_id>

RUN_DIR=results/proactive_wc_day80_1h_onec/<run_id>

# Full analysis (requests + CPU/RAM + scaling_decisions.png)
.venv/bin/python examples/compare_trace_vs_log.py "$RUN_DIR"

# Optional forecast-quality figure
.venv/bin/python examples/plot_rps_forecast.py "$RUN_DIR"
```

Open:

```text
$RUN_DIR/analysis/demo_app/scaling_decisions.png
$RUN_DIR/analysis/demo_app/trace_vs_log_requests.png
$RUN_DIR/analysis/demo_app/c-api-1_cpu.png
$RUN_DIR/analysis/demo_app/c-api-1_ram.png
$RUN_DIR/analysis/rps_forecast/api_rps_forecast.png   # if plot_rps_forecast was run
```

### Other demos

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_3600_proactive_lstm.yaml
.venv/bin/python examples/compare_trace_vs_log.py results/proactive_3600_lstm/<run_id>
.venv/bin/python examples/plot_rps_forecast.py results/proactive_3600_lstm/<run_id>
```

---

## 6) Outputs to inspect

| File | Meaning |
| --- | --- |
| `actions.csv` | Vertical decisions: `proactive_up` / `proactive_down` / `need_horizontal` + `result_code` |
| `rps_forecast.csv` | `lead=0` observations + `lead=1..H` forecasts |
| `apps/.../*.log.csv` | Per-tick incoming / served / dropped / CPU·RAM capacity & used |
| `analysis/<app>/scaling_decisions.png` | RPS + alloc/used + ▲ up / ▼ down markers |
| `analysis/<app>/trace_vs_log_requests.png` | Trace vs incoming / served / dropped |
| `analysis/rps_forecast/*.png` | Observed RPS vs forecasts + lead‑1 error |

### Healthy vs broken signals

| Signal | Healthy | Broken (seen before floor-fix) |
| --- | --- | --- |
| After first up | Served tracks incoming; CPU/RAM **used** moves with load | `served≈0`, usage stuck at min, RAM alloc flat |
| `scaling_decisions.png` RAM panel | Alloc steps with markers | Constant line at `ram_min` |
| Warm-up (τ &lt; 600 with defaults) | Drops OK (floor, no headroom) | — |

Decide residual includes the deployment floor:  
`A_req = min + ρ · r★ · tick_sec / θ_target` (see plan §7.3 / `decide.py`).

---

## 7) Forecast-only evaluation (optional)

1. Open `analysis/rps_forecast/<ms>_rps_forecast.png`.
2. Join `rps_forecast.csv`: for `lead=h`, match observation with same `ms_id` and `ttw == target_ttw`.
3. MAE / floored MAPE by lead.
4. Forecasts appear only after `feature_window` TTWs; history never stores `r_hat`.

---

## 8) Quick checklist

```bash
cd /Users/ahmad/research/ehsan_moradi/HierarchicalEdgeSim
.venv/bin/pip install -e ".[dev,lstm]"
.venv/bin/pytest tests/test_proactive_decide.py tests/test_proactive_allocate.py tests/test_proactive_auto_scaler.py -q

.venv/bin/python examples/run_with_autoscaler.py configs/demo_wc_day80_proactive_1h_onec.yaml
.venv/bin/python examples/compare_trace_vs_log.py results/proactive_wc_day80_1h_onec/<run_id>
.venv/bin/python examples/plot_rps_forecast.py results/proactive_wc_day80_1h_onec/<run_id>
```
