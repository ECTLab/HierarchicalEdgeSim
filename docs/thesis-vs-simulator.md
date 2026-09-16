# Thesis algorithms vs HierarchicalEdgeSim

**Status:** stale as of 2026-09-16 — the paper dropped the global rung and renamed Vertical / Horizontal / Vicinity. Current punch list: [tex-followups.md](./tex-followups.md).  
**Tex:** `proposed_method_complete.tex` (Summer 2026)  
**Code:** HierarchicalEdgeSim — `reactive_local` ladder plus `proactive_auto_scaler` front-end  
**Code:** current HierarchicalEdgeSim — `reactive_local` ladder plus `proactive_auto_scaler` front-end  
**Related:** [vicinity-partition.md](./vicinity-partition.md) · [cluster-manager-cycle.md](./cluster-manager-cycle.md) · [predict-and-decide.md](./predict-and-decide.md) · [allocate-resources.md](./allocate-resources.md) · [naming-refactor.md](./naming-refactor.md) · [s2-reactive-local-ladder.md](./s2-reactive-local-ladder.md) · [s3-ownership-bookkeeping.md](./s3-ownership-bookkeeping.md) · [s4-vicinity-help.md](./s4-vicinity-help.md) · [s5-global-help.md](./s5-global-help.md) · [s6-scale-down-reclaim.md](./s6-scale-down-reclaim.md) · [s7-proactive-front-end.md](./s7-proactive-front-end.md) · [s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md) · [mu-matched-cpu-ram-scale.md](./mu-matched-cpu-ram-scale.md) · [surplus-down-resource-quantum-and-seed-log.md](./surplus-down-resource-quantum-and-seed-log.md)

This note compares every named algorithm and clarification in the proposed-method tex with the simulator. It also lists places where the implementation is *more reasonable* than the algorithm (tex holes that showed up against this env’s serving model).

Primary code: `autoscaler/common/cm_cycle.py`, `autoscaler/reactive_local/allocate.py`, `autoscaler/proactive_auto_scaler/decide.py`, `env/api.py` (`request_worker_owner_scale`), `env/loans.py`, `env/root.py`, `env/partition.py`.

---

## Headline

The four-tier ladder from the tex **is implemented** and is what `reactive_local` (and the proactive front-end on top of it) actually runs:

```text
BEV → BEH → VicinityLeaderSchedule → BEG
```

Scale-down never enters the vicinity or global tiers.

Several algorithms are **lite** relative to the tex, and a handful of control-path rules in the code are **more reasonable than the algorithms** because the tex never accounted for this simulator’s serving model.

| Count | Status | Meaning |
|---|---|---|
| 5 | Stronger than the tex | Same job, but the code closes a hole the algorithm omitted |
| 5 | Implemented lite | Same job; paper pieces stubbed |

**Implemented as specified (structure):** VicinityPartitionAndLeaderElection at bootstrap, AllocateResources, reusable BEV/BEH, loan registry, owner-mediated mutation, cost-ordered scale-down, CheckCascadingMigration, a vicinity-wide FCFS help round, and BEG outside the home vicinity.

**Implemented, but not the way the tex writes them:** PredictAndDecide, AllocateResources cooldown/step caps, BEV packing, BEH spawn sizing, FCFS, and BEG ranking. In these places the code is usually *stricter* than the algorithm, for reasons that showed up in real runs.

**Not implemented:** lender `Reserve` / `safe_j` (clarification 7), confidence \(\kappa\) / predictor ensemble, BEG’s expected-response-time gate, root application admission, periodic re-partition \(T_{\mathit{repart}}\), and leader heartbeat failover. Inter-cluster distance exists for Algorithm 1; BEG and the vicinity help round still do not rank by it.

That split matches what the project’s own stage docs already call “lite vs paper” (S4–S7). It is not a secret gap; it is an intentional sim cut, plus a set of physics fixes the tex never stated.

---

## Status legend

| Status | Meaning |
|---|---|
| **Stronger than tex** | Implementation fixes a hole the algorithm omitted (usually \(\mu=0\) / serving model) |
| **Matches tex** | Same control flow |
| **Implemented lite** | Same *job*; paper pieces stubbed (distance, Reserve, RPC, partition, …) |
| **Not implemented** | Named algorithm or equation is not in the codebase |

---

## Named algorithms

| Algorithm | Tex | Code | Status | What actually landed |
|---|---|---|---|---|
| VicinityPartitionAndLeaderElection | Alg. vicinity | `env/partition.py` | Implemented lite | Listing mapped at bootstrap from coords or `latency_ms`. YAML `vicinities:` remains an experiment override. No \(T_{\mathit{repart}}\), heartbeat, or RPCs. |
| ClusterManagerCycle | Alg. cmcycle | `autoscaler/common/cm_cycle.py` | Implemented lite | Per-cluster \(Q_c\) then one vicinity round + BEG in one hook. \(t_{det}=\tau\). No CM processes, barrier, or \(\Delta t_{plan}\). |
| PredictAndDecide | Alg. predict | `proactive_auto_scaler/decide.py` | Stronger than tex | Same Up/Down/None + sustained shape, but util/residual use serving headroom \(\sum(A-\min)\), not total alloc. No \(\kappa\) ensemble; TCN or persistence, not LSTM pool. Mapping: [predict-and-decide.md](./predict-and-decide.md). |
| AllocateResources | Alg. allocate | `reactive_local/allocate.py` | Stronger than tex | BEV → BEH → \(\rho\) for Up; Down never leaves home. Cooldown is success-gated (and proactive Up/Down is asymmetric), not `StartCooldown(H)` every window. Mapping: [allocate-resources.md](./allocate-resources.md). |
| BEV | Alg. bev | `common/distribute.py` | Stronger than tex | Hottest-first packing with \(\mu\)-matched CPU/RAM, skip \(\mu=0\) resizes, last-replica surplus floor. Borrowed Grow/Shrink goes through owner API at apply time. |
| BEH | Alg. beh | `reactive_local/beh.py` | Stronger than tex | Same host-then-free ranking and global→vicinity→local reclaim. Spawns above minima so \(\mu>0\). Never kills the last replica; extras die only if remaining \(\mu\) still covers \(\mu_{\text{tgt}}\). |
| CheckCascadingMigration | Alg. cascade | `reactive_local/cascade.py` | Stronger than tex | At most one borrowed replica home after local free ≥ minima. Extra `LAST_REPLICA` guard, pending-free snapshot, `cascade_home` flag. Still per-MS (tex prose vs algorithm). |
| RequestWorkerOwnerScale | Alg. owner | `env/api.py` `request_worker_owner_scale` | Implemented lite | Single writer + loan grant/rollback is real. No idempotency key, RPC timeout, or per-node lock (single-threaded tick substitutes). |
| VicinityLeaderSchedule | Alg. leader | `reactive_local/vicinity.py` | Implemented lite | One FCFS joint round per vicinity, non-home members only. No Reserve/`safe_j`, no distance ranking, no multi-\(k\) inner step. YAML member order. |
| BEG | Alg. beg | `reactive_local/beg.py` · `env/root.py` | Implemented lite | Outside \(V_{\text{home}}\), serialized, global loan. Rank by free CPU not \(L+\gamma\cdot d\). No retry bound \(B\), no lender forecast, no expected-RT gate. |

---

## Eight clarifications (C1–C8)

| # | Clarification | Status | In the simulator |
|---|---|---|---|
| C1 | App = set of MS types; decide per type | Matches tex | World model is apps → microservices → containers. Policy is per `ms_id`. |
| C2 | FCFS across MS sharing a cluster | Implemented lite | \(t_{det}=\tau\), then `ms_id`. Wall-clock detection times would collapse to that order in one tick. |
| C3 | RAM floor/ceiling on scale-out and scale-in | Stronger than tex | Env clamps min/max. Policy also matches RAM to serving \(\mu\) so `ram_max` is a ceiling, not a target. |
| C4 | Per-MS vector-valued worker state | Implemented lite | Replica lists with \(q\), alloc, free. Not the formal length-\(W\) \(\mathbf{h},\mathbf{a},\mathbf{q},\mathbf{e}\) vectors; one scaler for the whole world. |
| C5 | Reusable BEV / BEH blocks | Matches tex | Shared `distribute` + `beh`; both `reactive_local` and `proactive_auto_scaler` call the same ladder. |
| C6 | Worker-owner sole mutator of lent nodes | Implemented lite | Auth path exists. Local BEH does not prefer an already-lent worker for a second spawn (clarification 6’s “same worker” rule). |
| C7 | Lender protects own forecast before granting | Not implemented | Eq. reserve / `safe_j` are not in vicinity or BEG. Lenders offer raw free capacity. |
| C8 | Non-overlapping vicinities + leader joint round; simple BEG | Implemented lite | Partition: Algorithm 1 at bootstrap (or YAML override). Joint round and BEG exist in lite form. Leader id is metadata, not a second actor. |

---

## What “implemented” means in this repo

The tex assumes distributed cluster managers, RPCs, and a leader barrier. HierarchicalEdgeSim is one process and one after-tick hook. Inside that hook `cluster_manager_cycle` runs Algorithm 2:

1. Observe every microservice (cooldown countdown / streaks / PredictAndDecide or reactive pressure).
2. Per **owner cluster**: enqueue \(\Delta\neq\) None, sort \(Q_c\) by \((t_{det}, ms\_id)\) with \(t_{det}=\tau\), drain local **BEV then BEH**.
3. Leftover Up residual becomes a `HelpRequest` with that \(t_{det}\).
4. If `World.root` exists, **one FCFS vicinity round**, then **BEG** on clusters outside \(V_{\text{home}}\).
5. All mutations go through `Env.request_worker_owner_scale` at apply time.

So ClusterManagerCycle is **mapped**, not distributed. The ladder is still the one in the tex: BEV → BEH → VicinityLeaderSchedule → BEG, and Down never enters vicinity/global. See [cluster-manager-cycle.md](./cluster-manager-cycle.md).

There are three scaler names. Only the last two walk that ladder:

| Scaler | Role |
|---|---|
| `reactive_vertical` | BEV-only baseline (no spawn, no loans) |
| `reactive_local` | Full ladder, reactive signals |
| `proactive_auto_scaler` | PredictAndDecide (TCN or persistence) feeding the **same** `reactive_local.allocate` path |

---

## Algorithm-by-algorithm

### 1. VicinityPartitionAndLeaderElection — implemented at bootstrap

The tex replaces the old `VICINITY_THRESHOLD` with a densest-seed + \(z\)-score (or largest-gap) partition, cap \(m_{\max}\), and a capacity-first leader score \(\rho\).

That listing now runs in `env/partition.py` when every cluster has `coords` (or a complete `latency_ms` matrix). YAML `topology.vicinities` remains an override so triangle experiments can pin groups. There is still no request-path delay, no \(T_{\mathit{repart}}\), no join/leave, no heartbeat \(\Delta t_{hb}\). Two paper-silent edges are documented: \(|D|=1\) still takes the only neighbor, and an empty \(z\)-score cut stays a singleton seed.

How to tell coords from RTT, what to open after `run_env_only.py`, and sample `run_meta.yaml` excerpts (`demo_partition`, `demo_partition_latency`, `demo_60_two_clusters`) are in [vicinity-partition.md](./vicinity-partition.md).

The named leader is **metadata**. `schedule_vicinity_help` does not branch on `env.is_leader`. That is documented on purpose so triangle experiments can force BEH vs vicinity vs BEG. It is not the algorithm in the tex’s vicinity section.

### 2. ClusterManagerCycle — implemented at the tick (in-process)

The listing now lives in `cluster_manager_cycle` (`autoscaler/common/cm_cycle.py`): per-cluster \(Q_c\), local AllocateResources, then one vicinity round and BEG. How to tell the cycle ran (`autoscaler.cycle`), which demos to use, and sample `actions.csv` excerpts are in [cluster-manager-cycle.md](./cluster-manager-cycle.md).

Still not the tex’s distributed protocol:

- No CM process per cluster. One hook. Predictor history is per `ms_id`, not per \((m,c)\).
- \(t_{det}=\tau\). Inside a tick that is the same FCFS as sorted microservice id (clarification 2).
- No barrier wait \(\Delta t_{bar}\) and no plan timeout \(\Delta t_{plan}\). Apply is synchronous; unmet residual → BEG in the same tick.
- `InCooldown` in the tex skips the whole MS; the code still updates streaks every tick and only suppresses **emission**. That is better (see [Cooldown after a rejected window](#7-cooldown-after-a-rejected-window-freezes-a-stuck-ms) and [Streaks during cooldown](#8-streaks-during-cooldown)).

### 3. PredictAndDecide — implemented, formula changed on purpose

The **control shape** matches: ensemble slot → proactive vs reactive; Up if observed or any hat \(\ge \theta^{up}\); Down only if **both** observed and **all** hats \(\le \theta^{down}\); `sustained` if at least \(\tau\) forecast steps sit at/above \(\theta^{up}\) (that flag still skips BEV and goes to BEH).

What does **not** match:

| Tex | Code |
|---|---|
| \(u = \max_j q_{m,j}\) (hottest replica) | Fleet \(q_{ms}\) from serving headroom, plus drop pressure on the reactive path |
| \(\delta = A \tilde u / \theta_{\text{target}} - A\) | \(A_{\text{req}} = n\cdot\min + (\texttt{cpu\_per\_request} \cdot \texttt{peak\_rps} \cdot \text{tick\_sec}) / \theta_{\text{target}}\) using \(\texttt{headroom}=\sum(A-\min)\). Code `peak_rps` is not paper \(r^*\) (predictor index). |
| \(\kappa_r = 1/(1+\text{MAPE})\), pick \(r^*=\arg\max \kappa\), floor \(\kappa_{\min}\) | Cold start = reactive until history length \(W\); then **always** proactive. No MAPE, no ensemble |
| LSTM / Bi-LSTM / GRU / Bi-GRU / A-Bi-GRU | TCN-delta (Alibaba) or persistence (tests). The tex called the predictor a black box; this is a different family |

The residual change is the important one. The tex treats **total allocation** as serving capacity. In this env, floors buy **no** \(\mu\):

\[
\mu = \min\bigl((A_{\text{cpu}}-\text{cpu}_{\min})/\rho_{\text{cpu}},\;(A_{\text{ram}}-\text{ram}_{\min})/\rho_{\text{ram}}\bigr)
\]

Routing is CPU-headroom weighted, so a replica at `cpu_min` gets share 0. Using \(A\) in \(\delta\) made idle min-replicas look like spare capacity and made \(q\) look idle after a trough. The first Alibaba TCN run dropped **69%** of requests largely because decide / BEV-down / min-BEH disagreed with \(\mu\). After the headroom residual, packed spawns, and surplus-down, that fell to about **8%** (then lower with other cooldown experiments). That is not a coding convenience; it is a bug the algorithm does not mention.

See [s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md). How the listing is mapped (gate vs residual, what the tex should absorb, sample runs): [predict-and-decide.md](./predict-and-decide.md). Letter collisions (`r*` vs `peak_rps`): [naming-refactor.md](./naming-refactor.md).

### 4. AllocateResources — implemented, cooldown and step caps differ

Up: BEV (unless `sustained`) → BEH → leftover \(\rho\) for vicinity. Down: BEV/BEH only, then clamp; never escalate. That is exactly the tex’s “down cannot leave the home cluster.”

Differences: cooldown is **success-gated**; proactive cooldown is **down-only after an Up** (Kubernetes HPA-style), not `StartCooldown(m,c,H)` after every window. Rate caps \(\alpha_{up}/\alpha_{down}\) clip the tex residual to one step per tick so the ladder does not jump to \(A_{\text{req}}\) in one decision. Down with extra replicas skips BEV-shrink of the seed in the same tick as a terminate.

How the listing is mapped (what to keep in the sim, what the tex should absorb, \(\alpha\)/\(\delta\) discussion): [allocate-resources.md](./allocate-resources.md).

### 5. BEV — implemented, packing is stricter

Same job: vertical grow/shrink on existing replicas; skip BEV on a sustained Up; never go below MS minima or above MS max / server free.

Stricter / more reasonable than the tex:

- Rank is a weighted score (drop, util, room), not only \(q^{cpu}\) hottest-first.
- CPU and RAM move as **one serving-\(\mu\) step** through \(\rho\). The tex grows each resource independently up to \(cpu_m^{\max}/ram_m^{\max}\), which treated `ram_max` as a fill target. Extra RAM past \(\text{ram}_{\min}+\mu\cdot\rho_{\text{ram}}\) does not serve anyone.
- `alloc_serves` refuses a resize that would still have \(\mu=0\) (CPU above min, RAM at min — that replica **receives** CPU-weighted load and drops all of it).
- Scale-down uses a surplus toward \(\mu_{\text{tgt}}=\Lambda/(1-\theta_{\text{free}})\), and **does not BEV-shrink the seed in the same tick as a terminate**. The tex would shrink and kill extras together and leave \(\mu\) below remaining load.

Borrowed Grow/Shrink is not a separate RPC inside BEV. `distribute_up` emits `ResizeAction` on whichever replica is hottest, including borrowed ones; `apply_actions` then calls `request_worker_owner_scale`. Same single-writer rule, different call shape.

### 6. BEH — implemented, spawn/terminate rules are stricter

**Up ranking** matches the tex: already-hosting servers first, then free CPU, then id. Home cluster only; leftovers go to vicinity.

**Spawn size does not match, and that is a fix.** The tex seeds every new instance at \((cpu_m^{\min}, ram_m^{\min})\). The code uses `packed_spawn_size`: floor **plus leftover headroom**, and **skips** a server that can only fit the floor. Vicinity and BEG use the same packer (`place_packed_spawns`). A minima spawn under this routing model is a replica that does not take load until a later BEV — and if the worker is itself floor-sized, BEV can never grow it. That showed up as red spikes on the triangle QoS plot (91 drops from \(\mu=0\) remotes).

**Down reclaim order matches:** global loans (older `ts` first) → vicinity → local by coldest \(q\). Reasons are stamped `beg_terminate` / `vicinity_terminate` / `beh_terminate`. Unknown remotes are treated as global so they still die before local.

**Last replica:** the tex’s terminate loop has no “never the last” rule. `beh_down` stops at one live replica, and `Env.terminate` returns `LAST_REPLICA`. Extras are killed only if remaining \(\mu\) still covers \(\mu_{\text{tgt}}\). Floor extras that add no \(\mu\) still get a token so they can be reclaimed.

**Clarification 6 gap:** the tex’s eligibility mask \(e_m\) includes already-borrowed nodes, and the prose says a second ask should land on the **same lent worker**. Local BEH never looks at foreign servers. Extra borrowed capacity is a **new** vicinity/BEG grant, not a second instance on the existing loan. That is a real spec miss, not an improvement.

### 7. CheckCascadingMigration — implemented, with extra guards

Matches: after local free \(\ge\) minima, pull at most one leftover borrowed replica home; prefer global over vicinity; **does not** feed the migrate into the shrink residual \(r\).

More reasonable than the tex:

- Apply order is terminate → spawn. The code **keeps a remaining local replica** so `LAST_REPLICA` cannot reject the borrowed terminate. The tex’s spawn-then-terminate would fail that case.
- Pending actions are subtracted from free before choosing the home worker.
- `cascade_home` can be turned off (the triangle demo does this: pulling a BEG replica onto a 1-core home worker would crush the seed and restart Up/Down chatter).

Tex **prose** says freed room can help a *different* application. The **algorithm** is per-\(m\), and that is what the code runs. Cross-MS cascade is still future work. No distance \(d(c,\mathrm{owner}(j))\) when choosing which loan to pull; older `ts` then id.

Cascade-home still places at **minima** (the tick only proved floor room was freed). That is consistent with the packed-spawn lesson: don’t pack more than you just freed.

### 8. RequestWorkerOwnerScale — implemented lite

This is real and enforced:

- Actor must be the worker’s owning cluster, **or** hold a loan for \((actor, ms_id)\).
- Fresh spawn with `loan_tier` grants the loan, then spawns; **failed spawn drops the grant**.
- Last borrowed instance on that worker drops the loan.

Missing vs the tex: idempotency key, RPC timeout \(\Delta t_{rpc}\), per-node lock, cached Ack. A single-threaded tick is the lock. Direct `resize`/`spawn`/`terminate` still exist for tests and world setup; **policy** goes through the owner path.

### 9. VicinityLeaderSchedule — implemented lite

The **job** is there: one FCFS round per vicinity, member workers as a pool, non-home only, loans stamped `vicinity`, unresolved → BEG. Concurrent members cannot race for the same neighbor.

Lite vs tex:

- No \(\mathrm{Reserve}_{c'}\) / \(\mathrm{safe}_j\) (clarification 7). Raw free capacity.
- No \(d(c,\mathrm{owner}(j))\) ranking. YAML `members:` order, then free CPU.
- One packed replica per inner iteration, not batch \(k\) at minima.
- `seq` = leftover order among MS this tick, not leader-assigned receipt numbers (same order in one process).

### 10. BEG — implemented lite

The **job** is there: home vicinity is never a BEG candidate; root ranks outside clusters; serialize requests in the window; global loan; leftover → `NeedGlobalHelpAction` (`LogUnmetDemand`).

Lite vs tex:

- Rank is **most free CPU**, then cluster id — not \(L_{c'}+\gamma\cdot d(c,c')\). There is no distance matrix.
- Walks all legal clusters; no separate retry bound \(B\).
- No lender forecast reservation.
- No “does this improve expected response time vs not scaling?” gate.

---

## Where the code is more reasonable than the algorithm

These are not accidental drift. They showed up when a literal reading of the tex was run against the usage model \(\mu = \min((A-\min)/\rho)\) and CPU-headroom routing. The 69% Alibaba drop on the first TCN run is the existence proof.

| Issue the tex missed | What the algorithm says | What the code does | Why the code is more reasonable |
|---|---|---|---|
| Floors buy no throughput | PredictAndDecide treats total alloc \(A\) as serving capacity. BEH / vicinity / BEG seed new replicas at `cpu_min` / `ram_min`. | \(\mu = \min((A-\min)/\rho)\). `packed_spawn_size` places floor + leftover headroom and skips a worker that can only fit the floor. | A minima replica gets zero CPU-headroom routing weight, so it serves nothing until a later BEV. On a worker whose cap is the floor, that replica is permanently dead. Literal paper spawn produced the 69% Alibaba drop (\(\mu=0\) fleet). |
| Headroom residual, not \(A\cdot\tilde u/\theta - A\) | \(\delta = \max(0, A\cdot\tilde u/\theta_{\text{target}} - A)\). Floors inflate \(A\) without adding \(\mu\). | \(A_{\text{req}} = n\cdot\min + (\texttt{cpu\_per\_request} \cdot \texttt{peak\_rps} \cdot \text{tick\_sec}) / \theta_{\text{target}}\), using \(\texttt{headroom} = \sum(A-\min)\). Headroom \(\approx 0\) with load is treated as saturated (Up). | After a trough, idle min-replicas made \(q\) look idle and residual grew the wrong resource. Headroom matches the usage model. |
| \(\mu\)-matched CPU/RAM instead of two wallets | Independent \(\delta_{\text{cpu}}\) and \(\delta_{\text{ram}}\). BEV grows each up to `cpu_max` / `ram_max`. `ram_max` is treated like a fill target. | One serving-\(\mu\) step, rate-capped on the CPU wallet, both resources via \(\rho\). BEV-up will not apply a resize that still has \(\mu=0\). | Independent wallets pumped RAM toward `ram_max` while CPU was already binding, then surplus-down left RAM-dead replicas that still attracted CPU-weighted routing and dropped everything. |
| Surplus scale-down and last-replica floor | BEH terminate walks \(J\) until residual \(\ge 0\). No last-replica rule. BEV shrinks to deployment minima. | \(\mu_{\text{tgt}} = \Lambda/(1-\theta_{\text{free}})\). Release only surplus. Never terminate the last replica. Skip BEV-shrink of the seed in the same tick as a terminate. Extras die only if remaining \(\mu\) still covers \(\mu_{\text{tgt}}\). | Literal shrink-to-minima walks the leftover seed onto \(\mu=0\), then routing still sends it load and the next ticks bounce Up. `Env.terminate` also refuses `LAST_REPLICA`. |
| Pending-action free snapshot | Vicinity/BEG read live free vectors. Two FCFS requests in one window can over-commit the same worker. | `snapshot_free` then `subtract_pending` (resize/spawn/terminate already queued this tick) before placing. | Single-threaded joint round still needs this; otherwise two MS leftovers pack the same last slot. |
| Loan grant rollback and apply order | Cascade: spawn local, then Terminate on borrowed; roll back spawn on Reject. Owner RPC has timeout/idempotency. | Apply order is terminate → resize → spawn. Cascade emits terminate+spawn and keeps a local replica so `LAST_REPLICA` cannot reject the borrowed kill. Failed foreign spawn drops the just-inserted loan. | Paper spawn-then-terminate would hit `LAST_REPLICA` if the borrowed replica was the only live one after a local kill. Rollback of a failed grant is specified; the sim actually does it. |
| Cooldown only after a successful apply | `StartCooldown(m,c,H)` after every AllocateResources call, even if every mutation was Reject. | `on_actions_applied` starts cooldown only if at least one resize/spawn/terminate succeeded. Streaks keep running on total reject so pressure can retry next tick. | Paper cooldown after a full-reject window would freeze a saturated MS until \(H\) elapses, with no capacity gained. |
| Resource quantum and seed lifecycle | Continuous reals; no mention of YAML-placed replicas in the action log. | `quantize_resource` to 0.01 at every alloc write. Seed spawn rows at \(\tau=0\) so `actions.csv` covers the replica’s whole life. | Unquantized floats caused RAM-dust `bev_down` chatter (CPU already on the hold quantum, RAM still moving 0.15 MB). |

Narrative for each of those eight:

### 1. Deployment minima are not serving capacity

The tex seeds BEH/vicinity/BEG at \((cpu_{\min}, ram_{\min})\) and uses total alloc \(A\) in utilization and residual. Under \(\mu=(A-\min)/\rho\) and CPU-headroom routing, that is a zero-throughput replica that may still attract load (RAM at min, CPU above min → share > 0, serve 0). Packed spawn + headroom residual + “refuse \(\mu=0\) resize” are the correct operationalization of “RAM is first-class” (C3), not a contradiction of it.

### 2. Independent CPU and RAM wallets over-provision RAM and create zombies

Tex \(\delta^{cpu}\) and \(\delta^{ram}\) are separate. Growing RAM toward `ram_max` while CPU is binding does not add \(\mu\). Later independent shrink can floor RAM and leave CPU headroom. The code sizes **one \(\mu\) step**, CPU-rate-capped, both resources through \(\rho\). Idle RAM above \(\text{ram}_{\min}+\mu\cdot\rho_{\text{ram}}\) is trimmed in \(\delta_{\text{ram min}}\) chunks on the last replica only.

See [mu-matched-cpu-ram-scale.md](./mu-matched-cpu-ram-scale.md).

### 3. Scale-down without a last-replica / surplus rule walks the seed onto \(\mu=0\)

The tex terminate loop stops when residual \(\ge 0\). Combined with BEV-to-minima, the leftover home replica sits on the floor, routing still sends it work, next ticks bounce Up. Surplus \(\mu_{\text{tgt}}=\Lambda/(1-\theta_{\text{free}})\), never kill the last replica, and “don’t shrink the seed in the same tick as a terminate” are the missing stopping conditions.

See [surplus-down-resource-quantum-and-seed-log.md](./surplus-down-resource-quantum-and-seed-log.md).

### 4. Cooldown after a rejected window freezes a stuck MS

Tex `StartCooldown` runs after every allocate. Code starts cooldown only if something actually applied. Streaks keep running so the next tick can retry. Proactive then went further: **don’t delay Up** after a success (HPA scaleUp window 0); only delay Down after an Up. That last part is a **policy choice** (Kubernetes-like), not a tex bugfix, but it is more reasonable for a predictor whose job is to grow *before* a spike.

See [s7-k8s-scale-cooldown.md](./s7-k8s-scale-cooldown.md).

### 5. Two help requests in one window can over-commit the same worker

Tex VicinityLeaderSchedule deducts from `safe_j` after each place, which would have been enough **if** `safe_j` existed. Without it, the lite scheduler still snapshots free and subtracts pending resize/spawn/terminate. Same idea, applied to raw free.

### 6. Cascade spawn-then-terminate races LAST_REPLICA

If the borrowed replica is the last live instance after a local kill, terminate is rejected. The code keeps a local replica and applies terminate first. Failed loan grants are rolled back (the tex specifies this; the sim actually does it).

### 7. Unquantized floats create infinite RAM-dust downs

Not in the tex at all. After CPU hits the 0.01 hold quantum, sub-MB RAM leftover kept emitting `bev_down`. Quantize at every alloc write; skip dust; still idle-trim RAM to \(\mu\cdot\rho\).

### 8. Streaks during cooldown

Tex `InCooldown` → `continue` (no observation). Code updates drop/slack streaks every tick and only gates emission. Otherwise a cooldown that covers a real spike would reset the streak to zero and delay the next Up.

---

## Paper pieces that are still missing or lite

| Gap | Tex anchor | Why it matters |
|---|---|---|
| Vicinity partition + capacity-first election | Alg. vicinity | Implemented at bootstrap from coords/`latency_ms`. YAML override for triangle experiments. No re-partition / heartbeat. |
| Lender Reserve / `safe_j` (C7) | Eq. reserve, Eq. safe, Alg. leader | Help uses raw free CPU/RAM. A lender can give away capacity it will need next window. |
| Confidence \(\kappa\) + predictor ensemble | Eq. confidence, Alg. predict | Cold start is reactive until history length \(W\). After that the run is fully proactive. No MAPE \(\kappa\), no LSTM/GRU pool. TCN-delta or persistence. |
| Inter-cluster distance | Alg. vicinity, Alg. leader, Alg. beg, Alg. cascade | Topology \(d(c,c')\) exists (coords or `latency_ms`) and feeds Algorithm 1. Vicinity help still walks published member order; BEG is free-CPU; cascade is global then vicinity then older `ts`. |
| BEG expected-response-time gate and retry bound \(B\) | Alg. beg | Walks all legal outside clusters. Always places if a packed replica fits. |
| Prefer already-lent worker for a second spawn (C6) | Clarification 6 + Alg. beh eligibility \(e_m\) | Local BEH stays in the home cluster. Extra borrowed capacity is a new vicinity/BEG grant, not a second instance on the existing loaned worker. |
| Root least-loaded admission | § Cloud layer | Initial placement is YAML. No live application admission at the root. |
| Leader heartbeat → skip vicinity, go to BEG | § Vicinity alg | Leader id is topology metadata. The scaler never branches on `env.is_leader`. |
| Burst / panic / SLA-reactive fallback | Ch. related + Ch. predictor | Documented as future work in the tex; not in the simulator either. |

---

## Sim-shaped adaptations (not bugs)

These are cuts that match a single-process simulator. They are not tex holes the way \(\mu=0\) spawn is.

### One process, one hook

The tex is distributed CMs plus a leader barrier. The sim keeps a single `on_tick_end` and emulates per-MS FCFS then one joint round. Deterministic, and enough to test the ladder. It is not a multi-agent protocol evaluation.

### YAML vicinities

HierarchicalEdgeSim uses **Algorithm 1** when cluster coords (or a complete RTT list) are in the config. Hand groups remain so experiments can force BEH vs vicinity vs BEG (the triangle configs). Periodic re-partition and heartbeat were left out on purpose. Env-only samples: [vicinity-partition.md](./vicinity-partition.md).

### Proactive cooldown vs StartCooldown(H)

After Alibaba, proactive scale-up is never delayed (HPA scaleUp window 0). Scale-down waits `cooldown_C` windows after an Up. Cold-start reactive still uses `cooldown_ticks` on any success.

### Cascade is per-MS

Tex prose says freed room can pull a **different** application home. Algorithm cascade is parameterized by \(m\), and that is what the code runs. Cross-MS cascade is still future work.

---

## Also not in the tex algorithms, and not in the code (correctly deferred)

The tex already labels these as future work; the sim did not sneak them in:

- Inter-microservice placement / affinity (C1 scope limit).
- Burst / panic / SLA-reactive hybrid (Ch. related).
- Proper leader hand-off (heartbeat currently “fall straight to BEG”).
- Root least-loaded **application admission** — placement is YAML-static.

Related-work ideas (Hypa burst mode, CoScal vertical-first correction as a *misprediction* patch) are not the S7 TCN path. Vertical-first **is** in the ladder, but as the cheap first rung, not as a forecast-error detector.

---

## How to talk about this in the thesis

Safe claims:

- The escalation ladder, ownership single-writer, RAM as a floor, FCFS help inside a vicinity, and global-then-vicinity-then-local reclaim are implemented and tested (`test_reactive_local`, `test_ownership`, `test_vicinity_help`, `test_global_help`, `test_scale_down_reclaim`, triangle BEG demo).
- Proactive PredictAndDecide sits in front of that same allocate path.

Claims to qualify or drop:

- You **can** claim Algorithm 1 (bootstrap partition + capacity-first election) when the world is built from coords/`latency_ms`. Still do **not** claim \(T_{\mathit{repart}}\), heartbeat failover, or distributed leader RPCs.
- You **can** claim Algorithm 2 (`ClusterManagerCycle`) as the per-cluster intent queue + local allocate + one vicinity round + BEG inside the tick hook. Still do **not** claim CM processes, a leader barrier, or \(\Delta t_{plan}\).
- You **can** claim Algorithm 3 (`PredictAndDecide`) as the Up/Down/None + `sustained` gate in front of that cycle. Still do **not** claim the tex residual \(A\tilde u/\theta-A\), hottest-replica \(u\), or \(\kappa\) ensemble. Residual is serving-headroom \(A_{\mathrm{req}}\). See [predict-and-decide.md](./predict-and-decide.md).
- You **can** claim Algorithm 4 (`AllocateResources`) as BEV → BEH → leftover \(\rho\) on Up only; Down never leaves home. Still do **not** claim `StartCooldown(H)` after every call, or applying the full residual in one tick. See [allocate-resources.md](./allocate-resources.md).
- Do **not** claim lender Reserve / \(\mathrm{safe}_j\).
- Do **not** claim \(\kappa\)-gated ensemble switching. Cold start is reactive-until-\(W\), then one model.
- Do **not** claim load–distance BEG. Say least-loaded (free CPU) among clusters outside \(V_{\text{home}}\).

For the \(\mu=0\) / headroom / last-replica rules, the honest framing is: **the algorithms specified resource floors but not a serving model.** Once \(\mu=(A-\min)/\rho\) and headroom routing are the physics, seeding at minima and shrinking to minima are bugs. The simulator made the method operational; those rules should probably move **into** a later draft of the algorithms rather than stay as “implementation details.”

If you want a next step, the highest-value tex updates would be: (1) packed spawn above minima, (2) residual from serving headroom, (3) last-replica + surplus down, (4) coupled CPU/RAM through \(\rho\), (5) success-gated cooldown and a per-window \(\alpha\)/\(\delta\) step on AllocateResources. The highest-value **code** remaining vs the current tex is Reserve/`safe_j` — only if you still want that as a thesis contribution rather than future work.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-22 | Written from the thesis-vs-simulator comparison (chat report + canvas tables) |
| v2 | 2026-08-26 | Algorithm 1 mapped at bootstrap (`env/partition.py`); YAML vicinities stay an override |
| v3 | 2026-08-26 | Pointer to vicinity-partition.md samples (coords vs `latency_ms`) |
| v4 | 2026-08-27 | Algorithm 2 mapped as in-process ClusterManagerCycle |
| v5 | 2026-08-27 | Pointer to cluster-manager-cycle.md demo checklist and samples |
| v6 | 2026-08-27 | Algorithm 3 mapped; pointer to predict-and-decide.md |
| v7 | 2026-08-27 | Algorithm 4 mapped; pointer to allocate-resources.md |
