# PredictAndDecide (Algorithm 3)

**Status:** done (control shape mapped; residual kept on serving headroom)  
**Paper:** `PredictAndDecide` in `proposed_method_complete.tex` (`alg:predict`)  
**Code:** `src/hierarchical_edge_sim/autoscaler/proactive_auto_scaler/decide.py`  
**Caller:** `proactive_auto_scaler/policy.py` (`scan_ms` inside ClusterManagerCycle)  
**Names:** [naming-refactor.md](./naming-refactor.md) — paper \(r^*\), \(\rho\), \(H\) are **not** the code identifiers below  
**Serving-model diagnosis:** [s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md)

Each decision window runs the listing of Algorithm 3 in **one process**, after a window close, when request-count history is already length \(W\). There are no CM threads, no predictor ensemble RPC, and no MAPE \(\kappa\) gate. Apply is still ClusterManagerCycle (Algorithm 2) then AllocateResources.

This is **not** `run_env_only.py`, and it is **not** `reactive_local`. Algorithm 3 only runs when `run_with_autoscaler.py` loads `proactive_auto_scaler` **and** history is full. Until then the same policy uses reactive streaks (cold start). That cold-start path is **not** inside `predict_and_decide`.

**Locked mapping:** keep the simulator formulas. Do not revert to \(\delta = A\tilde u/\theta - A\). Do not add MAPE/\(\kappa\)/LSTM ensemble as “mapping.” If the sim is more reasonable than the tex (especially \(\mu=0\) / serving model), keep the sim and say what the algorithm should absorb.

---

## When decide runs

Each tick, sensing adds incoming requests. When the tick closes a **window** (`ticks_per_window`; Alibaba and the 60-tick smoke use 1, so one tick = one paper window \(t\)):

1. Convert the window’s request count to `observed_rps`.
2. If history length \(< W\) (`feature_window`): **not** Algorithm 3. Reactive streaks → ladder.
3. If history is full: predictor emits `forecast_rps` (a short list of future rates). `predict_and_decide` returns \(\Delta\), residuals, `sustained`. ClusterManagerCycle allocates.

`run_meta.yaml` `autoscaler.decide` is `predict_and_decide` when this scaler ran. `autoscaler.cycle` is still `cluster_manager` (Algorithm 2). `autoscaler.name` is `proactive_auto_scaler`.

---

## Listing ↔ code

| Tex | Simulator |
|---|---|
| Window \(t\) | `window_index` after a window close |
| \(u_m=\max_j q_{m,j}\) | `u_obs` from demand vs serving capacity, then `max` with fleet \(q_{ms}\) (plain language below) |
| Ensemble \(\mathcal F_m\), \(\kappa_r\), paper \(r^*=\arg\max\kappa\) | One predictor after warmup. No MAPE, no LSTM pool |
| \(\hat u(t+1:t+H)\) from \(f_{r^*}\) | `forecast_rps` (request **rate**), then \(u=\texttt{rate}/\texttt{rps\_capacity}\) |
| Up if observed **or** any hat \(\ge\theta^{up}\) | `u_obs >= theta_up or max_u_hat >= theta_up` |
| Down only if observed **and** all hats \(\le\theta^{down}\) | same |
| else None | same |
| `sustained` if \(\ge\tau\) hot forecast steps | `sustained_steps` (still skips BEV → BEH) |
| Outputs \(\Delta\), \((\delta^{cpu},\delta^{ram})\), `sustained` | `Direction`, `delta_cpu`/`delta_ram`, `sustained` |
| \(\tilde u=\max(u,\max_h\hat u)\); \(\delta=A\tilde u/\theta_{\mathrm{target}}-A\) | `peak_rps`; \(A_{\mathrm{req}}=n\cdot\min+(\texttt{cpu\_per\_request}\cdot\texttt{peak\_rps}\cdot\texttt{tick\_sec})/\theta_{\mathrm{target}}\); \(\delta=A_{\mathrm{req}}-A\) |
| Down residual from **observed** \(u\) only | same `peak_rps` as Up, then clamp the sign |
| Reactive branch inside the algorithm (\(k_{\mathrm{sust}}\)) | Cold start is a **different** path (`x_up_streak`), not this function |

No fake RPCs, barriers, or request-path delay were added. The predictor stays a plug-in (persistence in tests; TCN-delta on Alibaba). That is the same mapping style as Algorithms 1 and 2: implement the listing in one process; do not invent a distributed protocol.

---

## What already matches

After a window close, proactive `scan_ms` calls `predict_and_decide`, then the same ClusterManagerCycle / AllocateResources path as reactive. That is the paper pipeline.

The listing and the code agree on the **gate**:

- **Up** if observed util **or** any horizon step is \(\ge\theta^{up}\)
- **Down** only if observed **and** the whole horizon are \(\le\theta^{down}\)
- otherwise **None**
- **`sustained`** if at least `sustained_steps` forecast steps sit at/above \(\theta^{up}\) (still skips BEV and goes to BEH)

The fight is what \(u\) and \(\delta\) are computed from, not the if/else shape.

---

## What we kept in the simulator (and why)

**Do not revert `decide.py` to the tex residual.** Using total alloc \(A\) as capacity is a bug against this env’s serving model:

\[
\mu = \min\bigl((A_{\mathrm{cpu}}-\min)/\texttt{cpu\_per\_request},\;(A_{\mathrm{ram}}-\min)/\texttt{ram\_per\_request}\bigr)
\]

Routing is CPU-headroom weighted: a replica at `cpu_min` gets share 0. Using total \(A\) in \(u\) and \(\delta\) treats idle min-replicas as spare capacity. After a trough, \(q\) looks idle and decide goes None/Down while \(\mu\approx 0\). The first Alibaba TCN run dropped **69%** of requests largely because decide / BEV-down / min-BEH disagreed with \(\mu\). After headroom residual + packed spawn + surplus-down, that fell to about **8%** (then lower with cooldown work).

Hottest-replica \(u\) is the wrong signal here. Load is fleet-routed; one hot replica is packing/routing, not “grow total alloc by \(A\cdot u/\theta\)”. Demand / `rps_capacity` is the quantity the residual already sizes against.

**Do not add MAPE \(\kappa\) / LSTM ensemble as “mapping.”** Cold-start-until-\(W\) stands in for “\(\kappa=0\) while \(t<W_\kappa\).” If \(\kappa\) is a thesis contribution later, it is a **new** piece, not a fix to decide.

**Down residual stays on `peak_rps`.** The tex Down uses observed \(u\) only, so it can shrink all the way to a deep valley even if the forecast is a bit higher (still in the Down band). Sizing from `peak_rps` shrinks less. Better under a lagging predictor.

### Adjacent (not Algorithm 3)

Leave these in AllocateResources / cooldown. Do not fold them into `decide.py` to “match the paper.”

- \(\alpha_{up}/\alpha_{down}\) clip so one tick does not jump to full \(A_{\mathrm{req}}\)
- success-gated / HPA-style down-only cooldown (tex `StartCooldown(m,c,H)` every window)
- packed spawn and surplus-down (they recovered the 69% drop, but they are ladder rules)

---

## What the algorithm should absorb

A later draft of Algorithm 3 should state the serving model, not treat it as an implementation detail:

1. \(u\) from demand vs **headroom** \(\sum_j(a_j-\min)\), not \(\max_j q_j\) and not total \(A\).
2. \(\delta\) from \(A_{\mathrm{req}}=n\cdot\min+(\gamma\cdot r_{\mathrm{peak}}\cdot\Delta t)/\theta_{\mathrm{target}}\) (both resources through per-request cost). Do **not** reuse paper \(\rho\) (help payload) or paper \(r^*\) (predictor index).
3. Same \(r_{\mathrm{peak}}\) (or \(\tilde u\)) for Up **and** Down residuals.
4. Predictor may emit load or util; they match once capacity is headroom-based.
5. Ensemble/\(\kappa\): optional / related work. Operational rule: warmup, then one model.

Honest thesis line: **the algorithms specified floors but not a serving model.** Once \(\mu=(A-\min)/\gamma\) and headroom routing are the physics, treating \(A\) as capacity is a bug. The simulator made decide operational; that belongs in a later draft of Algorithm 3, not as an implementation footnote.

---

## Discussion (questions asked while mapping)

This section is the Algorithm 3 thread, not the naming refactor. Letter collisions live in [naming-refactor.md](./naming-refactor.md).

### Differences: change the simulator, or the algorithm?

**Keep the simulator.** The control *shape* is already mapped in `predict_and_decide`. Do not put the tex residual back. The tex should absorb the serving model.

Paper \(r^*\) is still the **predictor index**. Code `peak_rps` is peak load, the analogue of paper \(\tilde u\). Paper \(\rho\) in AllocateResources is the help payload. Code `cpu_per_request` is YAML `cpu_per_request_cores`. Paper \(H\) is the forecast horizon; code `headroom_*` is \(\sum(A-\min)\).

### Are we using different names than the paper?

Yes, and some letters meant two objects. That confusion was fixed in code (`peak_rps`, `cpu_per_request`, `ticks_per_window`, …) **without** changing formulas. The dedicated note is [naming-refactor.md](./naming-refactor.md). This mapping doc uses only the **current** names.

### “Demand vs serving capacity, then max with fleet `q_ms`”

The paper’s utilization is: look at each replica’s \(q\), take the **hottest** one.

The simulator asks: **how hard is the whole microservice working relative to how many requests it can actually finish?**

- **Demand** = incoming request rate (`observed_rps`). How many requests per second are arriving.
- **Serving capacity** = how many requests per second the current **headroom** can handle (`rps_capacity`). Headroom is allocation above the floor. The floor buys no throughput, so a replica sitting at `cpu_min` contributes 0.
- Divide: `observed_rps / rps_capacity`. That is utilization from load vs real capacity. If capacity is almost 0 and requests are still coming, this looks **full** (scale up).

Then it also looks at **fleet `q_ms`**: used work / headroom across all live replicas of that microservice (not “hottest replica”).

`u_obs` is the **larger** of those two. Either “the request rate says we are overloaded” or “the fleet already looks busy” is enough to count as high utilization.

So that table cell means: **utilization from (arrivals ÷ real serving capacity), combined with the fleet-wide busy fraction, not the single hottest replica.**

### Residual (the simulator cell)

The paper says: take **all** allocated CPU \(A\), pretend that whole pile is serving capacity, and ask “how much extra \(A\) would bring utilization down to \(\theta_{\mathrm{target}}\)?” That is \(\delta = A\cdot\tilde u/\theta_{\mathrm{target}}-A\).

The simulator sizes **how much allocation you actually need to serve the load**:

1. Keep the floors: `n * cpu_min` (those cores do not serve).
2. Add the cores that **do** serve: enough headroom so that `peak_rps` runs at about \(\theta_{\mathrm{target}}\), using `cpu_per_request` (cores per request). Same idea for RAM.
3. That sum is `A_req`. Residual is `A_req - A`.

If you already have more than `A_req`, residual is negative (down). If you have less, it is positive (up). Then the sign is clamped so Up cannot shrink and Down cannot grow.

**`peak_rps`** is the highest of “what we see now” and “what the forecast says in the next few steps.” It is **not** paper \(r^*\) (which model won).

### Predictor I/O, and what `r` was in \(r/\texttt{rps\_capacity}\)

**I/O** = what goes in and out of the predictor.

- Paper: the model outputs **utilization** \(\hat u\) (a fraction 0–1).
- Simulator: the model outputs **request rate** (`forecast_rps`, requests per second). The Alibaba TCN was trained on request counts.

To use the same Up/Down thresholds (\(\theta^{up}\), \(\theta^{down}\)), the simulator converts rate → utilization:

\[
u = r / \texttt{rps\_capacity}
\]

Here **`r` is just a request rate** (RPS): either `observed_rps` or one forecast step. It is not leftover residual \(r^{cpu}\) and not paper \(r^*\).

`rps_capacity` is “RPS we could take if headroom were 100% busy.” Divide rate by that and you get a number you can compare to 0.80 / 0.30 like the paper.

### What a “trough” is

A **trough** is a **quiet stretch after a spike** — the valley in the load curve.

Example: traffic is huge at noon, then it falls. Extra replicas from the spike may sit at the **floor** (they add to total \(A\) but serve nothing). If you treat total \(A\) as capacity, utilization looks **idle** in that valley, so the paper formula is happy to Down/None. Real serving capacity may already be ~0, so the next small wave of requests all drop. That is what went wrong on the first Alibaba TCN run. Headroom-based \(u\) and residual treat that valley as **full**, not idle.

---

## How to check a run

Use `run_with_autoscaler.py` and a **proactive** config. `demo_60_reactive_local` is Algorithm 2 only (streaks, no `predict_and_decide`). Partition env-only demos never call decide.

| File | What to look at |
|---|---|
| `run_meta.yaml` | **Algorithm 3 check.** `autoscaler.decide: predict_and_decide`, `name: proactive_auto_scaler`, `cycle: cluster_manager`. Params use `ticks_per_window`, `forecast_horizon`, `sustained_steps` (not `ttw_ticks` / `horizon_H` / `sustained_tau`) |
| `actions.csv` | After history fills (\(W=10\) on the 60-tick smoke), ladder reasons (`bev_up`, `beh_spawn`, …) from decide, not only cold-start streaks |
| `*.log.csv` | Conservation: incoming = served + dropped |

A run is **not** a failure because:

- The first \(W\) ticks are reactive (no hats yet)
- `need_vicinity_help` on a one-cluster world (no root) after home is full
- Persistence is a last-sample copy, not TCN; Alibaba TCN needs torch
- Drops remain on peaked traces

Dump:

```bash
DIR=results/proactive_60/<run_id>
python3 -c "
import csv, yaml
from collections import Counter
from pathlib import Path
p = Path('$DIR')
m = yaml.safe_load((p/'run_meta.yaml').read_text())
a = m.get('autoscaler') or {}
print('name  ', a.get('name'))
print('cycle ', a.get('cycle'))
print('decide', a.get('decide'))
print('predictor', (a.get('params') or {}).get('predictor'))
rows = list(csv.DictReader((p/'actions.csv').open()))
print('actions', len(rows))
print(Counter((r['action_type'], r.get('reason','')) for r in rows))
"
```

---

## Demos and sample results

```bash
python3 -m pytest tests/test_proactive_decide.py tests/test_proactive_auto_scaler.py -q

PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_60_proactive.yaml
```

Alibaba TCN (`configs/demo_alibaba_proactive.yaml`) is the same decide function with a different predictor. Needs torch. Recorded drop numbers: [alibaba-tcn-s7-results.md](./alibaba-tcn-s7-results.md).

Do **not** use `demo_partition.yaml` or `demo_60_reactive_local.yaml` to prove Algorithm 3.

Run ids are `{seed}_{UTC}`.

### `demo_60_proactive.yaml` — persistence smoke

Same world as `demo_60_reactive_local`. `ticks_per_window: 1`, `feature_window: 10`, `forecast_horizon: 3`, `predictor: persistence`.

Sample after this mapping pass: `results/proactive_60/42_20260827T185431Z`. Actions/logs matched the post-rename baseline `42_20260827T165040Z` (itself identical to pre-rename `42_20260827T062449Z`). `run_meta.yaml` now also has `decide: predict_and_decide`.

```yaml
autoscaler:
  enabled: true
  name: proactive_auto_scaler
  cycle: cluster_manager
  decide: predict_and_decide
  params:
    ticks_per_window: 1
    feature_window: 10
    forecast_horizon: 3
    sustained_steps: 2
    predictor: persistence
```

`actions.csv`: 2× `bev_up`, 13× `beh_spawn`, 8× `beh_terminate`, 2× `need_vicinity_help` (plus seed). All local on **c1**. Packed spawn sizes sit above `cpu_min` (e.g. 0.79, not 0.50). Two help log lines after the home cluster filled (no `World.root`). No `vicinity_spawn` / `beg_spawn`. Incoming 8228, served 7899.8, dropped 328.2. Conservation held.

Compared with `demo_60_reactive_local` on the same trace: more local spawns, fewer drops. That is decide + the shared ladder, not a second cycle.

Alibaba TCN was not re-run on this pass (no torch in the mapping environment). That demo is the other predictor behind the same `predict_and_decide`.

---

## Tests

```bash
python3 -m pytest tests/test_proactive_decide.py tests/test_proactive_auto_scaler.py -q
```

`test_proactive_decide.py` is pure: Up from observed rate, Up from a horizon spike, Down when observed and hats are cold, None in band, `sustained`, residual includes deployment floors, zero headroom + load is Up. `test_yaml_loads_proactive` checks `decide: predict_and_decide` and that `run_meta` would dump it.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-27 | Algorithm 3 mapped; headroom residual kept; discussion + plain-language Q&A; 60-tick sample |
