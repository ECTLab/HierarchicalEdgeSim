# AllocateResources (Algorithm 4)

**Status:** done (escalator mapped; cooldown and step caps kept outside the listing)  
**Paper:** `AllocateResources` in `proposed_method_complete.tex` (`alg:allocate`)  
**Code:** `src/hierarchical_edge_sim/autoscaler/reactive_local/allocate.py` (`ladder_up`, `ladder_down`)  
**Callers:** `reactive_local/policy.py`, `proactive_auto_scaler/policy.py` (both from ClusterManagerCycle)  
**Leftover \(\rho\):** `HelpRequest` in `reactive_local/help.py`  
**Decide residual:** [24-predict-and-decide.md](./24-predict-and-decide.md)  
**Step-size knobs:** [08-reactive-local-params.md](./08-reactive-local-params.md)

The listing is the **local escalator**: BEV, then BEH if leftover remains, leftover \(\rho\) on Up only, clamp on Down so shrink never leaves home. Each window runs that in **one process**. There are no CM threads and no `StartCooldown` RPC.

This is **not** `run_env_only.py`, and it is **not** `reactive_vertical` (BEV only). Algorithm 4 runs when `run_with_autoscaler.py` loads `reactive_local` or `proactive_auto_scaler`. Vicinity and BEG are **not** this listing: the tex returns \(\rho\) and stops; Algorithm 2’s `resolve_help` consumes that leftover.

**Locked mapping:** keep the simulator. Do not put `StartCooldown(H)` at the end of every allocate. Do not apply the full residual in one tick. Do not vertical-shrink **keepers** in the same tick as a terminate. Packed spawn, \(\mu\)-matched BEV, and cascade are **later listings** (BEV / BEH / CheckCascadingMigration); do not fold them into this file to “match Algorithm 4.”

---

## When allocate runs

ClusterManagerCycle already grouped intents by owner cluster. For each \(\Delta\neq\) None:

1. Clip the residual to **one step** (`up_delta` / `_clip_step`: \(\alpha\) and \(\delta_{\min}\)). That clip is **not** in the tex listing.
2. `ladder_up` or `ladder_down` (this algorithm).
3. Up leftover becomes `HelpRequest` (\(\rho\)). Down leftover is dropped.
4. After **all** clusters finish local allocate, Algorithm 2 runs vicinity then BEG.
5. After apply: cooldown **only if something succeeded** (not inside `allocate.py`).

`run_meta.yaml` `autoscaler.allocate` is `allocate_resources` when this path ran. `cycle` is still `cluster_manager`. Proactive also has `decide: predict_and_decide`. `reactive_vertical` has **no** `allocate` field.

The Python module `allocate.py` also contains `resolve_help`. That is packaging: leftover is built here, so help scheduling sits next to it. The **listing** still ends at \(\rho\).

---

## Listing ↔ code

| Tex | Simulator |
|---|---|
| Input \(m,c,\Delta,(\delta^{cpu},\delta^{ram}),\mathit{sustained}\) | `CycleIntent` (`ms_id`, owner `cluster_id`, `kind`, `need_*`, `sustained`) |
| \(r\gets\delta\); \(\rho\gets\emptyset\) | leftover starts empty |
| \(r\gets\textsc{BEV}(\ldots,\mathit{sustained})\) | `distribute_up` unless `sustained`; Down: peel the extra we would reclaim, else last replica toward \(\mu_{\mathrm{tgt}}\) |
| If leftover: \(\textsc{BEH}\) | `beh_up` / `beh_down` |
| Down: \(r\gets(0,0)\) (never escalate) | `ladder_down` returns actions only (`leftover=None`) |
| Up leftover \(\to\rho=(c,m,r,\min,\hat u,t_{det})\) | `HelpRequest`: home, leftover CPU/RAM, floors, packed-spawn mins, \(t_{det}\). **No hats** |
| \(\textsc{StartCooldown}(m,c,H)\) | **Not here.** `on_actions_applied` after a successful mutation |
| Return \((r,\rho)\) | `(actions, leftover)` |

No fake RPCs, barriers, or plan timeouts were added. Apply is still `Env.apply_actions` after the hook.

---

## What already matches

Up: BEV (unless `sustained`) → BEH → leftover \(\rho\) for the leader. Down: local BEV/BEH only, then clamp; **never** vicinity/BEG. That is the tex’s “down cannot leave the home cluster.”

Reusable blocks (C5): both scalers call the same `ladder_up` / `ladder_down`.

Sustained Up skips BEV and goes to BEH — that flag is computed in decide / streaks, then honored here, matching the BEV listing’s first line.

---

## What we kept in the simulator (and why)

**Do not put `StartCooldown(m,c,H)` at the end of AllocateResources.** The tex starts cooldown even if every mutation was Reject, and even on Down. Length is the forecast horizon \(H\).

The sim starts cooldown in `on_actions_applied`, **only if something actually applied**. Reactive uses `cooldown_ticks` on any success. Proactive is HPA-style: Up is not delayed; Down waits `cooldown_C` windows after an Up.

A full-reject window that still starts cooldown would freeze a saturated MS until \(H\) elapses with no extra capacity. That is worse than the code.

**Apply the full residual in one window.** The tex hands \(\delta\) straight to VerticalScaling. The sim no longer clips with \(\alpha_{up}/\alpha_{down}\). Streaks, cooldown, last-replica, and `safe_j` still decide *when* and *where* that residual lands. \(\delta_{\min}\) is a dust/token floor, not a speed limit.

**Do not vertical-shrink keepers in the same tick as a terminate.** The tex always runs BEV on everyone, then BEH if leftover remains. The sim: while extras exist, VerticalScaling peels **only** the extra we would reclaim (floor is `cpu_min`, not fleet \(\mu_{\mathrm{tgt}}\)); terminate it on a later tick once it is at the floor or remaining \(\mu\) still covers \(\mu_{\mathrm{tgt}}\). Shrink+kill on the copies you mean to keep left \(\mu\) too small and bounced Up.

**Keep \(\rho\) without forecast hats.** Tex \(\rho\) carries \(\hat u(t{+}1{:}t{+}H)\) for lender `Reserve`. Mapping the escalator does not require stuffing hats into `HelpRequest`; `Reserve`/`safe_j` is computed from leftover \(\rho\) after local allocate.

### Adjacent (not Algorithm 4)

Leave these in BEV / BEH / cascade / Algorithm 2. Do not fold them into `ladder_up` to “match this listing.”

- Packed spawn above minima; skip a worker that can only fit the floor (BEH)
- \(\mu\)-matched CPU/RAM packing; refuse \(\mu=0\) resize (BEV)
- Surplus-down / never kill the last replica (BEH)
- `CheckCascadingMigration` after local free (tex puts this at the end of BEH)
- VicinityLeaderSchedule / BEG (`resolve_help`)
- Algorithm 3’s serving-headroom residual (already mapped)

---

## What the algorithm should absorb

A later draft of Algorithm 4 should state the **cooldown**, not treat it as an implementation detail:

1. **Cooldown after a successful apply only.** Do not `StartCooldown` on a full-reject window. Length is a policy knob (`cooldown_ticks` / `cooldown_C`), not necessarily the forecast horizon \(H\). Proactive may delay **Down after Up** and never delay Up (Kubernetes HPA: scaleUp window 0, scaleDown 300s).
2. **The window residual is the action.** Do not re-introduce \(\alpha_{up}/\alpha_{down}\) as a fraction of current alloc. \(\delta_{\min}\) stays as a dust/token floor so a tiny fleet still moves.
3. **Down with extra replicas:** vertical-down the extra you would reclaim, then terminate it; do not shrink keepers in the same tick as a terminate. Last replica: surplus peel toward \(\mu_{\mathrm{tgt}}\). (Last-replica / surplus-\(\mu\) stopping conditions still belong in BEV/BEH.)
4. **\(\rho\) without hats.** Keep \((c,m,r^{cpu},r^{ram},\min,t_{det})\). Forecast vectors are for `safe_j`, which is leftover own \(\rho\) after local allocate.
5. **Down clamp stays.** Unchanged and correct: leftover after local shrink is discarded; Down never builds \(\rho\).

Honest thesis line: **the listing specified the rung order but not a success-gated cooldown.** Once apply can Reject, starting cooldown on a no-op window is a bug. The simulator made the escalator operational; that belongs in a later draft of Algorithm 4.

Do **not** claim packed spawn or \(\mu\)-matched BEV as part of this mapping. Those are Algorithms 5–6.

---

## Discussion (questions asked while mapping)

### Is there any difference between the algorithm and the code?

**The control shape matches.** Differences on *this* listing are cooldown, peel-the-extra-before-terminate (never shrink keepers in the same tick as a kill), and a thinner \(\rho\). Packed spawn and related physics live in BEV/BEH, not here. The window residual is no longer \(\alpha\)-clipped.

`allocate.py` also running `resolve_help` is not Algorithm 4 growing a fourth local tier. Algorithm 2 still owns vicinity/BEG.

### What happened to \(\alpha_{up}/\alpha_{down}\)?

They were a sim-only speed limit (a fraction of current alloc per tick). They are gone. AllocateResources applies the window residual; streaks, cooldown, last-replica, and `safe_j` are the remaining brakes.

`min_mu_step` (`25` req/tick) is the one serving-μ dust floor: if we decided to move, move at least this much. RAM follows `Δμ × ρ`. Floor extras terminate because they add no μ; HorizontalScaling does not need a fake leftover token.

---

## How to check a run

Use `run_with_autoscaler.py` and `reactive_local` or `proactive_auto_scaler`. `20-demo_partition.yaml` never calls allocate. `reactive_vertical` is BEV-only (no BEH, no \(\rho\)).

| File | What to look at |
|---|---|
| `run_meta.yaml` | **Algorithm 4 check.** `autoscaler.allocate: allocate_resources` and `cycle: cluster_manager`. Proactive also has `decide: predict_and_decide`. `reactive_vertical` must **not** list `allocate` |
| `actions.csv` | Local rungs: `bev_up` / `beh_spawn` (or Down `bev_down` / `beh_terminate`). Leftover Up on a multi-cluster world becomes `vicinity_spawn` / `beg_spawn` **after** this listing, in Algorithm 2 |
| Down | No `vicinity_spawn` / `beg_spawn` from a shrink. That would mean Down built \(\rho\) |

A run is **not** a failure because:

- `need_vicinity_help` on a one-cluster world after home is full (no `World.root`)
- BEH spawn lands on a worker that **already hosts** the MS (prefer-hosting)
- Packed spawn sizes sit above `cpu_min` (BEH, not this listing)
- Drops remain on peaked traces

Dump:

```bash
DIR=results/08-ladder-60tick/reactive_local/<run_id>
python3 -c "
import csv, yaml
from collections import Counter
from pathlib import Path
p = Path('$DIR')
m = yaml.safe_load((p/'run_meta.yaml').read_text())
a = m.get('autoscaler') or {}
print('name    ', a.get('name'))
print('cycle   ', a.get('cycle'))
print('decide  ', a.get('decide'))
print('allocate', a.get('allocate'))
rows = list(csv.DictReader((p/'actions.csv').open()))
print('actions', len(rows))
print(Counter((r['action_type'], r.get('reason','')) for r in rows))
"
```

---

## Demos and sample results

```bash
python3 -m pytest tests/test_reactive_local.py tests/test_proactive_auto_scaler.py tests/test_cm_cycle.py -q

PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/08-demo_60_reactive_local.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/09-demo_60_vicinity_help.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/11-demo_60_proactive.yaml
```

Do **not** use `20-demo_partition.yaml` to prove Algorithm 4. Triangle 400-tick configs use this listing but were built to isolate BEV/BEH/vicinity/BEG rungs, not to prove the escalator text.

Run ids are `{seed}_{UTC}`. Folders below are from a 2026-08-27 mapping-pass check; actions/logs matched the Algorithm 2 samples bit-for-bit. `run_meta.yaml` now also has `allocate: allocate_resources`.

| Config | What Algorithm 4 should do |
|---|---|
| `demo_60_reactive_local` | Local Up: BEV then in-cluster BEH; leftover \(\rho\) logged (`need_vicinity_help` if home fills; no root) |
| `demo_60_vicinity_help` | Same local rungs; leftover \(\rho\) is real → Algorithm 2 vicinity spawn on `c2` |
| `demo_60_global_help` | Local + vicinity packed → leftover \(\rho\) → BEG on `c3` |
| `demo_60_proactive` | Same `ladder_up`/`ladder_down`; residual comes from Algorithm 3 |

### `08-demo_60_reactive_local.yaml` — local BEV then BEH

Sample: `results/08-ladder-60tick/reactive_local/42_20260827T194609Z`

```yaml
autoscaler:
  enabled: true
  name: reactive_local
  cycle: cluster_manager
  allocate: allocate_resources
```

`actions.csv`: 7× `bev_up`, 1× `beh_spawn` (plus seed). No `vicinity_spawn` / `beg_spawn`. The BEH replica landed on **c1-w1** (already hosting). Incoming 8228, served 6841.4, dropped 1386.6. Conservation held. Actions matched the Algorithm 2 sample `42_20260827T062448Z`.

### `09-demo_60_vicinity_help.yaml` — leftover \(\rho\) leaves home

Sample: `results/08-ladder-60tick/vicinity_help/42_20260827T194610Z`

Local allocate still BEV/BEH at **c1**. Unmet Up residual is \(\rho\); Algorithm 2 places 5× `vicinity_spawn` on **c2**. That spawn is **not** a fourth rung of Algorithm 4. Actions matched `42_20260827T062448Z`.

### `11-demo_60_proactive.yaml` — same listing, Algorithm 3 residual

Sample: `results/08-ladder-60tick/proactive/42_20260827T194610Z`

```yaml
autoscaler:
  name: proactive_auto_scaler
  cycle: cluster_manager
  decide: predict_and_decide
  allocate: allocate_resources
```

Same `ladder_up` / `ladder_down`. 2× `bev_up`, 13× `beh_spawn`, 8× `beh_terminate`. More local spawns than reactive_local on the same trace because decide’s residual differs, not because there is a second escalator. Actions matched `42_20260827T062449Z`.

---

## Tests

```bash
python3 -m pytest tests/test_reactive_local.py tests/test_proactive_auto_scaler.py tests/test_cm_cycle.py -q
```

`test_yaml_loads_reactive_local` / `test_yaml_loads_proactive` check `allocate: allocate_resources` and that `run_meta` would dump it. `test_cm_cycle.py` still checks that leftover \(\rho\) is merged FCFS after local allocate.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-27 | Algorithm 4 mapped; cooldown and α/δ kept outside the listing; discussion + what the tex should absorb |
