# S1 — Horizontal mutation APIs (`spawn` / `terminate`)

**Status:** done  
**Branch:** `ladder-based-implementation`  
**Roadmap:** [10-proposed-implementation-roadmap.md](./10-proposed-implementation-roadmap.md) §3 S1  
**Authority:** `proposed_method_complete.tex` (BEH prerequisites — Alg. BEH uses spawn/terminate)

S1 is only the **horizontal mutation APIs**. No autoscaler policy yet. A scripted caller (or tests) can create/remove replicas; the reactive ladder that decides *when* comes in S2.

---

## Why this stage exists

Every later ladder tier (BEH, vicinity help, BEG) is meaningless while `Env.spawn` / `Env.terminate` raise `NotImplementedError`. S1 turns those stubs into real, validated mutations so S2 can emit `SpawnAction` / `TerminateAction` instead of only logging `need_horizontal`.

**Still out of scope here:** policy that *decides* when to spawn; loans; foreign clusters; vicinity/global placement.

---

## What landed

### `Env.spawn(ms_id, server_id, …)`

Creates a container on a chosen server (horizontal scale-out).

- Default alloc = MS minima if `cpu_alloc_cores` / `ram_alloc_mb` are omitted (paper: new instance ≥ `cpu_min` / `ram_min`)
- Rejects below MS min, above MS max, insufficient server free CPU/RAM, unknown MS or server, duplicate container id
- Registers on `world.containers`, the MS `container_ids`, and the server `container_ids`
- Optional `container_id`; otherwise auto-id `c-{ms}-{server}-{n}`

Result codes (`SpawnResultCode`): `OK`, `UNKNOWN_MS`, `UNKNOWN_SERVER`, `BELOW_MS_MIN`, `ABOVE_MS_MAX`, `SERVER_CPU_EXCEEDED`, `SERVER_RAM_EXCEEDED`, `DUPLICATE_CONTAINER_ID`, `DUPLICATE_IN_BATCH`.

### `Env.terminate(container_id)`

Removes a live container and frees capacity (horizontal scale-in).

- Unregisters via `world.remove_container` (indexes on world / server / microservice)
- Rejects unknown id, MS mismatch (when `ms_id=` is passed), and **`LAST_REPLICA`** — must keep ≥1 replica so routing still has a target

Result codes (`TerminateResultCode`): `OK`, `UNKNOWN_CONTAINER`, `LAST_REPLICA`, `MS_MISMATCH`, `DUPLICATE_IN_BATCH`.

### Action types + `apply_actions`

- Canonical types live in `env/api.py`: `SpawnAction`, `TerminateAction` (alongside existing `ResizeAction` / `NeedHorizontalAction`)
- `autoscaler/common/actions.py` re-exports them for scaler modules
- **`apply_actions` order lock:** terminate → need_horizontal (log only) → resize → spawn; then `ms_id`, then `container_id`, then `server_id`
- Each attempt is written to the action log (same path that becomes `actions.csv` on a run)

Terminate-before-spawn is intentional: a batch can free capacity and immediately reuse it for a new replica in the same tick.

### World helper

`remove_container` in `env/world.py` unwinds indexes on terminate (pair of existing `place_container`).

---

## Tests

New file: `tests/test_spawn_terminate.py`. Removed the old stub test that expected `spawn`/`terminate` to raise `NotImplementedError` (`tests/test_api.py`).

S1 coverage:

| Test | What it checks |
|---|---|
| `test_spawn_defaults_to_ms_minima` | Spawn without alloc uses MS min; indexes and free capacity update |
| `test_spawn_rejects_below_min_and_server_full` | `BELOW_MS_MIN` and `SERVER_CPU_EXCEEDED` |
| `test_spawn_rejects_duplicate_id` | Cannot reuse an existing container id |
| `test_spawn_affects_routing_next_tick` | New replica gets load on the next non-zero-trace tick (equal headroom → equal share) |
| `test_terminate_last_replica_rejected` | Last replica cannot be terminated |
| `test_terminate_frees_capacity_for_respawn` | Terminate frees capacity so a later spawn can succeed |
| `test_apply_actions_order_terminate_resize_spawn` | Batch apply order terminate → resize → spawn |
| `test_apply_actions_spawn_duplicate_id_in_batch` | Duplicate spawn id in one batch → `DUPLICATE_IN_BATCH` |

### What was run

Full suite from repo root:

```bash
python3 -m pytest tests/ -q --tb=line
```

**Result: 122 passed, 0 failed.**

Focused S1-related files were also run earlier (`test_spawn_terminate`, `test_api`, `test_resize`, `test_apply_actions_hook`, `test_reactive_vertical`).

### How to see the results

From the repo root:

```bash
cd /home/sky/HierarchicalEdgeSim
python3 -m pytest tests/ -v
```

Useful variants:

```bash
# S1 only
python3 -m pytest tests/test_spawn_terminate.py -v

# Quiet summary
python3 -m pytest tests/ -q

# JUnit XML for CI / IDE
python3 -m pytest tests/ -v --junitxml=results/pytest-report.xml
```

In VS Code: open the Testing view and run the `tests` folder, or run the commands above in the integrated terminal — pytest prints each test and a final passed/failed count.

`pyproject.toml` already sets `pythonpath = ["src"]` for pytest, so `PYTHONPATH=src` is optional when using `python3 -m pytest`.

---

## Gate (met)

Horizontal mutation works with unit tests / scripted `apply_actions`. No smart policy required.

Next: **S2 — reactive local ladder (BEV → BEH inside one cluster)**.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-15 | S1 implementation notes: APIs, apply order, tests, how to rerun |
