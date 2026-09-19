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
| SchedulePlacements | Grow existing (local hosts before remote loans), then spawn; search all of \(N_V\) including \(N_{c'}\) so Phase 1 frees can recycle home; rank home, hosting, \(d\) ascending | `grow_existing_instances` then `place_packed_spawns` over `rank_placement_servers`. Home recycle is `horizontal_spawn` with no loan; remote is `vicinity_spawn`. Grow reason `vicinity_up`. Ceiling is `safe_j`. Spawn stays packed, not minima. |
| Owner(j) writer | Borrower cannot mutate a lent worker except as \(\rho\)/\(\xi\); owner applies the plan | `actor_cluster_id` must equal `owner(j)`. Borrower remote mutate is `NOT_AUTHORIZED`. Owner spawn of a foreign app records the loan. |
| CheckCascadingMigration | After \(m\) shrinks, at most one borrowed replica of a different \(m^*\) comes home; Evict via the leader | `check_cascading_migration` → packed local spawn + Evict \(\xi\). Never \(m\), never \(m^*\) already in \(R_V\). LAST_REPLICA stays. |
| Same-window FCFS | \(Q_c\) Decrease before Increase, then id | `intents.sort(key=(t_det, 0 if down else 1, ms_id))`. |
| Lender Reserve / \(safe_j\) | Leftover own \(\rho\) → \(\mathrm{Reserve}_c\) → \(safe_j\); leader never offers raw free | `member_safe_ceilings`. VicinityRound places against `safe_j`. Phase-1 releases raise remaining safe. |
| Predictor confidence \(\kappa\) | \(\kappa=0\) until \(W_\kappa\), else \(1/(1+\mathrm{MAPE})\); below \(\kappa_{\min}\) ignore hats | `CountConfidence` + `trust_forecast`. Predictor still runs every window. |
| Admission + partition | Least-loaded stamp; Algorithm 1 at init | `env/admission.py` + `build_world` once. YAML \(V\) remains an experiment override. Clusters/workers/\(V\) are static. |
| Per-window residual | AllocateResources applies \(\delta\) in one window | No \(\alpha_{up}/\alpha_{down}\). \(\delta_{\min}\) is still a dust/token floor, not a speed limit. |
| User delay | \(T=T_{\mathrm{net}}+\) M/M/1 sojourn; drops as \(T_{\mathrm{slo}}\); full-but-serving uses \(\rho=0.99\); mix p99 over offered load | `env/latency.py`. Logs `t_*_offered_sec`, `sla_miss_requests`, `t_wait_sec`. Plot `user_latency.png`. |

The paper’s §prototype still describes the older `edge_computing_thesis` repo (global tier, BEV/BEH names). Point that section at HierarchicalEdgeSim when you next edit the tex.

---

## Keep in the sim; absorb into the tex later

These are the cases where the simulator is the operational method.

1. **Packed spawn above minima.** Paper HorizontalScaling and SchedulePlacements seed at \((cpu_{\min},ram_{\min})\). Code uses `packed_spawn_size` (floor + leftover headroom; skip a worker that can only fit the floor). A minima replica has \(\mu=0\) and routing weight 0.

2. **Utilization and residual from serving headroom, not total \(A\).** Paper \(u=\lambda\gamma/A\) and \(\delta=\tilde\lambda\gamma/\theta_{\mathrm{target}}-A\). Code: \(A_{\mathrm{req}}=n\cdot\min+(\rho\cdot\mathrm{peak\_rps}\cdot\mathrm{tick\_sec})/\theta_{\mathrm{target}}\).

3. **μ-matched CPU/RAM.** Paper grows each wallet independently toward `cpu_max` / `ram_max`. Code takes one serving-\(\mu\) step through \(\rho\). `ram_max` is a ceiling, not a fill target.

4. **Headroom-weighted routing (absorbed into v2 tex as prefer-local).** Even LB plus minima spawn sends \(1/n\) of load to a \(\mu=0\) replica, which then drops it. Keep headroom weights inside each pool.

5. **Prefer-local util cap (not fill-to-μ).** Paper prefer-local fills home to \(\mu\), then leftover to loans. With M/M/1 that forces \(\rho=1\) on the home replica as soon as \(\Lambda\ge\mu_{\mathrm{home}}\), so sojourn hits \(T_{\mathrm{slo}}\) while borrowed replicas sit idle. Code: fill home to \(\theta_{\mathrm{route}}\cdot\mu\); spill to loans up to full remote \(\mu\); use the remaining home band only if loans are already full (no extra drops). \(\theta_{\mathrm{route}}\) is scaler `theta_high` when `reactive_local` / `reactive_vertical` is attached, else `sim.theta_route` (default \(1\) = old fill-to-\(\mu\)). Same-cluster fleets still split by \(\mu\)/headroom with no cap. Absorb into the tex prefer-local listing.

6. **Last-replica and surplus-down.** Paper terminate/shrink walks until residual \(\ge 0\), with no last-replica rule. Code: \(\mu_{\mathrm{tgt}}=\Lambda/(1-\theta_{\mathrm{free}})\), never kill the last replica, peel the extra we would reclaim before terminating it, and do not vertical-shrink keepers in the same tick as a terminate.

7. **Floor extras are fully releasable.** Paper ScheduleReleases terminates only when \(L\) covers a whole instance. A minima replica has \(\mu=0\), so the sim still terminates it when \(L>0\) even if \(L\) is smaller than the instance. Otherwise a leftover loan at the floor would sit forever while local headroom was the only surplus.

8. **Success-gated cooldown, but keep observing.** Paper now arms cooldown only if something applied (good) and still `continue`s PredictAndDecide during cooldown. Code updates streaks every tick and only suppresses emission. Proactive also uses HPA-style `cooldown_C` (never delay Up; delay Down after a successful Up).

9. **Resource quantum 0.01.** Not in the paper. Stops RAM-dust vertical-downs.

10. **No \(T_{\mathit{repart}}\).** Clusters, workers, and vicinities are static parameters of a run. Algorithm 1 (or the YAML override) runs once at world build. Drop the slow re-partition, join/leave drain, and straddling-loan two-step from the tex for this deployment.

---

## Still paper-ahead (next sim steps, not this file)

None of the remaining canvas “update the sim” rows. Leader heartbeat failover and distributed CM RPCs stay sim cuts, not paper-ahead work.

---

## Document history

| Date | Note |
|---|---|
| 2026-09-19 | Prefer-local util cap: home to \(\theta_{\mathrm{high}}\cdot\mu\), then loans, then leftover home band. Paper still fill-to-\(\mu\). |
| 2026-09-18 | Local extras: peel the extra we would reclaim before terminate; do not shrink keepers in the same tick as a terminate. |
| 2026-09-18 | Prefer-local routing and analytic offered delay (\(T_{\mathrm{net}}\) + M/M/1, drop as \(T_{\mathrm{slo}}\)). Absorbed into `proposed_method_complete.tex`. |
| 2026-09-17 | Removed \(\alpha_{up}/\alpha_{down}\). AllocateResources applies the window residual; streaks/cooldown/last-replica/safe_j remain. |
| 2026-09-16 | Remaining six paper-ahead rows: owner(j) writer, cross-MS cascade, Decrease-before-Increase, Reserve/\(safe_j\), \(\kappa\), static admission (no \(T_{\mathit{repart}}\)). |
| 2026-09-16 | SchedulePlacements matches Alg. place: grow existing (home then nearer loans, μ-matched), then packed spawn over all of \(N_V\) including home recycle after Phase 1. Distance ranking replaces YAML member order. Packed spawn stays. Ceiling is now \(safe_j\). |
| 2026-09-16 | VicinityRound matches the leader listing: every member reports (empty offers included), only \(\ell(V)\) computes \(\Pi\), ApplyVicinityPlan emits actions. Packed spawn stays. |
| 2026-09-16 | Borrowed scale-down matches the paper: Eq. split \(\xi\), local tiers on \(N_c\), ScheduleReleases farthest-first then shrink. Floor extras stay fully releasable. |
| 2026-09-16 | Started the align-sim-to-tex pass: dropped the global rung and renamed Vertical / Horizontal / Vicinity. Packed spawn and serving-headroom rules stay in the sim. |
