# Part A — Step-by-Step Implementation Guide

Hands-on build order for the Part A environment simulator. This doc turns [03-implementation-plan.md](./03-implementation-plan.md) milestones **A0–A7** into concrete tasks with **tests after every step** and a **human review gate** before moving on.

**Scope:** Part A only (environment, no live autoscaler).  
**Spec authority:** [03-implementation-plan.md](./03-implementation-plan.md) v8 — if this guide and the plan disagree, the plan wins.

---

## How to use this guide

Each step follows the same rhythm:

```text
Implement → run tests → fill review checklist → you sign off → next step
```

| Column | Meaning |
|---|---|
| **Build** | What to implement, in order, inside that step |
| **Tests** | Commands and test names that must pass before review |
| **Review packet** | What to paste or show us (diff summary, pytest output, one numeric check) |
| **Gate** | Explicit pass/fail criteria — do not start the next step until all gates are green |

**Rule:** one step at a time. If a gate fails, fix within the same step; do not carry debt forward.

---

## Before Step 0 — lock four decisions (5 minutes)

Confirm once; record in the Step 0 review packet.

| Decision | Recommended | Why |
|---|---|---|
| Python | **3.14+** | Project requirement |
| Project folder | **`HierarchicalEdgeSim/`** at repo root | All simulator code lives here |
| Import package | **`hierarchical_edge_sim`** | Python module name (snake_case); display name HierarchicalEdgeSim |
| Dependencies | **`pyyaml`**, **`pytest`** only for Part A | Traces/logs via stdlib `csv`; keep eval loop dependency-light |
| Repo layout | `HierarchicalEdgeSim/` subfolder | Keeps thesis/docs separate from simulator code |

---

## Step 0 — Scaffold (milestone A0)

**Goal:** Empty package installs; pytest runs; reference config + trace files exist on disk.

### Build

1. Create tree under `HierarchicalEdgeSim/`:
   - `pyproject.toml` — editable install, `src` layout, `requires-python >= 3.14`
   - `src/hierarchical_edge_sim/__init__.py`, `src/hierarchical_edge_sim/env/__init__.py`
   - `configs/00-tiny.yaml` — copy from plan §11
   - `traces/demo/api.csv` — copy from plan §11
   - `tests/conftest.py` — optional: `tiny_config_path` fixture
2. Add `tests/test_import_hierarchical_edge_sim.py`:
   - `import hierarchical_edge_sim`
   - `import hierarchical_edge_sim.env`
3. Add `.gitignore` entries: `__pycache__/`, `.pytest_cache/`, `*.egg-info/`, `results/`

### Tests

```bash
cd HierarchicalEdgeSim
pip install -e ".[dev]"
pytest tests/test_import_hierarchical_edge_sim.py -v
test -f configs/00-tiny.yaml
test -f traces/demo/api.csv
```

### Review packet

- Pytest output (all passed)
- `tree HierarchicalEdgeSim/` or file listing showing layout
- Confirm `00-tiny.yaml` and `api.csv` byte-match plan §11 (or diff if intentional)

### Gate

- [ ] `pip install -e .` succeeds
- [ ] `pytest` discovers and runs at least one test
- [ ] Reference config + trace present and readable

**Sign-off:** ___ (reviewer) ___ Date: ___

---

## Step 1 — Config types + YAML load (A1, part 1)

**Goal:** Parse `00-tiny.yaml` into typed dataclasses; no validation yet.

### Build

1. `env/config.py`:
   - Constants: `EPS = 1e-9`
   - Dataclasses: `SimConfig`, `ServerSpec`, `ClusterSpec`, `ContainerSpec`, `MicroserviceSpec`, `AppSpec`, `RawConfig`, `WorldSpec`
   - `load_yaml(path: str | Path) -> RawConfig`
   - `to_world_spec(config: RawConfig) -> WorldSpec` — structural copy only; assumes valid input
2. Wire field names exactly to plan §11 (`cpu_*_cores`, `ram_*_mb`)

### Tests

Add `tests/test_config.py`:

| Test | Assert |
|---|---|
| `test_load_tiny_yaml_parses` | Load `configs/00-tiny.yaml`; IDs and numeric fields match §11 |
| `test_world_spec_roundtrip_fields` | `to_world_spec(load_yaml(...))` preserves cluster/server/app/ms/container counts |

```bash
pytest tests/test_config.py -v
```

### Review packet

- One-liner: number of clusters, servers, apps, microservices, containers parsed from `00-tiny.yaml`
- Snippet: `MicroserviceSpec` fields for `api` (cpu_min, cpu_max, trace_file)

### Gate

- [ ] All `test_config.py` green
- [ ] No validation logic in this step (parsing only)

**Sign-off:** ___ Date: ___

---

## Step 2 — Validator (A1, part 2)

**Goal:** Full §3.2 pre-check; `validate_or_raise` returns `WorldSpec` or raises `ConfigError`.

### Build

1. `env/validate.py`:
   - `ValidationError`, `ConfigError`
   - `validate(config: RawConfig) -> list[ValidationError]`
   - `validate_or_raise(config: RawConfig) -> WorldSpec`
2. Implement every rule in plan §3.2 (including MS/App/Cluster coverage, float `EPS` slack).
3. Trace checks at validate time: read CSVs for header, row count, `time_unit` sequence, `requests ≥ 0` — do **not** build `TraceStore` here.

### Tests

Add `tests/fixtures/` — one minimal broken YAML or trace per reject rule:

| Fixture (example name) | Rule exercised |
|---|---|
| `dup_container_id.yaml` | Unique IDs |
| `empty_apps.yaml` | Non-empty world |
| `ms_no_containers.yaml` | MS coverage |
| `app_no_ms.yaml` | App coverage |
| `cluster_no_servers.yaml` | Cluster coverage |
| `bad_server_ref.yaml` | References |
| `orphan_server.yaml` | Cluster membership |
| `zero_cpu_cap.yaml` | Server caps |
| `bad_ms_coeffs.yaml` | MS coeffs |
| `alloc_above_max.yaml` | Container alloc |
| `overpacked_server.yaml` | Server packing |
| `missing_traces_dir/` | Traces dir |
| `missing_trace.csv` setup | Trace files |
| `trace_len_mismatch/` | Trace length |
| `bad_trace_header.csv` | Trace header |
| `bad_time_unit_seq.csv` | Trace `time_unit` |
| `negative_requests.csv` | Trace values |
| `bad_sim.yaml` | Sim |

Add `tests/test_validate.py`:

| Test | Assert |
|---|---|
| `test_tiny_yaml_validates_clean` | `validate_or_raise(tiny)` returns `WorldSpec`, no errors |
| `test_reject_<rule>` | One parametrized or named test per fixture above |

```bash
pytest tests/test_validate.py -v
pytest tests/ -v    # full suite so far
```

### Review packet

- Pytest count: **N reject tests + 1 golden pass** (expect ≥ 20 tests in `test_validate.py`)
- Paste one example `ValidationError` (path + message) from a reject test
- Confirm: invalid config never reaches `build_world` (no world module yet — note as design intent)

### Gate

- [ ] `00-tiny.yaml` passes `validate_or_raise`
- [ ] Every §3.2 row has a failing fixture test
- [ ] Trace files read during validate only for checks

**Sign-off:** ___ Date: ___

---

## Step 3 — Domain models (A2, part 1)

**Goal:** Runtime dataclasses for world objects; no builder yet.

### Build

1. `env/models.py`:
   - `ContainerTickRecord` (fields per plan §7, `lambda_in` not `lambda_arrival`)
   - `Container`, `Microservice`, `Server`, `Cluster`, `App`
   - Back-pointers and list fields per plan §16.3
   - `Container.append_history(...)`, `history`, `history_at(tau)`

### Tests

Add `tests/test_models.py`:

| Test | Assert |
|---|---|
| `test_container_tick_record_fields` | Dataclass has expected fields |
| `test_container_history_append_and_at` | Append 3 ticks; `history_at(2)` correct |

```bash
pytest tests/test_models.py -v
```

### Review packet

- Field list for `ContainerTickRecord` (screenshot or paste)
- Confirm `lambda_in` naming

### Gate

- [ ] Models importable without circular deps
- [ ] History API works in isolation

**Sign-off:** ___ Date: ___

---

## Step 4 — World builder (A2, part 2)

**Goal:** `build_world(world_spec) -> World` with correct registries and parent indexes.

### Build

1. `env/world.py`:
   - `World` dataclass with `apps`, `clusters`, `servers`, `microservices`, `containers` dicts
   - `build_world(spec: WorldSpec) -> World`
   - `place_container(...)` per plan §16.3
   - `server_free_cpu_cores(server)`, `server_free_ram_mb(server)` — cap minus sum of **alloc**

### Tests

Add `tests/test_world.py`:

| Test | Assert |
|---|---|
| `test_build_world_tiny_topology` | 1 cluster, 2 servers, 1 app, 1 ms, 1 container |
| `test_server_container_ids` | `c1-w1.container_ids == ["c-api-1"]`; `c1-w2` empty |
| `test_server_free_capacity_tiny` | `c1-w1` free CPU = 7.0, free RAM = 15872 (plan §11.1 sanity) |
| `test_cluster_server_backpointer` | `Server.cluster_id == "c1"` |

```bash
pytest tests/test_world.py -v
pytest tests/ -v
```

### Review packet

- Print free capacity for both servers from a one-line script or test output
- Confirm bidirectional indexes: parent lists + child `*_id` fields

### Gate

- [ ] `build_world(validate_or_raise(load_yaml(tiny)))` succeeds
- [ ] Free capacity uses **allocation**, not usage

**Sign-off:** ___ Date: ___

---

## Step 5 — TraceStore (A3)

**Goal:** Load validated traces; 1-based `get(ms_id, tau)` API.

### Build

1. `env/traces.py`:
   - `TraceStore` with internal `dict[str, list[float]]` (0-based storage)
   - `load_traces(world_spec: WorldSpec) -> TraceStore` — call only after validate
   - `get(ms_id: str, tau: int) -> float` — `tau` 1-based, plan §6.3

### Tests

Add `tests/test_traces.py`:

| Test | Assert |
|---|---|
| `test_load_demo_trace` | `N == 5`; `get("api", 4) == 120.0` |
| `test_get_tau_one_based` | `get(..., 1)` is first data row, not header |
| `test_trace_length_mismatch_rejected` | Covered in Step 2 if validate loads traces; optional integration test here |

Add `tests/fixtures/traces/` if not already present for length mismatch.

```bash
pytest tests/test_traces.py -v
```

### Review packet

- Table: τ = 1..5, `get("api", τ)` values vs `api.csv`
- Confirm validate-then-load pipeline: document call order in one sentence

### Gate

- [ ] Indexing: public 1-based, internal 0-based
- [ ] Values match §11 trace file

**Sign-off:** ___ Date: ___

---

## Step 6 — Usage formulas (A4, part 1)

**Goal:** Pure functions for μ, usage, q; no routing yet.

### Build

1. `env/usage.py`:
   - `serving_capacity(container, spec) -> float` — plan §4.2, including `ram_per_request_mb == 0 → INF` branch
   - `apply_tick(container, lambda_in, spec, tau) -> ContainerTickRecord` — updates usage + history
   - Utilization `q_cpu`, `q_ram` per §4.2

### Tests

Add `tests/test_usage.py`:

| Test | Assert |
|---|---|
| `test_serving_capacity_tiny_container` | μ = 50 for §4.4 A setup |
| `test_apply_tick_golden_rows` | For single-container §11.1: all 5 rows match λ_served, λ_dropped, cpu_used |
| `test_ram_per_request_zero_not_binding` | `ram_per_request_mb=0` → no ZeroDivisionError; CPU binds |
| `test_zero_headroom_serves_nothing` | `cpu_alloc == cpu_min` → μ = 0, usage = min floor |

```bash
pytest tests/test_usage.py -v
```

### Review packet

- Paste §11.1 golden table with **computed vs expected** columns (all match)
- Note how `ram_per_request_mb == 0` is handled (one sentence)

### Gate

- [ ] §11.1 numbers exact (use `pytest.approx` only if truly needed for floats)
- [ ] Idle tick (τ=1): `cpu_used_cores == 0.5` (floor, not 0)

**Sign-off:** ___ Date: ___

---

## Step 7 — Routing (A4, part 2)

**Goal:** Capacity-weighted split; equal-share fallback when `sum(h) ≤ EPS`.

### Build

1. `env/routing.py`:
   - `distribute(Λ, containers, cpu_min_cores) -> dict[str, float]` — plan §4.3
   - Single-container shortcut: weight 1.0

### Tests

Add `tests/test_routing.py`:

| Test | Assert |
|---|---|
| `test_single_replica_gets_all_lambda` | Λ=120 → one container λ_in=120 |
| `test_heterogeneous_split` | §4.4 B: A gets 66.7, B gets 333.3 (pytest.approx) |
| `test_zero_headroom_equal_share` | All h_i=0 → equal split; no division by zero |
| `test_routing_plus_usage_end_to_end` | §4.4 B full row: served/dropped per container |

```bash
pytest tests/test_routing.py -v
pytest tests/test_usage.py tests/test_routing.py -v
```

### Review packet

- §4.4 B numeric table (A and B: λ_in, λ_served, λ_dropped)
- Confirm weights use **CPU headroom only**, not RAM

### Gate

- [ ] Heterogeneous case matches §4.4 B within tolerance
- [ ] `distribute` never called with `len(containers)==0` (validator prevents)

**Sign-off:** ___ Date: ___

---

## Step 8 — Tick engine (A5)

**Goal:** Full simulation loop; in-memory history matches §11.1.

### Build

1. `env/engine.py`:
   - `Engine` or module functions: `run(world, traces) -> None` or `run_ticks(...) -> int`
   - Loop per plan §2.1 / §16.4: `sorted(microservices, key=id)`, apply routing + usage each τ
   - `current_tau` on `Env` or engine state
2. No disk I/O in this step.

### Tests

Add `tests/test_engine.py`:

| Test | Assert |
|---|---|
| `test_engine_tiny_five_ticks` | After run, `c-api-1.history` length 5 |
| `test_engine_golden_table` | Each τ: Λ, λ_served, λ_dropped, cpu_used vs §11.1 |
| `test_ms_processing_order_deterministic` | Two runs → identical histories (prep for A7) |

```bash
pytest tests/test_engine.py -v
pytest tests/ -v
```

### Review packet

- Full §11.1 table from test output
- Confirm no flush/metrics yet (in-memory only)

### Gate

- [ ] 5-tick integration green
- [ ] Drops on τ=3 and τ=4 match 30 and 70

**Sign-off:** ___ Date: ___

---

## Step 9 — Metrics + disk outputs (A6)

**Goal:** `results/<run_id>/` tree, meta.json, log.csv per plan §8.

### Build

1. `env/metrics_log.py`:
   - `run_id = f"{seed}_{utc_timestamp}"` — inject clock or pass timestamp for tests
   - Write `run_meta.yaml`, `*.meta.json`, `*.log.csv` columns per §8.3
   - `flush(world, tau)` each tick or batch at end (plan allows per-tick flush)
2. Wire engine to call flush.
3. `examples/run_env_only.py` — CLI: `python examples/run_env_only.py configs/00-tiny.yaml`

### Tests

Add `tests/test_metrics_log.py`:

| Test | Assert |
|---|---|
| `test_results_tree_layout` | Paths under `results/<run_id>/apps/demo_app/api/` |
| `test_log_csv_columns` | Header matches §8.3 |
| `test_log_csv_golden_tick4` | Row τ=4: incoming=120, served=50, dropped=70, cpu_core_used=1.0 |
| `test_meta_json_fields` | Required keys from §8.2 |

Use `tmp_path` + fixed timestamp in run_id for deterministic paths in tests.

```bash
pytest tests/test_metrics_log.py -v
python examples/run_env_only.py configs/00-tiny.yaml
```

### Review packet

- Directory listing of one run
- First/last 2 lines of `c-api-1.log.csv`
- `run_meta.yaml` snippet (seed, N)

### Gate

- [ ] Example script runs without error
- [ ] CSV columns human-readable per §8.3
- [ ] Log values match §11.1

**Sign-off:** ___ Date: ___

---

## Step 10 — Env API facade (A5/A6 glue)

**Goal:** Single entrypoint; read API; write API types only.

### Build

1. `env/api.py`:
   - `Env.from_config(path)` — load → validate → build → traces → ready
   - `run()` — engine + metrics
   - Read methods per plan §9
   - `RejectReason` enum + stub signatures for `spawn` / `resize` / `terminate` (raise `NotImplementedError` or return typed reject — **no live mutations in Part A**)

### Tests

Add `tests/test_api.py`:

| Test | Assert |
|---|---|
| `test_from_config_invalid_raises` | Bad YAML → `ConfigError` |
| `test_get_time_after_partial_run` | After 3 ticks, `get_time()==3` |
| `test_list_containers_includes_c_api_1` | Inventory matches world |
| `test_spawn_not_implemented_part_a` | Documented stub behavior |

```bash
pytest tests/test_api.py -v
pytest tests/ -v
```

### Review packet

- List of public `Env` methods implemented
- Confirm write APIs are stubs only

### Gate

- [ ] `Env.from_config("configs/00-tiny.yaml").run()` is the one-liner demo
- [ ] Invalid config fails before world build

**Sign-off:** ___ Date: ___

---

## Step 11 — Determinism + exit criterion (A7)

**Goal:** Reproducible logs; Part A complete.

### Build

1. Ensure `run_id` timestamp can be fixed in tests (dependency injection).
2. Seed affects only run_id prefix (and any future stochastic paths — none in Part A).

### Tests

Add to `tests/test_engine.py` or `tests/test_determinism.py`:

| Test | Assert |
|---|---|
| `test_two_runs_identical_logs` | Same seed + fixed clock → byte-identical `c-api-1.log.csv` |
| `test_full_suite_on_tiny` | Smoke: entire `pytest` green |

```bash
pytest tests/ -v
python examples/run_env_only.py configs/00-tiny.yaml
# optional: run twice, diff logs
```

### Review packet

- `pytest tests/ -v` final count and duration
- `diff` output of two log CSVs (empty)
- Short **Part A done** checklist vs plan §12 exit criterion

### Gate

- [ ] All tests green
- [ ] Example script matches §11.1
- [ ] Plan §14 checklist items you accept (tick below)

**Sign-off:** ___ Date: ___

---

## Part A completion checklist (plan §14)

Copy into final review PR or issue:

- [ ] Complete config sketch + golden table (§11) — verified by tests
- [ ] Pre-check rules (§3.2) — one test per rule
- [ ] Per-MS traces + TraceStore indexing (§6)
- [ ] Drop-only overflow — engine drops logged, no queue field
- [ ] `cpu_*_cores` naming — consistent in code and CSVs
- [ ] Object model (§16) — world builder matches diagram
- [ ] Milestones A0–A7 — all gates signed off

---

## Suggested review rhythm with us

| When | You send | We reply with |
|---|---|---|
| After each step | Pytest output + review packet bullets | Pass → next step, or specific fix list |
| After Step 2 | Validator fixture list | Missing rule coverage if any |
| After Step 6 | Golden table diff | Numeric disagreement hunt |
| After Step 9 | Sample log CSV | Column / path issues |
| After Step 11 | Full suite + diff | Part A sign-off or punch list |

**Tip:** Keep each step in its own git branch or commit (`part-a/step-0-scaffold`, …) so review diffs stay small.

---

## Test commands cheat sheet

```bash
cd HierarchicalEdgeSim
pytest tests/ -v                           # full suite
pytest tests/test_validate.py -v           # Step 2
pytest tests/test_usage.py -v              # Step 6
pytest tests/test_engine.py -v             # Step 8
python examples/run_env_only.py configs/00-tiny.yaml
```

---

## What comes after Part A (do not start yet)

Part B per plan §13: live `spawn` / `resize` / `terminate`, decision cadence, policy thresholds, hierarchical plugin. Requires Part A sign-off on this doc’s Step 11 gate.

---

## Document history

| Version | Change |
|---|---|
| v1 | Initial step-by-step guide with per-step tests and human review gates |
