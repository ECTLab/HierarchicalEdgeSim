# Implementation and Evaluation Options

Decision notes for implementing and evaluating the hierarchical edge autoscaling method (BEV → BEH → BEVi → BEG, vicinity leaders, owner/borrower loans, proactive predictors).

The algorithm has requirements that not every platform satisfies out of the box:

| Requirement | Why it matters |
|---|---|
| Multi-cluster hierarchy (root / cluster manager / workers) | Core architecture |
| Non-overlapping vicinities + leader-mediated scheduling | Not standard HPA/CA behavior |
| Cross-cluster borrow with owner-mediated mutation | Needs custom control plane |
| Joint vertical + horizontal scaling with RAM/CPU floors | Beyond typical replica-only HPA |
| Per-microservice predictors + confidence switching | Needs a forecast hook |
| Controllable topology, latency matrix, workloads | Needed for repeatable experiments |
| Metrics: tail latency, cost, unmet demand, scaling churn | Thesis evaluation story |

This document compares options against those requirements, then recommends a pragmatic path for an MSc timeline.

---

## Evaluation criteria

Score each option roughly on:

1. **Fidelity** — how close results are to a real edge deployment  
2. **Expressiveness** — how easily we can implement *our* control logic (not just stock autoscaling)  
3. **Scale of experiments** — number of clusters/nodes/time windows we can sweep  
4. **Engineering cost** — person-months to a first paper-grade result  
5. **Reproducibility** — scripts, seeds, traces, CI-friendly runs  
6. **Publication credibility** — what reviewers typically accept for edge autoscaling papers  
7. **Risk** — chance of spending months on infra instead of the algorithm  

---

## Option 1 — Kubernetes (extend autoscaling, multi-cluster, real monitoring + ML)

### What it would look like
- Workers as nodes/Pods; microservices as Deployments/StatefulSets  
- Vertical scaling via VPA (or custom resource patching); horizontal via HPA/custom metrics  
- Multi-cluster via **Karmada**, **Open Cluster Management**, **Cluster API**, or federation-style control  
- Monitoring via Prometheus / Metrics Server / custom exporters  
- Predictors as sidecars or a central inference service consuming metrics history  

### Pros
- Highest **realism** and industry relevance  
- Real container lifecycle, scheduling, networking, and resource isolation  
- Strong story for “deployable system” in thesis/defense  
- Rich ecosystem for monitoring, tracing, and ML serving  

### Cons
- Stock HPA/VPA **do not** implement vicinity leaders, loan registries, or BEV→BEH→BEVi→BEG  
- True multi-cluster + cross-cluster borrow is a research project by itself  
- Hard to get clean, repeatable latency matrices across many geo-clusters on a student budget  
- Vertical + horizontal coordination is famously painful on stock Kubernetes  
- High ops load (cluster bring-up, networking, failures, version skew)  
- Slow experiment loops (minutes per scenario vs seconds in simulation)  

### Fit for our algorithm
Good as a **validation target**, weak as the *only* evaluation vehicle for an MSc unless scope is cut hard (e.g., 2–3 clusters on k3s, synthetic latency).

### Effort
**High** (often 4–8+ months to something paper-grade if starting from scratch).

---

## Option 2 — Docker Swarm

### What it would look like
Similar ambition to Kubernetes, but with Swarm services, nodes, and overlays; custom manager logic for scaling and vicinity offload.

### Pros
- Simpler than Kubernetes operationally  
- Still real containers and multi-node networking  
- Closer to the current [thesis prototype](https://github.com/Sky-himself/edge_computing_thesis) mental model (managers + workers)  

### Cons
- Much smaller ecosystem than Kubernetes (monitoring, multi-cluster, VPA-like tooling)  
- Multi-“cluster” Swarm is awkward; you mostly build the hierarchy yourself  
- Weaker publication signal than Kubernetes for systems reviewers  
- Same fundamental problem: **our policy is custom**, Swarm only gives you process placement  

### Fit for our algorithm
Slightly easier than full Kubernetes for a small real testbed, but you still own almost all of the novel control plane. Usually dominated by either (a) k3s/KubeEdge or (b) a simulator/custom testbed.

### Effort
**Medium–high**.

---

## Option 3 — Minimal custom testbed / simulator from scratch

### What it would look like
- “Containers” as threads/processes or lightweight objects with CPU/RAM budgets  
- Explicit config: `#clusters`, `#workers`, latency matrix, apps, microservice graphs  
- Discrete time windows implementing `algorithm.tex` literally  
- Workloads from synthetic generators or replayed traces (e.g., FIFA/World Cup style traces already used in the repo)  
- Essentially a domain-specific simulator owned by us  

### Pros
- **Best expressiveness**: every block (BEV, BEH, BEVi, leader schedule, loan registry) maps 1:1 to code  
- Fast sweeps over topology, thresholds, predictor accuracy, vicinity size  
- Full reproducibility and easy ablation studies  
- Aligns with how most edge autoscaling *algorithm* papers evaluate  
- Can evolve from the existing Flask/Compose prototype into a cleaner event-driven core  

### Cons
- Lower fidelity (no real kernel scheduling, container cold-start quirks, CNI behavior)  
- Reviewers may ask “does this work outside the simulator?”  
- You must implement (or approximate) network delay, queueing, and resource contention carefully — otherwise results are not credible  
- Easy to accidentally bake in assumptions that favor your method  

### Fit for our algorithm
**Strong primary vehicle** for algorithm correctness and comparative evaluation.

### Effort
**Medium** if scoped tightly; **low–medium** if built on the existing repo’s concepts.

---

## Option 4 — Existing simulators (CloudSim family, EdgeCloudSim, iFogSim2, PureEdgeSim, YAFS, …)

### Representative tools
| Tool | Language | Notes |
|---|---|---|
| **CloudSim / CloudSim Plus** | Java | Cloud VM-centric; edge needs extensions |
| **EdgeCloudSim** | Java | Edge + WLAN/WAN + mobility modules |
| **iFogSim / iFogSim2** | Java | Fog hierarchy, microservices, clustering, mobility |
| **PureEdgeSim** | Java | Large-scale heterogeneous edge, energy, location |
| **YAFS** | Python (SimPy) | Topology as graphs; custom placement policies; Python-friendly |
| **Fogify** | Python/Docker | Emulation-oriented fog testbed (closer to Option 6) |

### Pros
- Credibility: many peer-reviewed papers use these  
- Built-in models for network, mobility, energy, sometimes microservices  
- Faster than real multi-cluster infra for parameter sweeps  
- Avoid reinventing discrete-event plumbing  

### Cons
- Steep learning curve (especially Java CloudSim descendants)  
- Extending the control plane to match **vicinity leaders + owner/borrower loans + BEV/BEH** often means fighting the framework’s assumptions  
- Documentation/community quality varies; some projects move slowly  
- Python stack (YAFS) matches the team better than Java, but may lack features you want  
- Risk of spending weeks “fitting” the algorithm into the simulator’s API  

### Fit for our algorithm
Good if we pick **one** tool and only customize the orchestrator policy module. YAFS or iFogSim2 are the most plausible; raw CloudSim alone is usually too cloud-centric.

### Effort
**Medium–high** (framework tax + policy implementation).

---

## Option 5 — Existing GitHub repos as a base (similar to Option 3)

### What it would look like
Fork a research prototype that already has multi-tier edge nodes, request generators, and scaling hooks; replace the policy with ours.

Sources to consider:
- Our own repo: [Sky-himself/edge_computing_thesis](https://github.com/Sky-himself/edge_computing_thesis) (already hierarchical, vicinity offload, traces)  
- Edge autoscaling / Fogify examples  
- Academic artifacts linked from EdgeCloudSim / YAFS tutorials  
- k3s + custom operator demos (if hybrid with real containers)  

### Pros
- Saves bootstrap time (topology, metrics, logging, Docker Compose already exist)  
- Direct continuity with work already done for the thesis  
- Easier to show “before/after” against the repo’s current 3-tier baseline  

### Cons
- Inherited simplifications (fixed vicinity size, limited prediction, single-container apps, etc.) must be removed carefully  
- Code quality / abstraction boundaries may fight a clean `algorithm.tex` mapping  
- External repos may be abandoned or poorly documented  
- Licensing and citation obligations  

### Fit for our algorithm
**Best bootstrap** if we treat the existing thesis repo (or a cleaned rewrite of it) as the codebase, then harden it toward `algorithm.tex`.

### Effort
**Low–medium** relative to greenfield.

---

## Option 6 — Edge-native / lightweight Kubernetes (k3s, KubeEdge, OpenYurt, Karmada) *[missed]*

### What it would look like
Small real clusters (k3s) per “edge site,” optional KubeEdge for edge nodes, Karmada (or similar) for multi-cluster orchestration; custom controllers implement vicinity + loan logic.

### Pros
- More realistic than Swarm, less heavy than full kubeadm multi-cluster  
- Better thesis narrative than pure simulation alone  
- Can run on a lab of VMs/Raspberry Pis  

### Cons
- Still substantial control-plane engineering for *our* policy  
- Cross-cluster scheduling products optimize different problems than BEVi/BEG  
- Hardware and networking setup still costly  

### Fit
Strong **secondary validation** after simulation results are solid.

### Effort
**High** (but lower than enterprise multi-cluster Kubernetes).

---

## Option 7 — Network/container emulation (Containernet, Mininet, Fogify) *[missed]*

### What it would look like
Emulate latency/bandwidth between sites; run real or near-real containers on emulated topology; inject our orchestrator as a process talking to the emulated nodes.

### Pros
- Better network fidelity than pure discrete-event simulation  
- Still controllable and scriptable  
- Fogify specifically targets fog/edge experiment reproducibility  

### Cons
- Heavier than Option 3; fewer nodes than simulators  
- Emulation bugs and resource contention on the host machine  
- Still not full geo-distribution  

### Fit
Useful middle ground if reviewers care about network delay realism and we already have containerized services.

### Effort
**Medium–high**.

---

## Option 8 — Hybrid evaluation strategy *[missed, often best]*

### What it would look like
1. **Primary:** custom discrete-event / thread-budget simulator (Option 3/5) implementing `algorithm.tex` exactly  
2. **Baselines:** reactive HPA-like, local-only BEV/BEH, vicinity without leader, always-global, etc.  
3. **Secondary (optional):** small real testbed (Compose or 2–3× k3s) showing that decisions are executable and loans work  
4. **Predictors:** start with oracle / ARIMA / simple LSTM; confidence switching as in the paper; no need for SOTA ML  

### Pros
- Matches MSc time and publication norms for algorithm papers  
- Separates “does the policy work?” from “can we operate Kubernetes?”  
- Lets us claim realism without betting the thesis on multi-cluster infra  

### Cons
- Two environments to maintain (sim + small real)  
- Must carefully state what is simulated vs measured  

### Fit
**Recommended default** for this project.

### Effort
**Medium** overall; staged deliverables.

---

## Option 9 — Pure analytical / queueing evaluation only *[missed, insufficient alone]*

### What it would look like
Use the M/M/1 / tail-latency model from `auto-scaling.tex` to compare configurations without a system prototype.

### Pros
- Fast; ties directly to the formulation  
- Good for upper bounds / sanity checks  

### Cons
- Cannot capture vicinity leader packing, fragmentation, RPC rejects, cooldown thrash  
- Weak as the sole evaluation for a systems-flavored method  

### Fit
Use as a **complement**, not the main evaluation.

---

## Comparative summary

| Option | Fidelity | Expressiveness | Exp. scale | Eng. cost | Reproducibility | Credibility | Risk |
|---|---|---|---|---|---|---|---|
| 1. Kubernetes | ●●●●● | ●● | ●● | ●●●●● | ●●● | ●●●●● | High |
| 2. Docker Swarm | ●●●● | ●●● | ●● | ●●●● | ●●● | ●●● | High |
| 3. Custom minimal sim | ●● | ●●●●● | ●●●●● | ●●● | ●●●●● | ●●●● | Medium |
| 4. Existing simulators | ●●● | ●●● | ●●●●● | ●●●● | ●●●● | ●●●●● | Medium–high |
| 5. Existing git base | ●●–●●●● | ●●●● | ●●●● | ●● | ●●●● | ●●●● | Low–medium |
| 6. k3s / KubeEdge / Karmada | ●●●●● | ●●● | ●●● | ●●●●● | ●●● | ●●●●● | High |
| 7. Emulation (Fogify/Containernet) | ●●●● | ●●●● | ●●● | ●●●● | ●●●● | ●●●● | Medium–high |
| 8. Hybrid (sim primary + small real) | ●●●● | ●●●●● | ●●●●● | ●●● | ●●●●● | ●●●●● | Low–medium |
| 9. Analytical only | ● | ●●● | ●●●●● | ● | ●●●●● | ●● | High (as sole method) |

---

## Recommendation for this thesis

### Preferred path: Option 8, grounded on Option 5 → Option 3

1. **Harden the existing thesis repo** into a clean discrete-window simulator that implements the refined `algorithm.tex` blocks (vectors, BEV/BEH, vicinity leader, loan registry, BEG).  
2. **Keep containers optional**: thread/process resource budgets are enough for algorithm evaluation; Docker Compose remains a demo/smoke layer.  
3. **Predictors:** start with trace-driven + simple models + confidence switching; treat “real ML ops” as optional polish, not a blocker.  
4. **Baselines** (minimum set):  
   - Reactive local-only (threshold HPA-like)  
   - Proactive local-only (BEV+BEH, no vicinity/global)  
   - Vicinity pairwise / no leader (ablate leader)  
   - Always escalate to global / random remote  
5. **Optional realism bump:** 2–3 k3s clusters or Compose sites with injected latency (tc/netem) to show loans and owner RPCs work outside the sim.  
6. **Avoid** betting the thesis on full Kubernetes multi-cluster or on deep forks of Java CloudSim unless there is spare time after core results.

### When to choose something else
- Advisor/reviewers demand “real orchestrator” evidence → add Option 6 as Phase 2, keep sim as Phase 1.  
- Team is already strong in Java CloudSim → Option 4 (iFogSim2 / PureEdgeSim) can replace the custom sim, but budget time for framework adapters.  
- Strong networking claims (WAN contention, accurate RTT) → add Option 7 for a subset of scenarios.

---

## Suggested experiment matrix (independent of platform)

Once a platform is chosen, evaluate at least:

| Axis | Example levels |
|---|---|
| Topology | 6 / 12 / 24 workers; vicinity sizes 3–5 |
| Workload | steady, bursty, spatial hotspot, FIFA-style traces |
| Predictor quality | oracle, good, noisy, cold-start reactive |
| Algorithm ablations | full ladder vs no BEVi vs no BEG vs no leader |
| Apps | 1 MS vs multi-MS application graphs |
| Metrics | p95/p99 latency, deployment cost, unmet demand, cross-cluster loans, decision latency, scaling churn |

---

## Custom simulator (pointer)

Environment modeling, entity design (servers / clusters / apps / containers), and how traces become CPU/RAM usage are documented separately:

→ **[02-custom-simulator-environment.md](./02-custom-simulator-environment.md)**

That doc also lists candidate base repos and a target package layout. This file stays focused on choosing among implementation/evaluation *options*.

---

## Open decisions to settle with the advisor

1. Is the thesis graded primarily as an **algorithm** contribution or a **systems** contribution?  
2. Is a small real testbed mandatory, or is a rigorous simulator enough?  
3. Do we need energy/mobility models (favors PureEdgeSim/iFogSim2), or is latency–cost under static geo-clusters enough?  
4. Maximum engineering budget before results must exist (e.g., 8–10 weeks)?  

Until those are fixed, **Option 8 (hybrid) with the existing repo as base** is the lowest-risk way to evaluate the proposed algorithm without diluting the novelty into infrastructure work.
