# S6 — Scale-down reclaim order + cascading migration

**Status:** done  
**Branch:** `ladder-based-implementation`  
**Roadmap:** [proposed-implementation-roadmap.md](./proposed-implementation-roadmap.md) §3 S6  
**Depends on:** [s5-global-help.md](./s5-global-help.md)

Scale-up walks BEV → BEH → vicinity → BEG. Scale-down never leaves the home cluster for *growth*. It only **releases** borrowed capacity, expensive first, then may pull one leftover loan home if this tick freed local minima.

---

## Reclaim order

`beh_down` ranks extra replicas:

1. **Global** loans (older `LoanRecord.ts` first) → `beg_terminate`
2. **Vicinity** loans (older ts first) → `vicinity_terminate`
3. **Local** replicas (lowest `q`, then slack, then id) → `beh_terminate`

Never terminate the last replica. Down still does not emit vicinity/BEG help.

Unknown remote (no loan row) is treated as global so it is still released before local (`beg_terminate`). `cascade_terminate` is a migrate-home, not this reclaim path.

---

## CheckCascadingMigration

After BEV shrink + BEH terminate, if **this tick** freed local CPU/RAM of at least MS minima (local shrink or local terminate — not a loan teardown), and a borrowed replica is still live:

1. Prefer a **global** leftover over vicinity (then older ts).
2. If a home worker can fit a minima replica after pending actions, emit `cascade_terminate` on the borrowed instance and `cascade_spawn` at home.
3. Does **not** add that migrate into the shrink residual (paper: cascade does not alter `r`).

Apply order is terminate → spawn, so a local replica must remain or `LAST_REPLICA` would reject the borrowed terminate.

`cascade_home` (default **true**) turns this off for ablation. YAML: `autoscaler.params.cascade_home: false`.

Lite vs paper: no distance `d(home, owner(j))` when choosing which loan to pull; ts then id. Cross-app “freed room helps a *different* MS” is the prose motivation; the algorithm is per-`m` and that is what we run.

---

## Tests

`tests/test_scale_down_reclaim.py`:

- Local + vicinity + global at minima → terminate **global** only
- Oversized local shrink frees minima → cascade pulls **global** home; vicinity loan stays
- `cascade_home: false` → shrink only, no migrate

Existing S4 `test_scale_down_prefers_borrowed_replica` still holds (one vicinity loan, no global).

```bash
python3 -m pytest tests/test_scale_down_reclaim.py tests/test_vicinity_help.py tests/test_global_help.py -v
python3 -m pytest tests/ -q
```

---

## Out of scope

S7 proactive PredictAndDecide on this same allocate path. Paper load–distance. Cross-MS cascade.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v2 | 2026-08-20 | Reclaim stamps `beg_terminate` / `vicinity_terminate` / `beh_terminate` |
| v1 | 2026-08-15 | Global→vicinity→local reclaim; cascade-home with flag |
