# RPS History, Recursive Multi-Horizon Forecast, and PredictAndDecide

**Status:** design lock candidate for the predictor front-end of the proactive scaler

**Scope:** only the path from request history → forecast trajectory → Up/Down/None + `sustained` + residuals. Not BEV/BEH/vicinity/BEG.

**Related:**

- [proactive-autoscaler-approach.md](./proactive-autoscaler-approach.md)
- `proposed_method_complete.tex` (Alg. PredictAndDecide)
- [deep-research-report.md](./deep-research-report.md)

**Review:** improved after a GPT‑5.6 design review (2026-08-06). Applied fixes and deferred notes are listed in [§9](#9-review-notes-gpt-56).

---

## 1. Goal of this module

At the end of each **time tick window (TTW)** indexed by \( t \), for a microservice \( m \):

1. Compute one **TTW-average RPS** sample from observed container arrivals over that TTW (**no trace access**).
2. Maintain a sliding history of those real RPS samples.
3. Run a **one-step** predictor recursively to obtain a short horizon of **future TTW-average RPS**:

   $$
   \hat{\mathbf{r}}_{t+1:t+H} = (\hat{r}_{t+1}, \ldots, \hat{r}_{t+H}).
   $$

4. Map that trajectory (plus current observations) into:

   $$
   (\Delta,\ \delta^{\mathrm{cpu}},\ \delta^{\mathrm{ram}},\ \mathit{sustained}),
   $$

   which is the contract of **PredictAndDecide** before AllocateResources.

The ML model never outputs “spawn 2 containers.” It outputs **future TTW-average RPS**. Policy turns RPS into capacity residuals.

**Control scope (locked for v1):** one RPS series and one decision state **per microservice \( m \)** (fleet-wide over all of \( m \)’s containers). Capacity \( A_m \) in the util bridge is the **same scope** (sum of allocs over those containers). Per-\((m,c)\) local series is deferred until locality-aware routing needs it.

---

## 2. Time base, TTW, and RPS sample

### 2.1 Tick vs time tick window (TTW)

**Tick** \( \tau \): the simulator’s finest discrete time step, of wall duration `tick_sec` seconds. In HierarchicalEdgeSim, per-tick arrival quantities (`lambda_in`) are **request counts for that tick** (same units as per-tick service capacity \( \mu \)).

**Time tick window (TTW):** a contiguous block of \( L \) ticks, where \( L \ge 1 \) is a **configurable integer**. TTWs are non-overlapping and abut:

$$
\mathrm{TTW}_t
=
\{\tau :\ tL < \tau \le (t+1)L \},
\qquad t = 0,1,2,\ldots
$$

(Use consistent 0- or 1-based tick indexing in code; keep fixed length \( L \).)

Wall duration of one TTW:

$$
\Delta t_{\mathrm{TTW}} = L \cdot \mathit{tick\_sec}.
$$

| Role | Unit | Notes |
| --- | --- | --- |
| Physics / routing / history records | tick \( \tau \) | unchanged from Part A |
| RPS sample + PredictAndDecide + cooldown | **TTW** \( t \) | one RPS point and at most one scale decision per completed TTW |
| Horizon \( H \), history \( W \), cooldown \( C \) | counted in **TTWs** | not in raw ticks |

**Why TTW exists:** per-tick rates are noisy; aggregating \( L \) ticks yields a smoother average rate for the LSTM and thresholds. Raising \( L \) smooths more and slows the control loop; \( L = 1 \) is one sample per tick.

**Limitation:** the forecast target is **average RPS over the TTW**, not within-TTW bursts. Larger \( L \) hides short spikes inside the window.

**Relation to `decision_every_k_ticks`:** for this scaler, TTW length \( L \) *is* that knob (`ttw_ticks: L`). Do not maintain a second aggregation period.

### 2.2 RPS definition (per MS, per TTW) — observed arrivals only

**Lock:** at autoscaling time the scaler **does not read workload traces**. Traces drive the env’s request generator; the scaler only sees container telemetry.

**Units lock (HierarchicalEdgeSim):** `ContainerTickRecord.lambda_in` is the **number of requests assigned to that container in tick \( \tau \)** (a count for the tick, not an RPS). Therefore TTW-average RPS is:

$$
\Lambda_m(\tau)
=
\sum_{c \in \mathcal{C}_m(\tau)}
\lambda^{\mathrm{in}}_{c}(\tau)
\quad \text{[requests in tick \(\tau\)]},
$$

$$
r_t^{(m)}
=
\frac{1}{L \cdot \mathit{tick\_sec}}
\sum_{\tau \in \mathrm{TTW}_t}
\Lambda_m(\tau)
\quad \text{[requests / second]}.
$$

Equivalent view: average requests-per-tick over the TTW, divided by `tick_sec`.

Use **`lambda_in`**, not `lambda_served`, so drops on a container still count as demand.

**Internal accumulator:** implementations may first sum request counts \( N_t = \sum_{\tau}\Lambda_m(\tau) \), then set \( r_t = N_t / (L \cdot \mathit{tick\_sec}) \). The durable history and model target remain **RPS**, so changing \( L \) later stays dimensionally comparable.

**Borrowed replicas:** if they belong to MS \( m \) and report `lambda_in` on their containers, they contribute to the same per-MS sum (v1 fleet scope).

**Telemetry gap (important):** today the env distributes offered load only onto existing containers. If \( m \) has **zero replicas**, there is no container `lambda_in`, so the scaler cannot see demand from container telemetry alone. Until the env exposes an MS-level “unmet / undelivered offer” signal:

- v1 assumes \( m \) always has ≥ 1 container when proactive sensing runs, **or**
- reactive/zero-replica recovery uses a separate env signal (out of this module’s math, but must not be ignored in integration).

**Do not** substitute the MS trace series for \( \Lambda_m \) inside the scaler. Offline LSTM training may use logged TTW-RPS built with this same definition.

### 2.3 Sliding history vector (last \( \alpha \) / \( W \) real TTW-RPS)

\( W := \alpha \). Authoritative history holds **observed** TTW-average RPS only.

After TTW \( t \) completes:

$$
\mathbf{x}_t = (r_{t-W+1},\ r_{t-W+2},\ \ldots,\ r_t) \in \mathbb{R}^{W}.
$$

**Cold start:** while fewer than \( W \) real samples exist, PredictAndDecide stays **reactive** (\( \kappa = 0 \) until confidence warm-up also completes — see §4.5). Still append every real \( r_t \).

Slide on each new **real** sample only:

$$
\mathbf{x}_{t+1} = (r_{t-W+2},\ \ldots,\ r_t,\ r_{t+1}).
$$

```text
on_ttw_end(m, t):
    N_t = sum(lambda_in over containers of m, ticks in TTW_t)   # request counts
    r_t = N_t / (L * tick_sec)                                 # RPS
    history[m].append(r_t)       # real only; never from trace; never r_hat
    if len(history[m]) > W:
        history[m].drop_left()
```

**Invariant (history purity):** \( \mathbf{x}_t \) never contains \( \hat{r} \). Recursive forecasts use a scratch copy only (§3.2).

---

## 3. Recursive multi-horizon forecast

### 3.1 One-step model

$$
\hat{r}_{t+1} = f_\theta(\mathbf{x}_t).
$$

After inverse-normalization (if any), validate output (§3.4) before use.

### 3.2 Recursive roll on a working copy (does not touch \( \mathbf{x}_t \))

Set \( \mathbf{z}^{(0)} := \mathrm{copy}(\mathbf{x}_t) \). For \( h = 1, \ldots, H \):

$$
\hat{r}_{t+h} = f_\theta\bigl(\mathbf{z}^{(h-1)}\bigr)
$$

$$
\mathbf{z}^{(h)} = \bigl( z^{(h-1)}_2,\ \ldots,\ z^{(h-1)}_{W},\ \hat{r}_{t+h} \bigr)
$$

(If using normalization Option B, keep \( \mathbf{z} \) in **normalized** space for the whole roll; denormalize each \( \hat{r}_{t+h} \) when emitting the returned vector.)

Return \( \hat{\mathbf{r}}_{t+1:t+H} \); discard all \( \mathbf{z}^{(h)} \).

```text
forecast_horizon(x_t, H):          # x_t is read-only
    z = copy(x_t)                  # or normalized copy
    preds = []
    for h in 1..H:
        r_hat = predict_next(z)    # may be in normalized space
        preds.append(r_hat)
        z = concat(z[1:], [r_hat]) # mutates z only
    return inverse_transform(preds)  # real RPS; x_t unchanged
```

| Object | Lifetime | May contain predicted RPS? |
| --- | --- | --- |
| \( \mathbf{x}_t \) / `history` | durable across TTWs | **No** — real TTW-average RPS only |
| \( \mathbf{z}^{(h)} \) | one forecast call | Yes — scratch |
| \( \hat{\mathbf{r}}_{t+1:t+H} \) | current TTW (+ stash \( \hat{r}_{t+1} \) for MAPE) | Yes — outputs, not history |

**Recursive error:** short \( H \) (3–5) keeps compounding manageable; still **evaluate** multi-step error on holdout before claiming adequacy. If \( h>1 \) error is bad, fall back to direct multi-output later (O2) without changing PredictAndDecide’s external contract.

**Baseline defaults (scalars; ranges are tuning guidance only):**

| Symbol | Meaning | Baseline | Tuning range |
| --- | --- | --- | --- |
| \( L \) (`ttw_ticks`) | ticks per TTW | **1** | 1–5 |
| \( W \) (\( \alpha \)) | real history length (TTWs) | **30** | 30–60 |
| \( H \) | forecast horizon (TTWs) | **3** | 3–5 |
| \( C \) | cooldown (TTWs) | **3** (\( = H \)) | ≥ 0 |

### 3.3 Normalization (required for LSTM checkpoints)

Durable history stays in **real RPS**. The predictor boundary applies the train-time transform.

**Option B (recommended with pre-trained weights):** fixed scaler from training (`scaler.json`: method + \( \mu,\sigma \) or min/max). At inference:

1. `x_norm = transform(x_real)`
2. recursive roll in normalized space
3. `r_hat_real = inverse_transform(r_hat_norm)`
4. MAPE / decide / residuals use **real** RPS only

**Option A (online per-window z-score):** freeze \( (\mu_t, \sigma_t) \) from \( \mathbf{x}_t \) for the whole roll; training must use the **same** per-window freeze on targets. Prefer B for shipped checkpoints.

Never mix scalers between train and infer. Clip or reject non-finite inverse outputs (§3.4).

### 3.4 Model output validation

Before PredictAndDecide consumes \( \hat{\mathbf{r}} \):

- require finite values;
- clip negatives to 0 (RPS cannot be negative), or treat as inference failure;
- on NaN / Inf / inference exception: **discard forecast**, keep reactive mode for this TTW, do not update MAPE with garbage.

---

## 4. From RPS trajectory to decisions

### 4.1 Capacity and predicted utilization

Let \( A_m^{\mathrm{cpu}} \) be total CPU allocated to \( m \) (sum over its containers). Let \( \rho^{\mathrm{cpu}} \) be **CPU-seconds per request** (`cpu_per_request_cores` when `tick_sec` accounting matches the sim’s per-tick usage model).

**Full-utilization throughput** (req/s):

$$
C_t^{\mathrm{full}} = \frac{A_m^{\mathrm{cpu}}}{\rho^{\mathrm{cpu}}}.
$$

Target operating throughput is \( \theta^{\mathrm{target}} \cdot C_t^{\mathrm{full}} \). For the util ratio used in thresholds:

$$
\hat{u}^{\mathrm{cpu}}_{t+h}
=
\frac{\hat{r}_{t+h}}{\max(C_t^{\mathrm{full}}, \varepsilon)},
\qquad
u_t^{\mathrm{cpu}}
=
\frac{r_t}{\max(C_t^{\mathrm{full}}, \varepsilon)}.
$$

**RAM (sim-faithful, simplified):** HierarchicalEdgeSim already treats RAM like CPU via `ram_per_request_mb` in the same linear usage model. For v1, mirror the CPU formulas with \( \rho^{\mathrm{ram}} \) in that empirical sense. A physically accurate concurrency/residency RAM model is **out of scope** here; do not pretend MB/s is MB.

Then:

$$
\hat{u}_{t+h} = \max\bigl(\hat{u}^{\mathrm{cpu}}_{t+h},\ \hat{u}^{\mathrm{ram}}_{t+h}\bigr)
$$

(omit RAM side if `ram_per_request_mb ≈ 0`).

**Observed util for gating:** prefer

$$
u_t = \max\bigl(u_t^{\mathrm{RPS}},\ u_t^{\mathrm{meas}}\bigr)
$$

where \( u_t^{\mathrm{meas}} \) is max container `q_cpu` / `q_ram` (or MS aggregate), so measurement pressure can override an optimistic RPS-derived util (**Up safety**).

### 4.2 Direction \( \Delta \)

With \( \theta^{\mathrm{up}} > \theta^{\mathrm{target}} > \theta^{\mathrm{down}} \):

- **Up** if \( u_t \ge \theta^{\mathrm{up}} \) **or** \( \max_{h \le H} \hat{u}_{t+h} \ge \theta^{\mathrm{up}} \)
- **Down** if \( u_t \le \theta^{\mathrm{down}} \) **and** \( \max_{h \le H} \hat{u}_{t+h} \le \theta^{\mathrm{down}} \)
- **None** otherwise

Horizon-cold scale-down avoids shrinking when a near-future rebound is predicted.

### 4.3 Sustained flag

When \( \Delta = \mathrm{Up} \) in proactive mode:

$$
\mathit{sustained}
=
\mathbf{1}\!\left[
  \bigl|\{ h \le H :\ \hat{u}_{t+h} \ge \theta^{\mathrm{up}} \}\bigr| \ge \tau
\right].
$$

Else \( \mathit{sustained} = \mathrm{False} \) from the forecast path.

**Defaults:** \( H = 3 \), \( \tau = 2 \). Used later to skip BEV → BEH on prolonged surge.

**Reactive mode:** build `sustained` from a streak of **observed pressure** (e.g. \( u_t \ge \theta^{\mathrm{up}} \) or drop pressure), **not** from emitted Up decisions (cooldown would freeze that streak incorrectly). Count pressure TTWs even while cooldown blocks emission.

### 4.4 Residuals — demand-based (safe for Down and \( A \to 0 \))

Do **not** size Down from current util alone while gating on the horizon (that can over-shrink relative to predicted near-future demand).

Define demand used for sizing:

- **Proactive:** \( r^{\star} = \max\bigl(r_t,\ \max_{h\le H}\hat{r}_{t+h}\bigr) \)
- **Reactive** (or forecast unavailable): \( r^{\star} = r_t \)

Required CPU alloc to hit target util under that demand:

$$
A_{\mathrm{req}}^{\mathrm{cpu}}
=
\frac{\rho^{\mathrm{cpu}}\, r^{\star}}{\theta^{\mathrm{target}}},
\qquad
\delta^{\mathrm{cpu}}
=
A_{\mathrm{req}}^{\mathrm{cpu}} - A_m^{\mathrm{cpu}}.
$$

Analogously for RAM with \( \rho^{\mathrm{ram}} \) when enabled.

Then:

- if \( \Delta = \mathrm{Up} \): use \( \delta \leftarrow \max(0, \delta) \) (and if \( A_m = 0 \), \( A_{\mathrm{req}} > 0 \) still yields a positive residual → horizontal spawn can recover);
- if \( \Delta = \mathrm{Down} \): use \( \delta \leftarrow \min(0, \delta) \);
- if \( \Delta = \mathrm{None} \): residuals unused.

This keeps direction (thresholds on util) and magnitude (demand → alloc) consistent with the horizon.

### 4.5 Confidence and proactive vs reactive

After TTW \( t \), once real \( r_t \) is known, compare to the **stashed one-step** forecast \( \hat{r}_{t \mid t-1} \) (real units, after inverse transform):

$$
e_t = \left| \frac{\hat{r}_{t \mid t-1} - r_t}{\max(|r_t|,\, r_{\mathrm{floor}})} \right|
$$

Use a **traffic floor** \( r_{\mathrm{floor}} \) (e.g. a small absolute RPS, or a percentile of training traffic) instead of a tiny \( \varepsilon \), so idle near-zero TTWs do not explode MAPE.

$$
\mathrm{MAPE}
=
\frac{1}{n}\sum e
\quad \text{over the last up to \( W_\kappa \) \emph{valid} pairs}.
$$

**Warm-up:** \( \kappa = 0 \) until `valid_error_count >= W_kappa` (not merely “absolute TTW index \( t \) large”). Missing stash / failed inference → skip the pair (do not count as valid).

- \( \kappa = 0 \) while warming up
- else \( \kappa = 1 / (1 + \mathrm{MAPE}) \)

If \( \kappa < \kappa_{\min} \): ignore \( \hat{\mathbf{r}} \) for \( \Delta \) (reactive), but still forecast when possible so confidence can recover.

**Note:** \( \kappa \) is driven by **one-step** error. Horizon steps \( h>1 \) can be worse; for v1 that is accepted with small \( H \), and multi-step error is an evaluation gate (§3.2). Optional later: \( \kappa \) from worst/weighted lead error.

**`kappa_min` interpretation:** e.g. `0.5` allows MAPE up to 1.0 (100% relative error) before forcing reactive — tune deliberately; do not treat 0.5 as “half accurate” in an informal sense without checking this formula.

### 4.6 Cooldown — suppress new scaling decisions, not sensing

After a **successful** scale act for \( m \), suppress new Up/Down for the next \( C \) TTWs.

**Preferred state:** `next_allowed_ttw[m]`.

If a successful allocate completes at the end of TTW \( t \):

$$
\texttt{next\_allowed\_ttw}[m] \leftarrow t + C + 1.
$$

So TTWs \( t+1, \ldots, t+C \) are silent for decisions; first eligible decision TTW is \( t+C+1 \).  
Examples: \( C=0 \) → next TTW allowed; \( C=1 \) → skip exactly one TTW; \( C=3 \) → skip three TTWs.

Equivalent counter form: after success set `cooldown[m] = C`; at each TTW start/end, if `cooldown > 0` then block decision and decrement **after** the gate (or decrement at TTW end but gate on value **before** decrement — pick one and test \( C \in \{0,1,3\} \) explicitly).

**Still always:** append real RPS; forecast; stash \( \hat{r}_{t+1} \); update confidence when a valid pair exists.

**Blocked during cooldown:** emitting \( \Delta \in \{\mathrm{Up},\mathrm{Down}\} \) / AllocateResources.

Arm cooldown **only on success**. All-reject → no cooldown (retry next eligible TTW).

\( C = H \) by default is a heuristic (same timescale as the justifying trajectory), not a theorem; provisioning delay may motivate a different \( C \) later.

```text
# per MS at end of each TTW t
append_real_rps(m, r_t)                    # always; from container lambda_in
r_hat = forecast_horizon(...) if warm else empty
stash y_hat_{t+1} = r_hat[1] if available  # BEFORE cooldown return
update_confidence from prior stash vs r_t  # if valid pair

if t < next_allowed_ttw[m]:
    return None                            # sensing+forecast only

(mode) = Proactive if kappa ok and |history|>=W else Reactive
(Delta, delta, sustained) = decide(...)
if Delta != None and allocate_succeeded(m):
    next_allowed_ttw[m] = t + C + 1
```

If AllocateResources can be async later, add `decision_pending[m]` so a second intent cannot queue while one is in flight; clear on settle; arm cooldown only on success.

---

## 5. Pre-trained LSTM: options and recommendation

### 5.1 Options

| Option | Idea | Pros | Cons |
| --- | --- | --- | --- |
| **O1.** Offline one-step LSTM + runtime load | `(W,1)` → next TTW-RPS | Matches recursive roll; simple κ | Need train pipeline + scaler |
| **O2.** Direct multi-horizon | one shot → \( H \) outputs | Less recursive error | Retrain if \( H \) changes |
| **O3.** Seq2seq encoder–decoder | encode / decode \( H \) | Better for long \( H \) | Overkill for \( H=3 \) |
| **O4.** Fine-tune TS foundation model | less cold-start | heavy / domain shift | |
| **O5.** Frozen unrelated pretrain | demo only | usually poor | |

### 5.2 Recommended: O1

Reasons unchanged: simple contract, \( H \) as policy knob, offline train / online infer, thesis-friendly.

**Artifacts:**

```text
models/<name>/
  model.pt
  scaler.json      # required with normalized training
  meta.json        # W, L used at train time, feature list, metrics, r_floor
```

**Interface:**

```text
class OneStepRpsPredictor:
    def predict_next(self, x: Vector[W]) -> float          # real RPS in/out at this API
    def forecast_horizon(self, x: Vector[W], H: int) -> Vector[H]
```

Normalization is encapsulated inside the predictor implementation.

**Stand-in:** last-value / linear extrapolation with the same interface until a checkpoint exists.

### 5.3 Not first path

O2/O3 only if recursive multi-step eval fails; O4/O5 not as frozen defaults.

---

## 6. Implementation plan (this aspect only)

### 6.1 Module layout

```text
autoscaler/proactive_hierarchical/
  rps_history.py
  ttw_rps.py          # accumulate lambda_in counts -> RPS; no TraceStore
  forecast.py
  predict_and_decide.py
  confidence.py
  cooldown.py
  predictors/
    base.py
    last_value.py
    lstm_torch.py
```

### 6.2 Per-TTW flow

```text
on end of TTW t for each m:
  1. N_t <- sum(lambda_in of m's containers over TTW_t)   # counts
     r_t <- N_t / (L * tick_sec)                          # RPS; NO trace
  2. history[m].append_real(r_t)
  3. update_confidence(prior_y_hat, r_t) if valid pair
  4. if len(history) >= W:
        r_hat <- forecast_horizon(copy(history), H)       # validated real RPS
        stash y_hat_{t+1} <- r_hat[1]
     else:
        r_hat <- empty; mode <- Reactive
  5. if t < next_allowed_ttw[m]:
        return None                                       # after stash
  6. mode <- Proactive if kappa ready and |history|>=W else Reactive
  7. (Delta, d_cpu, d_ram, sustained) <- decide(...)
  8. if Delta != None and allocate_succeeded(m):
        next_allowed_ttw[m] <- t + C + 1
```

Env ticks every \( \tau \); PredictAndDecide body runs when a TTW closes (\( \tau \bmod L = 0 \) with consistent indexing).

### 6.3 Build order

1. TTW RPS accumulator (multi-container; assert no trace imports).
2. History buffer (purity tests).
3. Recursive forecast + inverse/validation tests.
4. Cooldown with explicit tests for \( C \in \{0,1,3\} \) and allowed TTW indices.
5. `decide` / sustained / demand-based residuals (include Down + horizon peak; \( A=0 \) Up residual).
6. Confidence with `valid_error_count` and \( r_{\mathrm{floor}} \).
7. LSTM loader + scaler golden test.
8. Wire PredictAndDecide; BEV/BEH consume `sustained` later.

### 6.4 YAML params

```yaml
predictor:
  ttw_ticks: 1
  window_W: 30
  horizon_H: 3
  cooldown_C: 3
  sustained_tau: 2
  kappa_min: 0.5
  mape_window_W_kappa: 20
  rps_floor: 0.1          # MAPE denominator floor (req/s); tune to workload scale
  theta_up: 0.80
  theta_down: 0.30
  theta_target: 0.60
  model_path: models/rps_lstm_v1
```

---

## 7. Design locks (summary)

| Lock | Choice |
| --- | --- |
| Time base | **TTW** of \( L \) ticks |
| Forecast target | **TTW-average RPS** (not request-count, not replica count) |
| Online RPS source | Sum of container **`lambda_in` tick counts** / \( (L\cdot tick\_sec) \); **no traces** |
| `lambda_in` units | Request **count per tick** in HierarchicalEdgeSim |
| Scope v1 | **Per-MS** series + matching fleet capacity |
| History | Last \( W \) **real** RPS; never \( \hat{r} \) |
| Multi-step | Recursive one-step on scratch \( \mathbf{z} \) |
| Residuals | **Demand-based** \( A_{\mathrm{req}}=\rho r^\star/\theta^{target} \) |
| Cooldown | `next_allowed_ttw = t+C+1` after success; sensing continues |
| Stash order | Stash \( \hat{r}_{t+1} \) **before** cooldown early-return |
| LSTM | Offline one-step + scaler; infer real RPS at API boundary |
| Hybrid | Low \( \kappa \) → reactive decide; forecast may continue |

---

## 8. Open points

1. Env signal for demand when MS has **zero containers** (required for true recovery from empty fleet).
2. Shared LSTM across MS vs per-MS / per-class fine-tune (start shared + Option B scaler; revisit if MAPE stays poor).
3. Split \( C_{\mathrm{up}} \) vs \( C_{\mathrm{down}} \) later.
4. Whether to promote multi-step error into \( \kappa \) after first eval.
5. Async `decision_pending` if allocate ceases to be synchronous.

---

## 9. Review notes (GPT‑5.6)

External review agreed the core architecture (history purity, no online traces, recursive short horizon, cooldown ≠ freeze sensing) is sound, and flagged implementation hazards. Disposition:

| Review point | Disposition |
| --- | --- |
| `lambda_in` units ambiguity | **Applied** — locked as per-tick request count; RPS via \( /(L\cdot tick\_sec) \) |
| Scale-down sized only from \( u_t \) | **Applied** — demand-based \( r^\star \) / \( A_{\mathrm{req}} \) residuals |
| Zero allocation residual | **Applied** via demand-based formula; **note** zero-container telemetry gap |
| Pre-routing / no-replica demand invisible | **Noted** §2.2 + open point §8.1 (env work) |
| RAM dimensional purity | **Applied** — keep sim-linear RAM coeff; defer physical residency model |
| Per-MS vs per-\((m,c)\) scope | **Applied** — lock per-MS v1 |
| Cooldown off-by-one | **Applied** — `next_allowed_ttw = t+C+1` + test cases |
| Stash after cooldown return | **Applied** — stash before early return |
| One-step κ vs horizon error | **Noted**; eval gate; optional later |
| MAPE near zero / κ_min meaning | **Applied** — \( r_{\mathrm{floor}} \) + κ interpretation note |
| Confidence warm-up by absolute \( t \) | **Applied** — `valid_error_count` |
| Invalid model outputs | **Applied** — §3.4 |
| Reactive sustained from emissions | **Applied** — pressure-based streak |
| Async allocate double-fire | **Noted** for later (`decision_pending`) |
| \( L,W \) ranges vs locks | **Applied** — baseline scalars + tuning ranges |
| Within-TTW burst / \( C=H \) heuristic | **Noted** as limitations, not locks to overclaim |

Reviewer agent: [GPT-5.6 doc review](a8946e40-1af8-43fc-a723-9f0860bef199).
