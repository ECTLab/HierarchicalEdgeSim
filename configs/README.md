# Configs catalog

Files are numbered by when the scenario **first appeared**. **Higher number = later.**
`00` is pinned (Part A `tiny` world). Open this file first.

| If you want… | Open |
|---|---|
| Current triangle (post paper-match) | `16`–`19` reactive, `22`–`25` proactive |
| Alibaba 2-MS vicinity (campaign 12) | `33` reactive, `34` persistence, `35` HPA, `36` ProScale, `37` TCN, `48`–`49` θ=0.75 |
| Alibaba 2-MS split owner (campaign 15) | `50` reactive, `51` persistence, `52` HPA, `53` ProScale, `54` TCN |
| Alibaba 4-MS vicinity (campaign 13) | `38` reactive, `39` persistence, `40` TCN, `41` HPA, `42` ProScale |
| Alibaba 8-MS vicinity (campaign 14) | `43` reactive, `44` persistence, `45` HPA, `46` ProScale, `47` TCN |
| Alibaba MS_588 eval (campaign 11) | `26`–`30` |
| Alibaba MS_588 (original S7 pair) | `12` reactive, `13` TCN |
| Alibaba MS_150 | `14` reactive, `15` TCN |
| 60-tick ladder smokes | `08`–`11` |
| How to run | [../docs/00-how-to-rerun-tests-and-graphs.md](../docs/00-how-to-rerun-tests-and-graphs.md) |
| Where outputs land | [../results/README.md](../results/README.md) |

Deleted historical names (`demo_400_triangle_beg.yaml`, `demo_60_global_help.yaml`) stay unnumbered in old notes on purpose.

---

## Chronological (1 → latest)

| # | File | What it is |
|---|---|---|
| 00 | `00-tiny.yaml` | Part A 5-tick reference world |
| 01 | `01-demo_60.yaml` | Single-container 60-tick env |
| 02 | `02-demo_60_two_containers.yaml` | Two replicas, env only |
| 03 | `03-demo_60_two_containers_reactive.yaml` | Same world, vertical scaler |
| 04 | `04-demo_60_two_clusters.yaml` | Two apps / two clusters (Algorithm 1 coords) |
| 05 | `05-demo_300_two_containers.yaml` | 300-tick static |
| 06 | `06-demo_300_two_containers_reactive.yaml` | 300-tick vertical |
| 07 | `07-demo_300_two_containers_reactive_local.yaml` | 300-tick local ladder |
| 08 | `08-demo_60_reactive_local.yaml` | 60-tick HorizontalScaling smoke |
| 09 | `09-demo_60_vicinity_help.yaml` | 60-tick VicinityRound smoke |
| 10 | `10-demo_60_unmet_demand.yaml` | 60-tick leftover → unmet |
| 11 | `11-demo_60_proactive.yaml` | 60-tick persistence smoke (no torch) |
| 12 | `12-demo_alibaba_reactive_local.yaml` | MS_588 reactive baseline |
| 13 | `13-demo_alibaba_proactive.yaml` | MS_588 TCN |
| 14 | `14-demo_alibaba_ms150_reactive_local.yaml` | MS_150 reactive baseline |
| 15 | `15-demo_alibaba_ms150_proactive.yaml` | MS_150 TCN |
| 16 | `16-demo_400_triangle.yaml` | Triangle: vicinity then unmet |
| 17 | `17-demo_400_triangle_horizontal.yaml` | Triangle: in-cluster extras |
| 18 | `18-demo_400_triangle_vicinity.yaml` | Triangle: fat neighbor |
| 19 | `19-demo_400_triangle_skip_neighbor.yaml` | Triangle: floor skip → unmet |
| 20 | `20-demo_partition.yaml` | Algorithm 1 from coords |
| 21 | `21-demo_partition_latency.yaml` | Algorithm 1 from RTT matrix |
| 22 | `22-demo_400_triangle_proactive.yaml` | Triangle 16, persistence |
| 23 | `23-demo_400_triangle_horizontal_proactive.yaml` | Triangle 17, persistence |
| 24 | `24-demo_400_triangle_vicinity_proactive.yaml` | Triangle 18, persistence |
| 25 | `25-demo_400_triangle_skip_neighbor_proactive.yaml` | Triangle 19, persistence |
| 26 | `26-demo_alibaba_ms588_horizontal_reactive.yaml` | MS_588 4×8, reactive |
| 27 | `27-demo_alibaba_ms588_horizontal_persistence.yaml` | MS_588 4×8, persistence |
| 28 | `28-demo_alibaba_ms588_horizontal_tcn.yaml` | MS_588 4×8, TCN |
| 29 | `29-demo_alibaba_ms588_vicinity_reactive.yaml` | MS_588 home+fat neighbor, reactive |
| 30 | `30-demo_alibaba_ms588_vicinity_tcn.yaml` | MS_588 home+fat neighbor, TCN |
| 31 | *(removed)* | 32+32 eight-MS reactive. Superseded by 43 |
| 32 | *(removed)* | 32+32 eight-MS persistence. Superseded by 44 |
| 33 | `33-demo_alibaba_2ms_vicinity_reactive.yaml` | MS_588 + MS_150, 16+32 vicinity, reactive (campaign 12) |
| 34 | `34-demo_alibaba_2ms_vicinity_persistence.yaml` | Same world, persistence (campaign 12) |
| 35 | `35-demo_alibaba_2ms_vicinity_hpa.yaml` | Same world, Kubernetes HPA home-only (campaign 12) |
| 36 | `36-demo_alibaba_2ms_vicinity_proscale.yaml` | Same world, ProScale-style SMA + greedy neighbor (campaign 12) |
| 37 | `37-demo_alibaba_2ms_vicinity_tcn.yaml` | Same world, per-MS residual TCN (campaign 12) |
| 38 | `38-demo_alibaba_4ms_vicinity_reactive.yaml` | Four Alibaba MS, 24+32 vicinity, reactive (campaign 13) |
| 39 | `39-demo_alibaba_4ms_vicinity_persistence.yaml` | Same world, persistence (campaign 13) |
| 40 | `40-demo_alibaba_4ms_vicinity_tcn.yaml` | Same world, per-MS residual TCN (campaign 13) |
| 41 | `41-demo_alibaba_4ms_vicinity_hpa.yaml` | Same world, Kubernetes HPA home-only (campaign 13) |
| 42 | `42-demo_alibaba_4ms_vicinity_proscale.yaml` | Same world, ProScale-style SMA + greedy neighbor (campaign 13) |
| 43 | `43-demo_alibaba_8ms_sized_reactive.yaml` | Eight Alibaba MS, 40+40 vicinity, reactive (campaign 14) |
| 44 | `44-demo_alibaba_8ms_sized_persistence.yaml` | Same world, persistence (campaign 14) |
| 45 | `45-demo_alibaba_8ms_sized_hpa.yaml` | Same world, Kubernetes HPA home-only (campaign 14) |
| 46 | `46-demo_alibaba_8ms_sized_proscale.yaml` | Same world, ProScale-style SMA + greedy neighbor (campaign 14) |
| 47 | `47-demo_alibaba_8ms_sized_tcn.yaml` | Same world, one residual TCN per microservice (campaign 14) |
| 48 | `48-demo_alibaba_2ms_vicinity_persistence_theta75.yaml` | Campaign 12 world, persistence, \(\theta_{\mathrm{target}}=0.75\) |
| 49 | `49-demo_alibaba_2ms_vicinity_tcn_theta75.yaml` | Campaign 12 world, per-MS TCN, \(\theta_{\mathrm{target}}=0.75\) |
| 50 | `50-demo_alibaba_2ms_split_owner_reactive.yaml` | ms588 owns c1, ms150 owns c2, spare c3, reactive (campaign 15) |
| 51 | `51-demo_alibaba_2ms_split_owner_persistence.yaml` | Same world, persistence (campaign 15) |
| 52 | `52-demo_alibaba_2ms_split_owner_hpa.yaml` | Same world, Kubernetes HPA home-only (campaign 15) |
| 53 | `53-demo_alibaba_2ms_split_owner_proscale.yaml` | Same world, ProScale-style SMA + greedy spare (campaign 15) |
| 54 | `54-demo_alibaba_2ms_split_owner_tcn.yaml` | Same world, per-MS TCN (campaign 15) |

---

## By topic

- **Env only:** 00–02, 04–05, 20–21
- **Vertical / local ladder:** 03, 06–10
- **Alibaba:** 12–15, **26–30**, **33–54**
- **Proactive:** 11, 13, 15, **22–25**, **27–28**, **30**, **34**, **37**, **39–40**, **44**, **47–49**, **51**, **54**
- **Current triangle:** **16–19** reactive, **22–25** proactive

A new scenario gets the next number (`55-…`). Do not renumber existing files when you edit them.

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/16-demo_400_triangle.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/22-demo_400_triangle_proactive.yaml
.venv/bin/python examples/compare_trace_vs_log.py "$RUN_DIR"
```
