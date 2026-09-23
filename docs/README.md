# Docs catalog

Files are numbered by when the note **first appeared**. **Higher number = later.**
`00` is pinned at the top on purpose (how to run). Open this file first.

| If you want… | Open |
|---|---|
| How to run a demo and plot it | [00-how-to-rerun-tests-and-graphs.md](./00-how-to-rerun-tests-and-graphs.md) |
| Current paper-vs-sim punch list | [32-tex-followups.md](./32-tex-followups.md) |
| Current triangle results | [19-triangle-ladder-scenarios.md](./19-triangle-ladder-scenarios.md) |
| Alibaba recorded numbers (Aug 2026) | [29-alibaba-tcn-s7-results.md](./29-alibaba-tcn-s7-results.md), [30-alibaba-tcn-ms150-results.md](./30-alibaba-tcn-ms150-results.md) |
| MS_588 eval slices | [33-alibaba-ms588-eval.md](./33-alibaba-ms588-eval.md) |
| Two-MS Alibaba vicinity | [35-alibaba-2ms-eval.md](./35-alibaba-2ms-eval.md) |
| Eight-MS Alibaba vicinity | [34-alibaba-8ms-eval.md](./34-alibaba-8ms-eval.md) |
| YAML scenarios | [../configs/README.md](../configs/README.md) |
| Run folders on disk | [../results/README.md](../results/README.md) |

---

## Chronological (1 → latest)

| # | File | What it is |
|---|---|---|
| 00 | [00-how-to-rerun-tests-and-graphs.md](./00-how-to-rerun-tests-and-graphs.md) | Operator guide: tests, demos, plots |
| 01 | [01-implementation-evaluation-options.md](./01-implementation-evaluation-options.md) | Why a custom env vs existing simulators |
| 02 | [02-custom-simulator-environment.md](./02-custom-simulator-environment.md) | Environment design |
| 03 | [03-implementation-plan.md](./03-implementation-plan.md) | Part A plan |
| 04 | [04-part-a-implementation-steps.md](./04-part-a-implementation-steps.md) | Part A build steps |
| 05 | [05-extension-plan-root-and-vicinity.md](./05-extension-plan-root-and-vicinity.md) | Early root/vicinity plan |
| 06 | [06-autoscaler-plug-in-plan.md](./06-autoscaler-plug-in-plan.md) | Plug-in scaler plan |
| 07 | [07-autoscaler-implementation-steps.md](./07-autoscaler-implementation-steps.md) | Vertical scaler build steps |
| 08 | [08-reactive-local-params.md](./08-reactive-local-params.md) | Streak / θ / `min_mu_step` glossary |
| 09 | [09-proactive-autoscaler-approach.md](./09-proactive-autoscaler-approach.md) | Early proactive approach |
| 10 | [10-proposed-implementation-roadmap.md](./10-proposed-implementation-roadmap.md) | S1–S7 roadmap (Aug 11) |
| 11 | [11-s1-horizontal-mutation-apis.md](./11-s1-horizontal-mutation-apis.md) | S1 spawn/terminate |
| 12 | [12-s2-reactive-local-ladder.md](./12-s2-reactive-local-ladder.md) | S2 local ladder |
| 13 | [13-s3-ownership-bookkeeping.md](./13-s3-ownership-bookkeeping.md) | S3 loans / owner writer |
| 14 | [14-s4-vicinity-help.md](./14-s4-vicinity-help.md) | S4 VicinityRound |
| 15 | [15-s5-global-help.md](./15-s5-global-help.md) | S5 global rung (**removed**) |
| 16 | [16-s6-scale-down-reclaim.md](./16-s6-scale-down-reclaim.md) | S6 reclaim / cascade |
| 17 | [17-surplus-down-resource-quantum-and-seed-log.md](./17-surplus-down-resource-quantum-and-seed-log.md) | Surplus-down physics |
| 18 | [18-mu-matched-cpu-ram-scale.md](./18-mu-matched-cpu-ram-scale.md) | Coupled CPU/RAM through μ |
| 19 | [19-triangle-ladder-scenarios.md](./19-triangle-ladder-scenarios.md) | Triangle synthetics + current numbers |
| 20 | [20-thesis-vs-simulator.md](./20-thesis-vs-simulator.md) | Full paper comparison (**stale** Sep 16; use 32) |
| 21 | [21-vicinity-partition.md](./21-vicinity-partition.md) | Algorithm 1 partition |
| 22 | [22-cluster-manager-cycle.md](./22-cluster-manager-cycle.md) | Algorithm 2 cycle |
| 23 | [23-naming-refactor.md](./23-naming-refactor.md) | Letter collisions (`r*`, ρ, H) |
| 24 | [24-predict-and-decide.md](./24-predict-and-decide.md) | Algorithm 3 mapping |
| 25 | [25-allocate-resources.md](./25-allocate-resources.md) | Algorithm 4 mapping |
| 26 | [26-s7-proactive-front-end.md](./26-s7-proactive-front-end.md) | S7 TCN front-end |
| 27 | [27-s7-proactive-drop-diagnosis.md](./27-s7-proactive-drop-diagnosis.md) | Why the first TCN run dropped 69% |
| 28 | [28-s7-k8s-scale-cooldown.md](./28-s7-k8s-scale-cooldown.md) | HPA-style cooldown |
| 29 | [29-alibaba-tcn-s7-results.md](./29-alibaba-tcn-s7-results.md) | MS_588 recorded numbers |
| 30 | [30-alibaba-tcn-ms150-results.md](./30-alibaba-tcn-ms150-results.md) | MS_150 recorded numbers |
| 31 | [31-alibaba-story-plots.md](./31-alibaba-story-plots.md) | Overlay story plots |
| 32 | [32-tex-followups.md](./32-tex-followups.md) | **Latest** paper-match punch list |
| 33 | [33-alibaba-ms588-eval.md](./33-alibaba-ms588-eval.md) | MS_588 horizontal vs vicinity eval |
| 34 | [34-alibaba-8ms-eval.md](./34-alibaba-8ms-eval.md) | Eight Alibaba MS, vicinity, persistence (campaign 14) |
| 35 | [35-alibaba-2ms-eval.md](./35-alibaba-2ms-eval.md) | Two Alibaba MS (588+150), HPA, ProScale, ladder, persistence (campaign 12) |

---

## By topic

- **Environment:** 01, 02, 03, 04
- **Scaler plans:** 05, 06, 07, 08, 09, 10
- **Ladder stages:** 11–16
- **Serving-model fixes:** 17, 18
- **Algorithms 1–4:** 21, 22, 24, 25
- **Proactive / Alibaba:** 26–31, **33**, **34**, **35**
- **Paper match:** 20 (historical), **32** (current)
- **Experiments:** 00 (how to run), 19 (triangle), **33** (MS_588 eval), **35** (2-MS Alibaba), **34** (8-MS Alibaba)

New notes get the next number (`36-…`). Do not renumber existing files when you edit them.
