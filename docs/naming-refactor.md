# Simulator naming refactor (paper-letter collisions)

**Status:** done (code + YAML aliases + tests)  
**What this is:** why decide/sensing identifiers were renamed, and which leftovers are on purpose.  
**What this is not:** Algorithm 3 mapping, serving-model changes, or a thesis comparison. Formulas did not change. Pipeline: [s7-proactive-front-end.md](./s7-proactive-front-end.md). Paper vs code: [thesis-vs-simulator.md](./thesis-vs-simulator.md).

The confusion was not “the simulator uses English and the paper uses Greek.” It was **the same letter meaning two different objects**, plus a few simulator-only names (TTW, \(C_{\mathrm{full}}\), RPS) that the paper never defines.

---

## Where the confusion came from

Algorithm 3 (`PredictAndDecide`) and its neighbors already overload short letters. The simulator then reused some of those letters for **environment** quantities.

Three examples that showed up when reading the listing next to `decide.py`:

| Letter / name | In the paper | In the simulator (before the rename) |
|---|---|---|
| \(r^*\) | winning **predictor index** (\(r^*=\arg\max_r\kappa_r\)) | `r_star` = peak **request rate** used to size \(A_{\mathrm{req}}\) |
| \(\rho\) | (1) vicinity/global **help payload** after AllocateResources; (2) Algorithm 1 **leader score** | `rho_cpu` / `rho_ram` = **cores or MB to serve one request** |
| TTW, \(C_{\mathrm{full}}\), RPS | not in the paper | sensing/clock adapters: ticks batched into a window; RPS that fills headroom |

Paper \(r^*\) is “which model won.” Code `r_star` was “the rate we size to.” That second quantity is the paper’s \(\tilde u\) (peak observed-or-forecast util), just in RPS units.

Paper \(\rho\) in Algorithm 2/AllocateResources is the leftover help tuple. The env usage model needed a per-request cost; old design notes already called that \(\rho\). When decide was rewritten around serving headroom, that cost appeared in \(A_{\mathrm{req}}\) under the same letter.

TTW / \(C_{\mathrm{full}}\) / RPS exist because the paper starts from utilization \(q\), while this env is tick-based and traces are request counts. Sensing converts counts → RPS; decide converts RPS → util. The paper has no word for that bridge. **RPS** (“requests per second”) is ordinary English and stayed. **TTW** explained nothing and went away.

---

## Same letter, different object (the dangerous set)

These are not aliases. They are different quantities that reused a short name.

| Letter | Paper | Simulator (current code) |
|---|---|---|
| \(r^*\) | winning predictor index | `peak_rps` (was `r_star`) |
| \(\rho\) | help payload, or leader-election score | `cpu_per_request` / `ram_per_request` in decide (YAML: `cpu_per_request_cores`) |
| \(H\) | forecast **horizon** (also `StartCooldown(H)`) | `headroom_cpu` / `headroom_ram` = \(\sum(A-\min)\); horizon is `forecast_horizon` |
| \(r^{cpu}\) | leftover **residual** after BEV/BEH | `observed_rps` / `forecast_rps` = **request rate** |
| \(u\) | node used-CPU vector **and** MS util \(\max q\) | `u_obs` = MS utilization only |
| \(\tau\) | `sustained` threshold (how many hot forecast steps) | `tau` = simulation **tick**; the threshold is `sustained_steps` |
| \(\mu\) | mean of distances in Algorithm 1 | serving capacity (requests a replica can finish this tick) |

---

## Same idea, different name (harmless once you have a glossary)

| Paper | Simulator now | Why the sim name exists |
|---|---|---|
| window \(t\) | `window_index` after a close of `ticks_per_window` ticks | Discrete engine can tick faster than one predictor sample. Alibaba uses `ticks_per_window=1`, so one tick = one paper window. |
| \(\hat u(t+1:t+H)\) | `forecast_rps`, then \(u = r / \texttt{rps\_capacity}\) | TCN is trained on Alibaba **counts**, not on \(q\). |
| \(\tilde u = \max(u,\max_h\hat u)\) | `peak_rps = max(observed_rps, hats)` | Same “size to the peak” idea; wrong letter before (`r*`). |
| horizon \(H\) | `forecast_horizon` | Dropped `_H` so it does not look like headroom. |
| persistence \(\tau\) | `sustained_steps` | Sim `tau` is already the tick. |
| \(\theta^{up},\theta^{down},\theta^{target}\) | `theta_up`, `theta_down`, `theta_target` | Unchanged. |
| \(\Delta\) | `Direction` | Unchanged. |
| \((\delta^{cpu},\delta^{ram})\) | `delta_cpu`, `delta_ram` | Unchanged (formula still uses headroom, not \(A\tilde u/\theta-A\)). |
| \(A_m\) | `A_cpu`, `A_ram` | Unchanged. |
| \(k_{sust}\) | `x_up_streak` on the cold-start path | Different module, same idea. |
| \(W_\kappa\) | `feature_window` | Warmup until history is long enough; no MAPE. |

Names that **only exist in the simulator** (not missing paper features):

| Name | Meaning |
|---|---|
| `observed_rps` | \(N / (L \cdot \texttt{tick\_sec})\) over a closed window |
| `ticks_per_window` (\(L\)) | how many sim ticks make one paper window \(t\) |
| `tick_sec` | wall seconds per discrete tick |
| `rps_capacity_*` | RPS that would drive headroom to 100%: \((\mathrm{headroom}/\mathrm{cpu\_per\_request})/\texttt{tick\_sec}\) |
| `lambda_in` / \(\Lambda\) | offered requests this tick |

---

## What was renamed

Scope: proactive **decide + sensing + YAML**, plus `CycleIntent.window_index`. Not a repo-wide synonym hunt.

| Before | After |
|---|---|
| `r_t` | `observed_rps` |
| `r_hat` | `forecast_rps` |
| `r_star` | `peak_rps` |
| `rho_cpu` / `rho_ram` in `decide.py` | `cpu_per_request` / `ram_per_request` |
| `H_cpu` / `H_ram` | `headroom_cpu` / `headroom_ram` |
| `c_full_*` | `rps_capacity_*` |
| `ttw_ticks` | `ticks_per_window` |
| `ttw_t` | `window_index` |
| `is_ttw_close` / `ttw_index` | `is_window_close` / `window_index` |
| `horizon_H` | `forecast_horizon` |
| `sustained_tau` | `sustained_steps` |
| `ttw_rps.py` | `window_rps.py` |
| `_next_down_ttw` | `_next_down_window` |

Canonical per-request cost in the **world spec** was already `cpu_per_request_cores` / `ram_per_request_mb`. Decide now uses that name instead of inventing `cost_per_request_cpu` as a third synonym.

`RPS` stayed. `cooldown_C` stayed (HPA-ish, not an Algorithm 3 collision). Sim tick `tau` stayed (used everywhere; paper window is \(t\)).

### YAML aliases

`validate_params` still accepts the old keys so older configs do not break:

- `ticks_per_window` or `ttw_ticks`
- `forecast_horizon` or `horizon_H`
- `sustained_steps` or `sustained_tau`

If both the new and old key are present, the **new** key wins. Current demos (`demo_60_proactive`, `demo_alibaba_proactive`, `demo_alibaba_ms150_proactive`) use the new keys. `run_meta.yaml` dumps the dataclass field names (`forecast_horizon`, not `horizon_H`).

---

## What was left alone (on purpose)

Renaming every local `rho_cpu` in the ladder, or every \(\rho\) in historical notes, would not make Algorithm 3 easier to read. Those are **physics** or **paper** names.

| Left as-is | Why |
|---|---|
| `spec.cpu_per_request_cores` | Already explicit. |
| Locals `rho_cpu = spec.cpu_per_request_cores` in `beh.py`, `allocate.py`, `distribute.py`, `mu_scale.py` | Same object; not the help payload. Touch when those files are rewritten. |
| `examples/analysis/aggregate.py` `MsPhysics.rho_cpu` | Plot physics, not decide. |
| Env `mu` in `usage.py` | Serving capacity. Algorithm 1’s \(\mu\) is mean distance; a comment is enough. |
| Obs `sum_h_cpu` / `sum_h_ram` | Fleet headroom aggregate fed into `headroom_cpu`. |
| TCN `meta.json` key `"horizon"` | Model artifact from training, not a Python identifier. |
| Paper leftover \(\rho\) in ClusterManagerCycle docs | That **is** the help payload. |
| Docs that talk about \(\mu=(A-\min)/\rho\) | Env serving model; \(\rho\) there means per-request cost, not the help tuple. |
| `docs/custom-simulator-environment.md` Option A \(\rho\) | Historical design note. |
| `docs/proactive-autoscaler-approach.md` (`predict.py`, …) | Pre-implementation plan; not the current tree. |

---

## How to read a formula without mixing them

Paper (Algorithm 3) - **Algorithm 3 talks *utilization*. The env talks *requests***. Decide is the adapter: RPS in, Δ and 𝛿 out:

\[
\delta = A\,\tilde u / \theta_{\mathrm{target}} - A
\quad\text{after choosing predictor } r^*
\]

Simulator (same *role*, different *units*):

\[
u = r / \texttt{rps\_capacity},\quad
A_{\mathrm{req}} = n\cdot\min + (\texttt{cpu\_per\_request} \cdot \texttt{peak\_rps} \cdot \Delta t) / \theta_{\mathrm{target}}
\]

`peak_rps` is not paper \(r^*\). `cpu_per_request` is not paper \(\rho\) (help payload). `headroom_*` is not paper horizon \(H\).

If a later tex draft wants matching letters: keep \(r^*\) for the ensemble index; call peak load \(r_{\mathrm{peak}}\) or \(\tilde\lambda\); call per-request cost \(\gamma\) or \(\rho^{\mathrm{req}}\); call serving headroom \(H^{\mathrm{serve}}\). The simulator does not need another rename for that.

---

## Code map

| Piece | Path |
|---|---|
| Decide | `src/hierarchical_edge_sim/autoscaler/proactive_auto_scaler/decide.py` |
| Sensing + window close | `.../sensing.py`, `.../window_rps.py` |
| YAML | `.../params.py` (`_pop_alias`) |
| Cycle field | `autoscaler/common/cm_cycle.py` `CycleIntent.window_index` |
| Demos | `configs/demo_60_proactive.yaml`, `configs/demo_alibaba_proactive.yaml`, `configs/demo_alibaba_ms150_proactive.yaml` |
