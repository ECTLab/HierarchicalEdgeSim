# S7 — Proactive front-end on the completed ladder

**Status:** done (Option A TCN) + control-path fixes vs the 69% Alibaba drop  
**Branch:** `proactive-integration`  
**Roadmap:** [proposed-implementation-roadmap.md](./proposed-implementation-roadmap.md) §3 S7  
**Depends on:** [s6-scale-down-reclaim.md](./s6-scale-down-reclaim.md)  
**Alibaba diagnosis:** [s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md)  
**Cooldown (K8s-style, no 55-minute hold):** [s7-k8s-scale-cooldown.md](./s7-k8s-scale-cooldown.md)  
**Names vs paper letters:** [naming-refactor.md](./naming-refactor.md)

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
| Window | `ticks_per_window=1` for TCN (one Alibaba minute per sample) |

Option B (univariate one-step + recursive roll) remains only as the persistence / unit-test path.

Inference reconstructs absolute normalized load as `last_known + delta`, then denormalizes with the training min–max stored in `meta.json`.

---

## Pipeline

```text
each tick: accumulate λ_in
window close (every ticks_per_window ticks):
  observed_rps = N / (L · tick_sec)
  append N to history
  if history < W:  reactive streaks → ladder   # cold start
  else:
    forecast_rps = TCN(60×2) → 5 RPS hats
    PredictAndDecide(observed_rps, forecast_rps, headroom=Σ(A−min), cpu_per_request)
      → (Δ, δ_cpu, δ_ram, sustained)
    same ladder as S2–S6
```

Decide maps RPS to utilization with `rps_capacity = (headroom / cpu_per_request) / tick_sec` where `headroom = Σ(A − min)` (floors buy no μ). Headroom ≈ 0 and `observed_rps > 0` is treated as saturated (Up). Residual is `A_req = n·min + (cpu_per_request · peak_rps · tick_sec) / θ_target`. Proactive BEV-down will not pin the last serving replica onto a floor, and will not leave any replica at `μ = 0` with CPU headroom (routing would send it load it cannot serve). Then:

- **Up** if `u_obs ≥ θ_up` or any `û ≥ θ_up`
- **Down** if both observed and all hats are `≤ θ_down`
- else **None**

Decide residual is the gap from current alloc `A` to `A_req = n·min + (cpu_per_request · peak_rps · tick_sec) / θ_target`, where `peak_rps` is `max(observed_rps, hats)`. Apply clips that gap to one reactive-sized step (`α_up` / `α_down`). BEH packs that leftover above minima so the new replica can serve on the next tick (apply order is resize then spawn, so there is no same-tick BEV of a new id).

`sustained` is true when at least `sustained_steps` forecast steps sit at/above `θ_up` — that skips BEV and goes to BEH.

---

## What landed

| Piece | Role |
|---|---|
| `models/tcn_delta_v1/` | Copied weights + `meta.json` (MS_588 min/max, 60×2→5) |
| `models/tcn_delta_v1_ms150/` | Same weights; MS_150 min/max 240–40083 |
| `traces/alibaba/MS_588.csv` | 721 one-minute ticks from Alibaba v2021 |
| `traces/alibaba/MS_150.csv` | Same format; heavier, not 60-minute periodic |
| `predictors/tcn.py` | Option A loader (torch optional extra) |
| `configs/demo_alibaba_proactive.yaml` | TCN + Alibaba MS_588 world |
| `configs/demo_alibaba_reactive_local.yaml` | Same MS_588 world, reactive baseline |
| `configs/demo_alibaba_ms150_proactive.yaml` | TCN + Alibaba MS_150 transfer |
| `configs/demo_alibaba_ms150_reactive_local.yaml` | Same MS_150 world, reactive baseline |
| `configs/demo_60_proactive.yaml` | Torch-free persistence smoke |

YAML leftover keys after the decide block are `reactive_local` params (`x_up_streak`, `cascade_home`, …).

---

## Lite vs paper

- Global TCN from `alibaba-trace` (`tcn-only`), not a per-MS embedding and not LSTM.
- Training min–max is the full 12h series (same leakage as that repo).
- No vicinity `Reserve` / lender forecast (still S4 lite).
- Cooldown after a proactive **Up** is `cooldown_C` windows and delays **scale-down
  only** (Kubernetes HPA: scaleUp 0s, scaleDown 300s, then 100% per period).
  Scale-up follows the forecast immediately. Alibaba TCN uses `α_down = 1.0`.
  Cold-start reactive still uses `cooldown_ticks`.

The first Alibaba TCN run dropped 69% because decide / BEV-down / min-BEH disagreed with `μ`. Fixes and later numbers: [s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md). Why `hold_down_ticks` came out and how cooldown matches HPA: [s7-k8s-scale-cooldown.md](./s7-k8s-scale-cooldown.md).
