# Tex follow-ups

Living list of places where the **simulator is the operational method** and `proposed_method_complete.tex` should be updated later. The working rule: change the simulator to match the paper, except when a run showed the paper would mis-serve this env; those exceptions land here instead of being ported into the code.

This is not a full paper-vs-sim comparison. Use it as the punch list for the next tex draft.

---

## Already aligned (do not reverse in the sim)

| Item | Paper | Simulator now |
|---|---|---|
| No global / fourth tier | Ladder stops at VicinityRound; unmet demand is logged | `resolve_help` runs VicinityRound then `UnmetDemandAction`. No `beg.py`, no `loan_tier=global`. |
| Names | VerticalScaling, HorizontalScaling, VicinityRound | Action reasons `vertical_*`, `horizontal_*`, `vicinity_*`. Module `horizontal.py`. |
| Borrowed scale-down | Eq. split: \(L=\min(R,B)\) becomes \(\xi\); local tiers see only \(N_c\); ScheduleReleases farthest-first then shrink | `ReleaseIntent` + `schedule_releases`. Local `vertical_*` / `horizontal_*` on home replicas only. `vicinity_terminate` / `vicinity_down` from the vicinity round. |
| Vicinity leader | Only \(\ell(V)\) runs the body; barrier on all \(\lvert V\rvert\) reports including empty offers; broadcast \(\Pi\); members ApplyVicinityPlan | `VicinityReport` per member (empty Q/R is an offer). `env.is_leader` is the only cluster that calls `schedule_vicinity_plan`. `ApplyVicinityPlan` emits env actions. One-process stand-in: no RPC, barrier is “all local allocate finished”. |

The paper’s §prototype still describes the older `edge_computing_thesis` repo (global tier, BEV/BEH names). Point that section at HierarchicalEdgeSim when you next edit the tex.

---

## Keep in the sim; absorb into the tex later

These are the cases where the simulator is right and a literal reading of the current algorithms is not, under \(\mu=\min((A-\min)/\rho)\) and CPU-headroom routing.

1. **Packed spawn above minima.** Paper HorizontalScaling and SchedulePlacements seed at \((cpu_{\min},ram_{\min})\). Code uses `packed_spawn_size` (floor + leftover headroom; skip a worker that can only fit the floor). A minima replica has \(\mu=0\) and routing weight 0.

2. **Utilization and residual from serving headroom, not total \(A\).** Paper \(u=\lambda\gamma/A\) and \(\delta=\tilde\lambda\gamma/\theta_{\mathrm{target}}-A\). Code: \(A_{\mathrm{req}}=n\cdot\min+(\rho\cdot\mathrm{peak\_rps}\cdot\mathrm{tick\_sec})/\theta_{\mathrm{target}}\).

3. **μ-matched CPU/RAM.** Paper grows each wallet independently toward `cpu_max` / `ram_max`. Code takes one serving-\(\mu\) step through \(\rho\). `ram_max` is a ceiling, not a fill target.

4. **Headroom-weighted routing.** Paper assumes even spread of \(\lambda_m\) (no hot/cold). Code weights by CPU headroom. Even LB plus minima spawn sends \(1/n\) of load to a \(\mu=0\) replica, which then drops it.

5. **Last-replica and surplus-down.** Paper terminate/shrink walks until residual \(\ge 0\), with no last-replica rule. Code: \(\mu_{\mathrm{tgt}}=\Lambda/(1-\theta_{\mathrm{free}})\), never kill the last replica, do not vertical-shrink the seed in the same tick as a terminate.

6. **Floor extras are fully releasable.** Paper ScheduleReleases terminates only when \(L\) covers a whole instance. A minima replica has \(\mu=0\), so the sim still terminates it when \(L>0\) even if \(L\) is smaller than the instance. Otherwise a leftover loan at the floor would sit forever while local headroom was the only surplus.

7. **Success-gated cooldown, but keep observing.** Paper now arms cooldown only if something applied (good) and still `continue`s PredictAndDecide during cooldown. Code updates streaks every tick and only suppresses emission. Proactive also uses HPA-style `cooldown_C` (never delay Up; delay Down after a successful Up).

8. **Per-window \(\alpha/\delta\) step caps.** Paper may apply the full residual in one window. Code clips with \(\alpha_{\mathrm{up}}/\alpha_{\mathrm{down}}\).

9. **Resource quantum 0.01.** Not in the paper. Stops RAM-dust vertical-downs.

---

## Still paper-ahead (next sim steps, not this file)

Do **not** treat these as tex bugs. They are paper designs the simulator has not implemented yet:

- `Reserve` / `safe_j`
- Confidence \(\kappa\) / MAPE
- Decrease-before-Increase in \(Q_c\)
- Cross-MS cascade via Evict
- Grow-existing and distance ranking inside VicinityRound placements
- Periodic re-partition \(T_{\mathit{repart}}\) and root admission

---

## Document history

| Date | Note |
|---|---|
| 2026-09-16 | VicinityRound matches the leader listing: every member reports (empty offers included), only \(\ell(V)\) computes \(\Pi\), ApplyVicinityPlan emits actions. Grow / \(safe_j\) / home recycle still paper-ahead. Packed spawn stays. |
| 2026-09-16 | Borrowed scale-down matches the paper: Eq. split \(\xi\), local tiers on \(N_c\), ScheduleReleases farthest-first then shrink. Floor extras stay fully releasable. |
| 2026-09-16 | Started the align-sim-to-tex pass: dropped the global rung and renamed Vertical / Horizontal / Vicinity. Packed spawn and serving-headroom rules stay in the sim. |
