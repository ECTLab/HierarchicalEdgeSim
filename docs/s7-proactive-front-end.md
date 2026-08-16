# S7 — Proactive front-end on the completed ladder

**Status:** done (Option A TCN)  
**Branch:** `ladder-based-implementation`  
**Roadmap:** [proposed-implementation-roadmap.md](./proposed-implementation-roadmap.md) §3 S7  
**Depends on:** [s6-scale-down-reclaim.md](./s6-scale-down-reclaim.md)

PredictAndDecide sits in front of the same AllocateResources path as `reactive_local` (BEV → BEH → vicinity → BEG, cost-ordered down + cascade). `reactive_local` stays the baseline scaler name.

---

## Locks

| Item | Choice |
|---|---|
| Predictor I/O | **Option A:** lookback `60×2` `[normalized_load, time_tick/720]` → 5-step **delta** |
| Default demo backend | `tcn_delta` (`models/tcn_delta_v1/`, weights from `alibaba-trace`) |
| Test / smoke backend | `persistence` (last sample, no torch) |
| Cold start | **reactive-only** until `W` real samples exist (`κ` blend is v2) |
| History purity | durable buffer holds observed request counts only |
| Sensing | container `lambda_in` only — no live trace reads |
| Allocate | `reactive_local.allocate` (same reasons: `bev_up`, `beh_spawn`, …) |
| TTW | `ttw_ticks=1` for TCN (one Alibaba minute per sample) |

Option B (univariate one-step + recursive roll) remains only as the persistence / unit-test path.

Inference reconstructs absolute normalized load as `last_known + delta`, then denormalizes with the training min–max stored in `meta.json`.

---

## Pipeline

```text
each tick: accumulate λ_in
TTW close:
  r_t = N / (L · tick_sec)
  append N to history
  if history < W:  reactive streaks → ladder   # cold start
  else:
    r̂ = TCN(60×2) → 5 RPS hats
    PredictAndDecide(r_t, r̂, A, ρ) → (Δ, δ_cpu, δ_ram, sustained)
    same ladder as S2–S6
```

Decide maps RPS to utilization with `C_full = (A / ρ) / tick_sec`, then:

- **Up** if `u_obs ≥ θ_up` or any `û ≥ θ_up`
- **Down** if both observed and all hats are `≤ θ_down`
- else **None**

Decide residual is the gap from current alloc `A` to `A_req = min + (ρ · r* · tick_sec) / θ_target`, where `r*` is `max(r_t, hats)`. Apply clips that gap to one reactive-sized step (`α_up` / `α_down`): lite BEH spawns at `cpu_min` (`μ=0` until BEV), so dumping the full `A_req` gap creates dozens of idle replicas.

`sustained` is true when at least `sustained_tau` forecast steps sit at/above `θ_up` — that skips BEV and goes to BEH.

---

## What landed

| Piece | Role |
|---|---|
| `models/tcn_delta_v1/` | Copied weights + `meta.json` (MS_588 min/max, 60×2→5) |
| `traces/alibaba/MS_588.csv` | 721 one-minute ticks from Alibaba v2021 |
| `predictors/tcn.py` | Option A loader (torch optional extra) |
| `configs/demo_alibaba_proactive.yaml` | TCN + Alibaba world |
| `configs/demo_alibaba_reactive_local.yaml` | Same world, reactive baseline |
| `configs/demo_60_proactive.yaml` | Torch-free persistence smoke |

YAML leftover keys after the decide block are `reactive_local` params (`x_up_streak`, `cascade_home`, …).

---

## Lite vs paper

- Global TCN from `alibaba-trace` (`tcn-only`), not a per-MS embedding and not LSTM.
- Training min–max is the full 12h series (same leakage as that repo).
- No vicinity `Reserve` / lender forecast (still S4 lite).
- Cooldown after a proactive apply is `cooldown_C` TTWs; cold-start reactive still uses `cooldown_ticks`.
