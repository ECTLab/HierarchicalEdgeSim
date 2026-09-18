# μ-matched CPU/RAM scale

**Status:** landed on `code-review`  
**Date:** 2026-08-20  
**Proof run:** `results/06-triangle-beg-era/full_ladder/42_20260820T115435Z`  
**Related:** [17-surplus-down-resource-quantum-and-seed-log.md](./17-surplus-down-resource-quantum-and-seed-log.md) (v3), [19-triangle-ladder-scenarios.md](./19-triangle-ladder-scenarios.md), [08-reactive-local-params.md](./08-reactive-local-params.md)

Physics already said serving capacity is

\[
\mu = \min\!\bigl((A_{\mathrm{cpu}}-\mathrm{cpu_{min}})/\rho_{\mathrm{cpu}},\;(A_{\mathrm{ram}}-\mathrm{ram_{min}})/\rho_{\mathrm{ram}}\bigr).
\]

Floors buy no throughput. Extra RAM past \(\mathrm{ram_{min}}+\mu\cdot\rho_{\mathrm{ram}}\) does not serve more requests. Scale-up/down treated CPU and RAM as two leftover wallets anyway, so replicas grew fat RAM that \(\mu\) never used.

---

## Problem

`up_delta` converted dropped demand through \(\rho\) for **each** resource, then applied **that resource’s** rate cap:

```
Δ_cpu = min(max(D · ρ_cpu, δ_cpu_min), α_up · ΣA_cpu)
Δ_ram = min(max(D · ρ_ram, δ_ram_min), α_up · ΣA_ram)
```

On the triangle seed (`1.0` cores / `512` MB, `α_up=0.20`, `δ_ram_min=128`):

| Wallet | Bound | Value |
|---|---|---|
| CPU | `0.20 × 1.0` | 0.20 cores (20 req/tick) |
| RAM | `0.20 × 512` | **102.40 MB** (and `δ_ram_min` would have been 128) |

Packed spawn is floor + leftover, so the first remote replica was **0.70 / 358.40**. Later BEV-up walked RAM toward `ram_max` (512) even though CPU was already the binding resource. Peak serving μ on a full replica is 50 req/tick; that only needs \(256 + 50 \times 0.5 = 281\) MB.

Surplus-down then peeled the **same** \(\Delta\mu\) off both resources, starting from that fat RAM. CPU stopped at the hold (`0.58` cores, μ=8). RAM only came down by the same small μ steps, so leftover sat near **490 MB**. v2 skipped downs that did not cut μ, which correctly killed sub-MB RAM chatter — and also froze that idle RAM in place.

`ram_max: 512` in YAML is a ceiling, not a target. The scaler was using current alloc as a RAM growth budget.

---

## What we did

Size **one serving-μ step**, rate-limit it on the **CPU** wallet, convert both resources through \(\rho\). Do not floor RAM at `δ_ram_min` or cap it at `α_up · ΣA_ram` on the way up.

```
step_μ = min(max(D, δ_cpu_min / ρ_cpu), (α_up · ΣA_cpu) / ρ_cpu)
Δ_cpu = step_μ · ρ_cpu
Δ_ram = step_μ · ρ_ram
```

Same triangle leftover at τ=18 is now **10 MB**, packed spawn **0.70 / 266**. BEV-up grows RAM only if it would lag that μ (full replica **1.00 / 281**).

On the way down, each resource’s headroom is sized to \(\mu_{\mathrm{tgt}}\cdot\rho\) with \(\mu_{\mathrm{tgt}}=\Lambda/(1-\theta_{\mathrm{free}})\). Sub-MB RAM-only dust is still skipped. When CPU is already on the hold quantum, leftover RAM above \(\mathrm{ram_{min}}+\mu\cdot\rho_{\mathrm{ram}}\) is idle-trimmed in `δ_ram_min` chunks (last replica only). RAM leftover without CPU leftover does not spawn another replica.

Code: `src/hierarchical_edge_sim/autoscaler/common/mu_scale.py`, used from `reactive_local.allocate`, `distribute_up` / `distribute_down`, packed spawn (`beh.py` / `place.py`), `reactive_vertical`, and proactive `_clip_step`.

`δ_ram_min` is now an **idle-trim** chunk on the last replica, not a second grow floor. `α_up` is a CPU rate cap; RAM follows ρ for the same μ. See [08-reactive-local-params.md](./08-reactive-local-params.md).

This matches the simulator physics (floors buy no μ). It is closer to the proposed method’s “do not buy unused RAM” outcome than the dual-wallet pump was. The tex still sizes independent utilization residuals and seeds BEH at minima; lockstep \(\mu\cdot\rho\) is the env model, not a literal copy of `PredictAndDecide`.

---

## Triangle BEG log (`42_20260820T115435Z`)

Trace: Λ 40 → 180 by τ=200, 180 → 5 by τ=320, hold at 5. Conservation: **27 / 33412 dropped (0.08%)**, same order as the dual-wallet runs.

| τ | Action | Alloc |
|---|---|---|
| 0 | seed `c-api-0` | 1.00 / **512** (YAML start; not a scaler target) |
| 18 | `vicinity_spawn` | **0.70 / 266** |
| 47, 82 | `bev_up` on that replica | 0.95 / 278.50 then **1.00 / 281** |
| 82, 153 | `beg_spawn` | 0.70 / 266, then the same BEV walk to 1.00 / 281 |
| 257, 279, 302 | `beg_terminate` ×2, then `vicinity_terminate` | global loans first, then vicinity |
| 310–326 | `bev_down` on the seed | CPU 1.00 → 0.81 → 0.62 → **0.58**; RAM peels the CPU rate-cap pair (12.5 MB/tick) while load is still falling |
| 334, 342 | idle-trim RAM | 474.50 → 346.50 → **259.85** |
| 343–400 | hold | 0.58 / 259.85; usage 0.55 / 258.50 (`cpu_min + 5×ρ_cpu`, `ram_min + 5×ρ_ram`); no UP |

259.85 is \(\mathrm{ram_{min}} + \mu_{\mathrm{tgt}}\cdot\rho_{\mathrm{ram}}\) with \(\mu_{\mathrm{tgt}}=5/(1-0.35)\approx 7.69\). CPU 0.58 is the 0.01 quantum above that target (μ=8). No later resize onto `cpu_min`.

The other three triangle slices still have dual-wallet `actions.csv` until they are re-run.

---

## How to verify

```bash
python3 -m pytest tests/ -q
PYTHONPATH=src python3 examples/run_with_autoscaler.py configs/demo_400_triangle_beg.yaml
```

Look at the new `results/06-triangle-beg-era/full_ladder/<run_id>/actions.csv`: first extra **266** not 358; BEV-up RAM stops at **281**; leftover RAM **~260** not ~490.
