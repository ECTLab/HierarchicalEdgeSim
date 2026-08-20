# Triangle ladder slices — four topologies, one trace

**Status:** configs on `code-review`  
**Trace:** `traces/demo/api_400_triangle.csv` (Λ 40 → 180 by τ=200, 180 → 5 by τ=320, hold at 5)  
**Physics:** `cpu_min=0.5`, `cpu_max=1.0` ⇒ μ_max = 50 req/tick; peak 180 needs four full replicas  
**Related:** [mu-matched-cpu-ram-scale.md](./mu-matched-cpu-ram-scale.md), [surplus-down-resource-quantum-and-seed-log.md](./surplus-down-resource-quantum-and-seed-log.md), [s6-scale-down-reclaim.md](./s6-scale-down-reclaim.md)

The original triangle demo (`demo_400_triangle_beg.yaml`) is one topology: one
tiny home worker, one tiny neighbor, one fat BEG worker. That is the **full
ladder** control. It does not prove local BEH, a fat vicinity (no BEG), or
skipping a floor-only neighbor. Those are separate slices, not more clusters
on the same picture.

Do **not** grow this into a large matrix. Four synthetics plus the existing
Alibaba `reactive_local` re-run are enough to trust the post-surplus /
packed-spawn path. 60-tick demos still exist as smoke; they do not hold long
enough for surplus reclaim.

---

## The four synthetics

| Config | Isolates | Topology | Must see | Must not see |
|---|---|---|---|---|
| `demo_400_triangle_beh.yaml` | In-cluster BEH | c1-w1 filled (1.0); empty sibling c1-w2 (8.0); no vicinities | `beh_spawn` / `beh_terminate` on `c1-w2`; one leftover on c1 | `vicinity_*`, `beg_*` |
| `demo_400_triangle_vicinity.yaml` | Packed vicinity | c1 filled; fat c2 (8.0) in v1; no c3 | `vicinity_spawn` / `vicinity_terminate` on c2, `cpu_new>0.50` | `beg_*`, `beh_*` |
| `demo_400_triangle_skip_beg.yaml` | Floor skip → BEG | c1 filled; c2=0.4 (below min); fat c3 outside v1 | `beg_spawn` / `beg_terminate` on c3, no spawn on c2 | `vicinity_*` |
| `demo_400_triangle_beg.yaml` | Full ladder | c1 1.0 + c2 1.0 + fat c3 | vicinity then BEG (spawn **and** terminate) | local `beh_spawn` / `beh_terminate` |

Every slice: reclaim to **one** live replica in cluster `c1`, last alloc `> cpu_min`, leftover RAM near `ram_min + μ · ρ_ram` (not `ram_max`), no UP after the last extra terminate. Packed extras spawn above the floor (`cpu_new>0.50`) with RAM matched to that μ, not `α_up · seed RAM`.

BEH-only is the exception on *which* replica survives. Vicinity and BEG extras are a cheaper loan tier, so they die first and `c-api-0` on `c1-w1` remains. In-cluster extras are the same tier as the seed; among equal μ the ranker is `(q, -slack, container_id)`, so `c-api-0` can be reclaimed and the leftover sits on the fat sibling (`c1-w2`). That still satisfies LAST_REPLICA and surplus hold. Do not treat it as a keep-seed failure.

`cascade_home` is **off** on all four. Surplus down skips BEV while extras exist and reclaims remotes first, so cascade-home has nothing to pull. That is a separate policy question, not a fifth topology.

---

## Terminate reasons match spawn rungs

Scale-up already stamped the rung (`beh_spawn` / `vicinity_spawn` / `beg_spawn`). Scale-in used to stamp every extra kill as `beh_terminate`, including global loans on `c3`. That was a leftover name from `beh_down`, not a wrong kill order.

`beh_down` still ranks global → vicinity → local. It now stamps the same key:

| Loan rung | Spawn | Terminate |
|---|---|---|
| Global (BEG) | `beg_spawn` | `beg_terminate` |
| Vicinity | `vicinity_spawn` | `vicinity_terminate` |
| In-cluster extra | `beh_spawn` | `beh_terminate` |

`cascade_terminate` is migrate-home, not this reclaim path. Unknown remotes (no loan row) still rank as global, so they log `beg_terminate`. Plot legends follow the new reasons (`BEG terminate`, `vicinity terminate`); older run dirs that predate this change still show remotes as `beh_terminate`.

---

## How to run

```bash
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_400_triangle_beh.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_400_triangle_vicinity.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_400_triangle_skip_beg.yaml
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_400_triangle_beg.yaml
```

Plots (needs matplotlib on `PYTHONPATH`):

```bash
python3 examples/compare_trace_vs_log.py <run_dir>
```

Look at `analysis/demo_app/ladder_qos.png` and `replicas_by_site.png`.

Alibaba regression (ρ=0.0004, 0.01 alloc quantum): `configs/demo_alibaba_reactive_local.yaml`.

---

## Recorded runs (seed 42)

Every slice dropped **27 / 33412 (0.08%)** on the pre-μ-match runs. Conservation holds. After μ-matched scale, extras pack at **0.70 / 266** (not 358.40) and BEV-up RAM stops at **281** (`ram_min + 50 × 0.5`). The YAML seed can still start at 512; surplus down idle-trims leftover RAM to **259.85** (`ram_min + μ_tgt × ρ_ram`).

Recorded full-ladder run after this change: `results/triangle_beg/42_20260820T115435Z`. Re-run the other three slices to refresh their `actions.csv`. Older folders keep the dual-wallet RAM numbers.

| Slice | Run dir | Extra spawn | Extra terminate | Leftover |
|---|---|---|---|---|
| BEH | `results/triangle_beh/42_20260820T103939Z` | 3× `beh_spawn` on `c1-w2` | 3× `beh_terminate` (includes seed `c-api-0`) | `c-api-c1-w2-2` on `c1-w2` |
| Vicinity | `results/triangle_vicinity/42_20260820T110318Z` | 3× `vicinity_spawn` on `c2-w1` | 3× `vicinity_terminate` | `c-api-0` on `c1-w1` |
| Skip → BEG | `results/triangle_skip_beg/42_20260820T110032Z` | 3× `beg_spawn` on `c3-w1` | 3× `beg_terminate` | `c-api-0` on `c1-w1` |
| Full ladder | `results/triangle_beg/42_20260820T110507Z` | 1× `vicinity_spawn` on `c2`, then 2× `beg_spawn` on `c3` | 2× `beg_terminate`, then 1× `vicinity_terminate` | `c-api-0` on `c1-w1` |

UTC stamps in folder names will not match another machine. Prefer the latest dir under each `results/triangle_*/`. Folders from `42_20260820T103939Z` for vicinity and skip-BEG are **pre-fix**: same kills, but remotes still say `beh_terminate`.

Vicinity extras after the label fix:

```
257  terminate  c-api-c2-w1-3  vicinity_terminate
279  terminate  c-api-c2-w1-1  vicinity_terminate
302  terminate  c-api-c2-w1-2  vicinity_terminate
```

Skip-BEG extras:

```
257  terminate  c-api-c3-w1-3  beg_terminate
279  terminate  c-api-c3-w1-1  beg_terminate
302  terminate  c-api-c3-w1-2  beg_terminate
```

Full ladder reclaim is global first, then vicinity (`c3` dies before `c2`), which is the S6 order.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v4 | 2026-08-20 | μ-matched CPU/RAM scale; leftover RAM ≈ 260 not 512 |
| v3 | 2026-08-20 | Recorded run dirs after terminate-reason fix; vicinity / skip-BEG / BEG CSVs stamp `vicinity_terminate` / `beg_terminate` |
| v2 | 2026-08-20 | Reclaim reasons match spawn rungs (`beg_terminate` / `vicinity_terminate`) |
| v1 | 2026-08-20 | BEH / vicinity / skip-BEG slices next to the full-ladder triangle |
