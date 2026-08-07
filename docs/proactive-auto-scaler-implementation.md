# Implementation Guide — `proactive_auto_scaler`

**Status:** Steps 1 and 2 complete and since simplified: the `average` predictor and
`max_ticks` partial-run support (both used only as Step‑1 scaffolding) were removed
once the LSTM predictor was wired up end-to-end. `proactive_auto_scaler` now always
uses the one-step LSTM predictor (`predictors/lstm_torch.py`); see
[how-to-run-proactive-lstm-tests.md](./how-to-run-proactive-lstm-tests.md) for current
usage. The Step 1/Step 2 plan below is kept as historical design record — the
`predictor: average | lstm` param and `average.py` file it references no longer exist.  
**Design background:** [rps-forecast-predict-and-decide.md](./rps-forecast-predict-and-decide.md)  
**This file is the build plan.** Prefer this over the design doc when implementing.

---

## Progress

| Step | Scope | Status |
| --- | --- | --- |
| **1** | TTW RPS + history + average forecast + long `rps_forecast.csv` (no actions) | **Done** |
| **2** | Swap / add LSTM via `OneStepRpsPredictor` using `microservice-workload-predictor` | **Plan below — not coded yet** |
| **3** | PredictAndDecide (Up/Down/`sustained`/residuals, cooldown, κ) | Later |

Step 1 package layout, CSV schema, and acceptance remain as implemented under `autoscaler/proactive_auto_scaler/`. Sections [§1–§8](#1-how-this-fits-the-current-logging-practice) below are the **frozen Step‑1 reference**. New work starts at [§10](#10-step-2--lstm-from-microservice-workload-predictor).

---

## What Step 1 built (summary)

```text
each tick
  → add container lambda_in counts into a TTW bucket
when a TTW closes (every L ticks)
  → compute observed RPS for each microservice
  → append to sliding history of length feature_window (F)
  → always log observation (lead=0, r_t)
  → if history full: predict next H RPS (average) + log lead=1..H
at end of Env.run
  → flush results/<run_id>/rps_forecast.csv
```

No scaling actions. Predictor is swappable at `predict_next(x) -> float`.

### Out of scope until their steps

| Deferred | When |
| --- | --- |
| LSTM / FIFA checkpoint | **Step 2** (this update) |
| Up / Down / `sustained` / residuals | Step 3 |
| Cooldown, `kappa`, `theta_*`, MAPE gate | Step 3 |
| BEV / BEH / spawn / resize | Ladder — later |

---

## Confirmed locks (still hold)

1. Scaler folder / YAML name: **`proactive_auto_scaler`**
2. Step 1–2: no env actions (`[]` always) until Step 3
3. Logging: buffer in memory → one CSV at run end
4. Forecast log is **long / tidy** (join on `target_ttw` + `ms_id`)
5. History stores **only** observed \( r_t \); recursive roll uses a scratch copy
6. Online RPS from container `lambda_in` only — **no traces inside the scaler**

---

## 1. How this fits the current logging practice

Today:

| Buffer during run | Flushed by | File under `results/<run_id>/` |
| --- | --- | --- |
| `Env.action_log` | `write_run_outputs` → `_write_actions_csv` | `actions.csv` |
| per-container `history` | `write_run_outputs` → `_write_container_log` | `apps/.../<id>.log.csv` |
| autoscaler meta | `write_run_outputs` → `run_meta.yaml` | `run_meta.yaml` key `autoscaler` |
| `scaler.rps_forecast_log` | `write_run_outputs` → `_write_rps_forecast_csv` | **`rps_forecast.csv`** |

Rules: append only while ticking; header-only CSV if empty; do not overload `actions.csv`.

---

## 2. Package layout (Step 1 — done; Step 2 adds files marked ★)

```text
autoscaler/proactive_auto_scaler/
  __init__.py
  params.py              # Step 2: + predictor name + model/scaler paths
  ttw_rps.py
  history.py
  predictors/
    base.py              # OneStepRpsPredictor: predict_next(x) -> float
    average.py           # mean(x)
    lstm_torch.py        # ★ Step 2 adapter
  forecast.py            # recursive horizon on scratch copy (unchanged contract)
  policy.py              # select predictor from params; same logging
```

Register name already: `"proactive_auto_scaler"`.

**Artifacts (not Python source) — Step 2:**

```text
HierarchicalEdgeSim/models/rps_lstm_v1/   # or path from YAML
  lstm_edge_weights.pth    # from microservice-workload-predictor (or retrained)
  traffic_scaler.pkl       # MinMaxScaler fitted at train time
  meta.json                # ★ required: feature_window F, units, train L, notes
```

---

## 3. Parameters

### Step 1 (already used)

```yaml
autoscaler:
  enabled: true
  name: proactive_auto_scaler
  params:
    ttw_ticks: 1         # L
    feature_window: 30   # F
    horizon_H: 3         # H
```

### Step 2 additions (plan — do not invent extras)

```yaml
autoscaler:
  enabled: true
  name: proactive_auto_scaler
  params:
    ttw_ticks: 60
    feature_window: 30          # MUST equal LSTM train seq_length (see §10.3)
    horizon_H: 3
    predictor: lstm             # average | lstm  (default: average)
    model_path: models/rps_lstm_v1/lstm_edge_weights.pth
    scaler_path: models/rps_lstm_v1/traffic_scaler.pkl
    # optional: meta_path: models/rps_lstm_v1/meta.json
```

| Param | Meaning |
| --- | --- |
| `predictor` | Which `OneStepRpsPredictor` `policy` constructs. |
| `model_path` / `scaler_path` | Checkpoint + train-time `MinMaxScaler`. Required when `predictor: lstm`. |
| `feature_window` | Still \( F \): history length **and** LSTM input sequence length. |

---

## 4. Core behavior (Step 1 — unchanged)

### 4.1–4.2 TTW close

Same as implemented: \( r_t = N_m / (L \cdot tick\_sec) \); log `lead=0`; if history full, `forecast_horizon` + log `lead=1..H`.

### 4.3 Average predictor (baseline)

```text
predict_next(x): return mean(x)   # len(x) == F
```

### 4.4 History purity

History = real \( r_t \) only. Predictions never enter the ring buffer.

---

## 5. CSV schema: `rps_forecast.csv` (long format)

Unchanged. Join `lead=h` forecasts to later `lead=0` observations via `target_ttw` + `ms_id`. Same columns; Step 2 only changes how `r_hat` is produced.

---

## 6. Build steps — Step 1 (done)

A–F completed: register → TTW/history → average forecast → policy log → CSV flush → demos (`demo_300_*`, `demo_3600_*`) + `plot_rps_forecast.py`.

---

## 7. Acceptance (Step 1) — met

1. YAML-selectable `proactive_auto_scaler`.
2. Correct TTW RPS from `lambda_in` (validated vs smooth-hill trace).
3. Forecast after \( F \) samples; history purity.
4. Long `rps_forecast.csv`.
5. No actions.
6. Pytest green.

---

## 8. How to manually check a run

```bash
cd HierarchicalEdgeSim
.venv/bin/python examples/run_with_autoscaler.py configs/demo_3600_proactive_auto_scaler.yaml
.venv/bin/python examples/plot_rps_forecast.py results/proactive_3600/<run_id>
```

Average predictor: lag on rising/falling load is **expected**.

---

## 9. After Step 2 — Decide (still later)

Up/Down/`sustained`/residuals, cooldown, confidence gating. Reuse the same `r_t` / `r_hat` series. Predictor quality can be evaluated from `rps_forecast.csv` **before** any scaling actions.

---

## 10. Step 2 — LSTM from `microservice-workload-predictor`

**Source repo (sibling of HierarchicalEdgeSim):**  
`/Users/ahmad/research/ehsan_moradi/microservice-workload-predictor/`

Do **not** treat that repo’s `ProactiveScalerController` as the HierarchicalEdgeSim autoscaler. It is an **inference helper** only. Our scaler stays `proactive_auto_scaler`; the LSTM becomes one `OneStepRpsPredictor` implementation.

### 10.1 What that repo actually ships

| File | Role |
| --- | --- |
| `predictor_module.py` | `WorkloadPredictor` (PyTorch LSTM `hidden=16` + linear) + `ProactiveScalerController.get_prediction(window)` |
| `lstm_edge_weights.pth` | Trained `state_dict` |
| `traffic_scaler.pkl` | `sklearn.preprocessing.MinMaxScaler` fitted on training series |
| `train_lstm.py` | Offline train script (FIFA98-style CSV, asymmetric under-predict loss) |
| `wc_day6_1_bursts.csv` | Minute-level `request_count` (~1440 rows) |
| `how-to-use-the-predictor.md` | Example: last **30** points → next-step count |
| `Pipfile` | `torch`, `numpy`, `scikit-learn`, `pandas`, `matplotlib` (Python 3.12) |

**Inference contract in their code today:**

```text
raw window (length W) 
  → MinMaxScaler.transform 
  → tensor (1, W, 1) 
  → LSTM → linear 
  → inverse_transform 
  → int(request_count) for next step
```

Architecture matches design **O1** (offline one-step + recursive multi-horizon at runtime) in [rps-forecast-predict-and-decide.md](./rps-forecast-predict-and-decide.md) §5.

### 10.2 Mismatches we must resolve before wiring (do not paper over)

These are the important findings from scanning the predictor repo against HierarchicalEdgeSim Step 1.

#### A. Sequence length inconsistency **inside** the predictor repo

| Location | Window length |
| --- | --- |
| `train_lstm.py` | `seq_length = 5` |
| `predictor_module.py` / how-to | hard-requires **`len == 30`** |

LSTM weights do not hard-code sequence length, but **training used \( F=5 \)**. Calling inference with \( F=30 \) on those weights is **not** the same model that was trained.

**Lock for Step 2:**

1. Pick one \( F \) and make train + infer + YAML `feature_window` identical.
2. Prefer **retrain** with `seq_length = feature_window` (recommend start with **\( F=30 \)** to match the design baseline and their how-to), **or** temporarily set `feature_window: 5` and change their controller check to 5 — only if we keep the existing `.pth` without retraining.
3. Write \( F \) into `meta.json` and **assert** at load time: `params.feature_window == meta.feature_window`.

#### B. Units / semantics: their target ≠ our \( r_t \)

| | `microservice-workload-predictor` | HierarchicalEdgeSim proactive Step 1 |
| --- | --- | --- |
| Series | Per-**minute** `request_count` (FIFA bursts) | **TTW-average RPS** (req/s) from `lambda_in` |
| Typical scale | hundreds–thousands of requests / minute | demo hill ~40–300 **per second** (depends on trace) |
| Output | `int` count | `float` RPS for logs / later util bridge |

**Do not** drop the FIFA checkpoint onto the smooth-hill RPS series and expect meaningful forecasts. Scale and time base differ.

**Allowed paths (choose explicitly in Step 2 demos):**

| Path | When to use | What to do |
| --- | --- | --- |
| **P1 — Retrain on sim TTW-RPS (recommended for thesis integration)** | Evaluate predictor inside HierarchicalEdgeSim on our traces | Export `lead=0` `r_t` from long runs (or build offline from the same TTW formula), train with `train_lstm.py`-style pipeline on that series, save new `.pth` + `.pkl` + `meta.json` (`units: ttw_rps`) |
| **P2 — Keep FIFA model, feed FIFA-scale counts** | Reproduce their notebook-style eval only | Drive a trace whose **per-TTW request totals** match minute counts; either predict **counts** and convert `r_hat = count_hat / (L * tick_sec)`, or define TTW so one TTW ≈ one training minute and document the mapping in `meta.json` |
| **P3 — Smoke-only** | CI / wiring test | Tiny synthetic series scaled into the existing scaler range; assert finite `r_hat` and CSV shape — **not** a quality claim |

Default for the HierarchicalEdgeSim demo after Step 2: **P1**.

#### C. API shape vs our predictor protocol

| Their `ProactiveScalerController` | Our `OneStepRpsPredictor` |
| --- | --- |
| `get_prediction(sliding_window) -> int` | `predict_next(x: list[float]) -> float` |
| Owns model+scaler load | Same, but behind protocol |
| Not recursive | Recursion stays in **`forecast.py`** (call `predict_next` \( H \) times on scratch \( \mathbf{z} \)) |

**Adapter rule:** implement `predictors/lstm_torch.py` that:

- loads weights + scaler (paths from params);
- implements `predict_next(x)` with **float** RPS (or float count then convert — see P1/P2);
- does **not** return `int` (truncation hurts low RPS and residuals later);
- does **not** mutate history;
- on bad input / non-finite output: raise or return a sentinel that `policy` treats as “no forecast this TTW” (log `lead=0` only; same as warm-up) — align with design §3.4.

#### D. Normalization and recursive roll

Design Option B: durable history in **real** units; transform at predictor boundary; prefer recursive roll in **normalized** space, inverse each emitted lead (or inverse at the end of each step consistently).

Their helper inverse-transforms **every** one-step call. That is fine if `forecast_horizon` always passes **real-unit** windows into `predict_next` (each call re-transforms). Prefer that first (matches current `forecast.py` + average). Optional later: a `predict_next_norm` path for pure norm-space roll — not required for first LSTM wiring.

**Never** mix a scaler fitted on FIFA counts with real RPS inputs (see B).

#### E. Dependencies

HierarchicalEdgeSim today: `pyyaml` only (+ pytest). Their stack needs **`torch`**, **`numpy`**, **`scikit-learn`** (for the pickle), **`joblib`**.

**Lock:**

- Add an **optional** extra, e.g. `[project.optional-dependencies] lstm = ["torch", "numpy", "scikit-learn", "joblib"]` (pin reasonably).
- `predictor: average` must work **without** torch installed.
- `predictor: lstm` import/load fails with a clear error if extras missing.
- Python: their Pipfile says 3.12; HierarchicalEdgeSim requires `>=3.14` — verify torch wheels for the env before claiming CI coverage; if blocked, document “LSTM demos local-only” until resolved.

#### F. Naming / packaging

- **Do not** `sys.path` hack to the sibling git repo long-term.
- **Do:** copy or vendor the small inference pieces into `predictors/lstm_torch.py` (architecture + load), and place weight/scaler files under `HierarchicalEdgeSim/models/...`.
- Keep `train_lstm.py` either as a script under `HierarchicalEdgeSim/scripts/` (adapted to read TTW-RPS CSV) or document “train in sibling repo, copy artifacts.” Prefer one training entrypoint documented in this plan’s acceptance.

### 10.3 How we use it in the existing Step‑1 loop

No change to TTW accumulation or CSV schema.

```text
on TTW close for ms m:
  r_t = counts_to_rps(...)
  history.append(r_t)                 # real only
  log lead=0
  if history full (len == F):
      x = history.as_list()           # length F, real RPS (or P2-mapped units)
      preds = forecast_horizon(x, H, predictor=lstm_or_average)
      log lead=1..H with r_hat
  return []                           # still no actions in Step 2
```

```text
# lstm predict_next (conceptual)
predict_next(x_real):                 # len == F
    x_n = scaler.transform(x_real)
    y_n = model(tensor(x_n))          # one step
    y   = scaler.inverse_transform(y_n)
    validate finite; clip y >= 0
    return float(y)
```

`policy.py` constructs predictor once in `build()` / `__init__` from `params.predictor`.

### 10.4 Build order (Step 2 only)

Do in order; keep average path and full pytest green **without** torch.

1. **Lock artifacts + meta**  
   - Resolve \( F \) (retrain vs use 5).  
   - Add `meta.json`: `{ "feature_window", "units", "ttw_ticks_train", "tick_sec_train", "source", "loss" }`.  
   - Copy weights/scaler into `HierarchicalEdgeSim/models/rps_lstm_v1/`.

2. **Optional deps + guard**  
   - `pyproject` optional `lstm` extra.  
   - Import torch only inside `lstm_torch.py`.

3. **`LstmTorchPredictor` adapter**  
   - Same architecture as `WorkloadPredictor`.  
   - `predict_next` float API; length check vs `feature_window`.  
   - Unit tests with a **tiny fake** `state_dict` + identity-like scaler **or** skip-if-no-torch; plus one golden test if real weights present.

4. **Params + `build()` selection**  
   - `predictor: average | lstm`.  
   - Assert `feature_window` matches `meta` when lstm.

5. **Policy smoke**  
   - Same logging; compare average vs lstm on identical run (two configs).  
   - Still `actions.csv` header-only.

6. **Training path P1 (recommended)**  
   - Script: read prior `rps_forecast.csv` (`lead=0`) or generate TTW-RPS offline → train → write models dir.  
   - Retrain with `seq_length == feature_window`.  
   - Keep asymmetric loss optional (document; matches their under-provision bias).

7. **Demo config + plot**  
   - e.g. `configs/demo_3600_proactive_lstm.yaml` on a trace consistent with the **trained** series (smooth hill only if P1-retrained on that family or similar).  
   - Reuse `plot_rps_forecast.py`; expect less pure lag than average if the model learned trend (not guaranteed on OOD).

### 10.5 Acceptance (Step 2)

1. `predictor: average` unchanged; no torch required.
2. `predictor: lstm` loads checkpoint + scaler; `feature_window` matches train meta.
3. `rps_forecast.csv` still long-format; `r_hat` finite floats; history purity preserved.
4. Recursive \( H \) leads still produced only via `forecast_horizon` + one-step LSTM (no multi-output head required).
5. Documented train/infer \( F \) alignment (no silent 5-vs-30).
6. Documented units path (P1 or P2); demo does not claim FIFA weights on RPS hill without conversion/retrain.
7. Tests: adapter + policy selection; full suite green with average; LSTM tests gated or optional.

### 10.6 Explicit non-goals for Step 2

- No Up/Down actions, cooldown, or κ.
- No online training / fine-tune during `Env.run`.
- No reading workload traces inside the scaler.
- No replacing `forecast.py` with their controller loop.
- No dependency on the sibling repo at runtime after artifacts are copied.

### 10.7 Manual check (after Step 2 coding)

```bash
# average baseline (no torch)
.venv/bin/python examples/run_with_autoscaler.py configs/demo_3600_proactive_auto_scaler.yaml

# LSTM (after extras + checkpoint aligned to F and units)
.venv/bin/pip install -e ".[lstm]"
.venv/bin/python examples/run_with_autoscaler.py configs/demo_3600_proactive_lstm.yaml
.venv/bin/python examples/plot_rps_forecast.py results/.../<run_id>
# Compare lead=1 MAE vs average on the same trace
```

---

## 11. Design alignment summary

| Design lock ([rps-forecast…](./rps-forecast-predict-and-decide.md)) | How Step 2 uses the external predictor |
| --- | --- |
| O1 offline one-step LSTM | Their `WorkloadPredictor` + `.pth` |
| Option B fixed scaler | Their `traffic_scaler.pkl` (re-fit on P1 data) |
| Real RPS at API boundary | Adapter returns float in sim units |
| Recursive multi-horizon | Existing `forecast.py`, not their how-to loop |
| \( W \) / `feature_window` | Must equal train `seq_length` after we fix their 5↔30 bug |
| No trace access online | Unchanged |

**Bottom line:** reuse the **architecture + train/infer pattern** from `microservice-workload-predictor`; wrap it as `LstmTorchPredictor`; fix window/units before trusting plots; keep average as default and CSV evaluation path.
