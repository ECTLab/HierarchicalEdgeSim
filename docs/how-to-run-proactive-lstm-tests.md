# How to Run Proactive LSTM Forecast Tests

End-to-end guide for **tests**, **installing trained models**, and **running demos** (including the FIFA day‑80 1 Hz trace).

Related:

- Implementation plan: [proactive-auto-scaler-implementation.md](./proactive-auto-scaler-implementation.md)
- General demos/plots: [how-to-rerun-tests-and-graphs.md](./how-to-rerun-tests-and-graphs.md)
- Training / FIFA CSV pipeline: sibling repo `microservice-workload-predictor/` (`train_lstm.py`, `docs/lstm-accuracy-and-realistic-traces.md`)

---

## 1) Setup

```bash
cd /Users/ahmad/research/ehsan_moradi/HierarchicalEdgeSim
python3.14 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pip install -e ".[lstm]"    # torch, sklearn, joblib, numpy
.venv/bin/pip install matplotlib      # for plot scripts
```

Average predictor demos work **without** `[lstm]`. LSTM demos need the optional extra.

---

## 2) Unit / integration tests

```bash
# full suite
.venv/bin/pytest tests/ -q

# proactive autoscaler only (average + LSTM gated on torch/artifacts)
.venv/bin/pytest tests/test_proactive_auto_scaler.py -v
```

LSTM tests skip cleanly if weights under `models/rps_lstm_v1/` are missing or torch is not installed.

---

## 3) Where the autoscaler loads the model

Default bundle (used when YAML omits paths, or when configs point here):

```text
HierarchicalEdgeSim/models/rps_lstm_v1/
  lstm_edge_weights.pth
  traffic_scaler.pkl
  meta.json
```

Code: `autoscaler/proactive_auto_scaler/predictors/lstm_torch.py` (`default_model_dir()`).

Configs typically set explicit relative paths (cwd = HierarchicalEdgeSim when using `examples/run_with_autoscaler.py`):

```yaml
autoscaler:
  name: proactive_auto_scaler
  params:
    predictor: lstm
    feature_window: 10          # must match meta.json
    model_path: models/rps_lstm_v1/lstm_edge_weights.pth
    scaler_path: models/rps_lstm_v1/traffic_scaler.pkl
    meta_path: models/rps_lstm_v1/meta.json
```

**Normalization:** same as training — history stays in real units; `MinMaxScaler.transform` → LSTM → `inverse_transform`. HierarchicalEdgeSim does **not** import `predictor_module.py`; it vendors the same pattern in `lstm_torch.py`.

---

## 4) Install a newly trained model

Train in the sibling repo (example: multi-day minute averages):

```bash
cd /Users/ahmad/research/ehsan_moradi/microservice-workload-predictor
python train_lstm.py \
  --data dataset/fifa98_bursts_1m_combined.csv \
  --out-dir artifacts/fifa_1m \
  --feature-window 10
```

Copy the three artifacts into HierarchicalEdgeSim (overwrites the active bundle):

```bash
cp artifacts/fifa_1m/lstm_edge_weights.pth \
   artifacts/fifa_1m/traffic_scaler.pkl \
   artifacts/fifa_1m/meta.json \
   ../HierarchicalEdgeSim/models/rps_lstm_v1/
```

Or keep several bundles and point YAML `model_path` / `scaler_path` / `meta_path` at another folder under `models/`.

Checklist after install:

1. `meta.json` → `feature_window` equals YAML `feature_window`
2. Scaler was fit on the **same unit family** you will observe online (e.g. minute-avg of per-second counts ≈ TTW RPS with `ttw_ticks=60`, `tick_sec=1`)
3. Re-run a short pytest LSTM case or a demo below

---

## 5) Demo traces and configs

| Config | Trace | Length | Predictor | Notes |
| --- | --- | --- | --- | --- |
| `configs/demo_3600_proactive_auto_scaler.yaml` | `api_3600_smooth_hill.csv` | 3600 ticks | `average` | Baseline lag on hill |
| `configs/demo_3600_proactive_lstm.yaml` | same hill | 3600 | `lstm` | Needs model bundle |
| `configs/demo_wc_day80_proactive_lstm.yaml` | `api_wc_day80_1s.csv` | **3600** ticks (first 1 h @ 1 Hz) | `lstm` | Prefix of FIFA day 80 1 s bursts |
| `configs/demo_300_proactive_auto_scaler.yaml` | phased 300 | 300 | `average` | Few TTWs if `ttw_ticks` large |

### 5.1 FIFA day‑80 1 Hz trace

Source: `microservice-workload-predictor/wc_day80_bursts_1s.csv`  
Sim file: `traces/demo/api_wc_day80_1s.csv` (`time_unit,requests`, **first 3600 seconds only** for a fast demo).

Mapping used:

- each CSV second → one sim tick (`tick_sec: 1`)
- `request_count` → `requests`
- `ttw_ticks: 60` → TTW RPS ≈ mean requests/sec over that minute (60 TTWs in this 1 h run)

Regenerate the 1‑hour prefix:

```bash
cd /Users/ahmad/research/ehsan_moradi/microservice-workload-predictor
python - <<'PY'
import csv
from pathlib import Path
src = Path("wc_day80_bursts_1s.csv")
dst = Path("../HierarchicalEdgeSim/traces/demo/api_wc_day80_1s.csv")
n_keep = 3600
with src.open() as fin, dst.open("w", newline="") as fout:
    r = csv.DictReader(fin)
    w = csv.writer(fout)
    w.writerow(["time_unit", "requests"])
    for i, row in enumerate(r, start=1):
        if i > n_keep:
            break
        w.writerow([i, row["request_count"]])
print("wrote", dst, "rows=", n_keep)
PY
```

---

## 6) Run demos and plot forecasts

Always from HierarchicalEdgeSim root:

```bash
cd /Users/ahmad/research/ehsan_moradi/HierarchicalEdgeSim
```

### Average baseline (1‑hour hill)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_3600_proactive_auto_scaler.yaml
# → results/proactive_3600/<run_id>/
.venv/bin/python examples/plot_rps_forecast.py results/proactive_3600/<run_id>
```

### LSTM on hill

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_3600_proactive_lstm.yaml
.venv/bin/python examples/plot_rps_forecast.py results/proactive_3600_lstm/<run_id>
```

### LSTM on FIFA day 80 (first 1 hour — 3600 ticks)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_wc_day80_proactive_lstm.yaml
# → results/proactive_wc_day80_lstm/<run_id>/
.venv/bin/python examples/plot_rps_forecast.py results/proactive_wc_day80_lstm/<run_id>
```

### Outputs to inspect

| File | Meaning |
| --- | --- |
| `rps_forecast.csv` | Long log: `lead=0` observations + `lead=1..H` forecasts |
| `run_meta.yaml` | Autoscaler name + params (including model paths) |
| `actions.csv` | Header-only until Decide/actions are implemented |
| `analysis/rps_forecast/*.png` | Observed vs forecast + lead‑1 abs error |

---

## 7) How to evaluate results

1. **Plot:** open `analysis/rps_forecast/api_rps_forecast.png`.
2. **Join in CSV:** for each forecast row (`lead=h`), find observation with same `ms_id` and `ttw == target_ttw`; error = `r_hat - r_t`.
3. **Metrics:** MAE / floored MAPE by `lead`; compare **lstm** vs **average** on the **same** trace.
4. **Sanity:** forecasts start only after `feature_window` TTWs; history never stores `r_hat`.

If LSTM looks worse than average on an OOD scale (e.g. old day‑6 scaler on hill RPS), reinstall a checkpoint trained on a matching series (§4) and re-run.

---

## 8) Quick checklist

```bash
cd /Users/ahmad/research/ehsan_moradi/HierarchicalEdgeSim
.venv/bin/pip install -e ".[dev,lstm]"
.venv/bin/pytest tests/test_proactive_auto_scaler.py -q
# after copying fresh artifacts into models/rps_lstm_v1/:
.venv/bin/python examples/run_with_autoscaler.py configs/demo_wc_day80_proactive_lstm.yaml
.venv/bin/python examples/plot_rps_forecast.py results/proactive_wc_day80_lstm/<run_id>
```
