# Cluster manager cycle (Algorithm 2)

**Status:** done (2026-09-16: leftover after VicinityRound is `unmet_demand`, not BEG)  
**Paper:** `ClusterManagerCycle` in `proposed_method_complete.tex` (`alg:cmcycle`)  
**Code:** `src/hierarchical_edge_sim/autoscaler/common/cm_cycle.py`  
**Callers:** `reactive_local/policy.py`, `proactive_auto_scaler/policy.py` (both pass AllocateResources + `resolve_help`)

The cycle lives in `autoscaler/common/` because both scalers share the **window orchestrator**. AllocateResources and VicinityRound stay in `reactive_local/`; `common` only takes those as callables so it does not import a concrete scaler. Putting the file under `reactive_local/` would hide that proactive uses the same listing.

Each decision window runs the listing of Algorithm 2 in **one process**. There are no CM threads, no leader RPC, no barrier wait, and no plan timeout. Apply is synchronous (`Env.apply_actions` after the hook), so unmet residual after VicinityRound is logged in the same tick.

This is **not** `run_env_only.py`. Algorithm 1 (partition) can run with no autoscaler. Algorithm 2 only runs when `run_with_autoscaler.py` loads `reactive_local` or `proactive_auto_scaler`.

---

## When the cycle runs

`on_tick_end` still fires once after physics. Inside it:

1. **Observe every MS** (streaks, cooldown countdown, window sensing). Cooldown does **not** skip observation — that is stricter than tex `InCooldown` → `continue`.
2. **`cluster_manager_cycle`**: per owner cluster, enqueue \(\Delta\neq\) None, sort \(Q_c\), drain local AllocateResources (BEV then BEH).
3. Merge leftover \(\rho\) FCFS and run VicinityLeaderSchedule then BEG (`resolve_help`).

`M_c` is the set of microservices whose **app-owner cluster** is \(c\). A lender cluster does not run a second decide for a loaned replica (clarification 6: single writer). Fleet metrics already include borrowed containers.

The decide plug-in is reactive streaks or `PredictAndDecide` (Algorithm 3). How that listing is mapped, and why the residual uses serving headroom: [predict-and-decide.md](./predict-and-decide.md). The cycle does not own the predictor ensemble. Local BEV then BEH is Algorithm 4: [allocate-resources.md](./allocate-resources.md).

---

## Listing ↔ code

| Tex | Simulator |
|---|---|
| Run once per window at every cluster \(c\) | Loop owner clusters in sorted id order inside one hook |
| `CollectNodeMetrics` | Free CPU/RAM read on demand during BEH / help; leader snapshot is **after** local allocate |
| Scan \(M_c\) by microservice id | `sorted` members of each owner cluster |
| \(t_{det} \gets \mathrm{now}()\); sort \(Q_c\) by \(t_{det}\), then id | `t_det = τ`; sort `(t_det, ms_id)` |
| `AllocateResources` drain | `ladder_up` / `ladder_down` |
| Leader barrier + `VicinityLeaderSchedule` | After **all** clusters finished local allocate, one `schedule_vicinity_help` |
| Non-leaders submit \(Q_V^{local}\) | Same leftover list; no RPC |
| Apply via `RequestWorkerOwnerScale`; timeout → BEG | `apply_actions`; leftover after vicinity → BEG same tick |

`run_meta.yaml` `autoscaler.cycle` is `cluster_manager` when this path ran.

---

## Why three tex pieces are “missing,” and what we did

`docs/thesis-vs-simulator.md` used to list three ClusterManagerCycle gaps. They were **sim cuts**, not forgotten BEV/BEH. Mapped vs stubbed:

### Per-cluster CM and per-\((m,c)\) predictors

The tex runs a CM **at every cluster** with one predictor instance per \((m,c)\). This env is one after-tick hook. Mapping: group MS by **owner cluster**, fill \(Q_c\), drain local allocate, then help. Not mapped: one OS process per cluster, or a second decide on the lender for a loaned replica. Predictor history stays per `ms_id` (Algorithm 3).

### Detection-timestamp FCFS

The tex stamps \(t_{det} \gets \mathrm{now}()\) and sorts \(Q_c\) by that time (clarification 2). In a discrete tick every MS is seen at the same integer \(\tau\), so wall-clock `now()` would collapse to microservice id anyway. Mapping: stamp `t_det = τ` on intents and `HelpRequest`, sort `(t_det, ms_id)`. Do not invent sub-tick timestamps.

### Leader barrier / free-vector reports / \(\Delta t_{plan}\)

The tex waits for member free-vectors (\(\Delta t_{bar}\)), RPCs \(Q_V\) to the leader, and on plan timeout (\(\Delta t_{plan}\)) escalates to BEG. There are no member processes. Mapping: after **all** clusters finish local allocate, one in-process vicinity round (free snapshot minus pending actions), then BEG in the **same tick**. That is \(\Delta t_{plan}=0\). Do not add sleeps or `env.is_leader` as a second actor. Leader id is Algorithm 1 metadata.

`CollectNodeMetrics` at the **start** of the tex cycle is unused here; Reserve/`safe_j` would need it later. The vectors the leader needs are post-local, which is what `resolve_help` already snapshots.

---

## How to check a run

`run_env_only.py` never calls the cycle. Use `run_with_autoscaler.py`.

| File | What to look at |
|---|---|
| `run_meta.yaml` | **Algorithm 2 check.** `autoscaler.cycle: cluster_manager` and `autoscaler.name` (`reactive_local` or `proactive_auto_scaler`) |
| `actions.csv` | Ladder actually ran. Empty header-only (env-only style) is a failure on these configs |
| `*.log.csv` / `*.meta.json` | Conservation: incoming = served + dropped. Spawn `cluster_id` / `server_id` match the intended rung |

A run is fine when `cycle` is set and `actions.csv` shows the rung that config was built for (table below).

A run is **not** a failure because:

- BEH spawn lands on a worker that **already hosts** the MS (prefer-hosting), even if a sibling is empty
- Proactive on a one-cluster world logs `need_vicinity_help` after the home cluster fills (no `World.root`)
- Drops remain on peaked traces; the cycle does not add RTT

Dump:

```bash
DIR=results/reactive_local_60/<run_id>
python3 -c "
import csv, yaml
from collections import Counter
from pathlib import Path
p = Path('$DIR')
m = yaml.safe_load((p/'run_meta.yaml').read_text())
a = m.get('autoscaler') or {}
print('name ', a.get('name'))
print('cycle', a.get('cycle'))
rows = list(csv.DictReader((p/'actions.csv').open()))
print('actions', len(rows))
print(Counter((r['action_type'], r.get('reason','')) for r in rows))
"
```

---

## Demos and sample results

```bash
python3 -m pytest tests/test_cm_cycle.py tests/test_reactive_local.py tests/test_vicinity_help.py tests/test_unmet_demand.py -q

PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_60_reactive_local.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_60_vicinity_help.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_60_unmet_demand.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_60_proactive.yaml
```

(`pytest` already sets `pythonpath = ["src"]`. A one-off `python3 examples/...` needs `PYTHONPATH=src` unless the package is installed.)

Do **not** use `demo_partition.yaml` / `demo_partition_latency.yaml` for Algorithm 2; those are Algorithm 1 only (`run_env_only.py`). Triangle 400-tick configs also use this cycle but were built to isolate ladder rungs, not to prove the cycle listing.

Run ids are `{seed}_{UTC}`. Folders below are from 2026-08-27 checks.

| Config | What the cycle should do |
|---|---|
| `demo_60_reactive_local` | One cluster: local \(Q_c\) → BEV then in-cluster BEH |
| `demo_60_vicinity_help` | Home packed → leftover \(\rho\) → vicinity spawn on `c2` |
| `demo_60_global_help` | Local + vicinity packed → BEG spawn on `c3` |
| `demo_60_proactive` | Same world as reactive_local; decide is persistence; cycle is the same |

### `demo_60_reactive_local.yaml` — local BEV/BEH

Sample: `results/reactive_local_60/42_20260827T194609Z` (`allocate: allocate_resources`; actions match `42_20260827T062448Z`)

```yaml
autoscaler:
  enabled: true
  name: reactive_local
  cycle: cluster_manager
  allocate: allocate_resources
```

`actions.csv`: 7× `bev_up`, 1× `beh_spawn` (plus seed). No `vicinity_spawn` / `beg_spawn`. The BEH replica landed on **c1-w1** (already hosting), not empty sibling `c1-w2` — BEH prefer-hosting, not a cycle miss. Conservation held.

### `demo_60_vicinity_help.yaml` — leftover → vicinity

Sample: `results/vicinity_help_60/42_20260827T194610Z` (`allocate: allocate_resources`; actions match `42_20260827T062448Z`)

`cycle: cluster_manager`. 5× `vicinity_spawn` onto **c2** (`c-api-c2-w1-*`). No `beg_spawn`. Also some `bev_up` on the home replica. Conservation held.

### `demo_60_global_help.yaml` — leftover → BEG

Sample: `results/global_help_60/42_20260827T062449Z`

`cycle: cluster_manager`. 5× `beg_spawn` onto **c3** (`c-api-c3-w1-*`). Neighbor `c2` is too small for a packed vicinity replica. Conservation held.

### `demo_60_proactive.yaml` — same cycle, Algorithm 3 decide

Sample: `results/proactive_60/42_20260827T194610Z` (`decide: predict_and_decide`, `allocate: allocate_resources`; actions match `42_20260827T062449Z`)

```yaml
autoscaler:
  name: proactive_auto_scaler
  cycle: cluster_manager
  decide: predict_and_decide
  allocate: allocate_resources
```

Local `beh_spawn` / `beh_terminate` / `bev_up` on **c1** only. Two `need_vicinity_help` log lines after the home cluster filled (no root). No `vicinity_spawn` / `beg_spawn`. More local spawns than reactive_local, so fewer drops on the same trace. Conservation held.

---

## Tests

```bash
python3 -m pytest tests/test_cm_cycle.py tests/test_reactive_local.py tests/test_vicinity_help.py tests/test_unmet_demand.py -q
```

`test_cm_cycle.py` checks per-cluster allocate order and FCFS help merge by `(t_det, ms_id)` without needing a full 60-tick run.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-27 | Algorithm 2 mapped as in-process per-cluster \(Q_c\) |
| v2 | 2026-08-27 | Cycle moved to `autoscaler/common/cm_cycle.py` |
| v3 | 2026-08-27 | Why the tex gaps stay stubbed; how to read runs; 60-tick sample excerpts |
| v4 | 2026-08-27 | Pointer to Algorithm 3 decide field on the proactive sample |
| v5 | 2026-08-27 | Pointer to Algorithm 4 allocate field |
