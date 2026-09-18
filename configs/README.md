# Configs catalog

Files are numbered by when the scenario **first appeared**. **Higher number = later.**
`00` is pinned (Part A `tiny` world). Open this file first.

| If you want… | Open |
|---|---|
| Current triangle (post paper-match) | `16`–`19` |
| Alibaba MS_588 | `12` reactive, `13` TCN |
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

---

## By topic

- **Env only:** 00–02, 04–05, 20–21
- **Vertical / local ladder:** 03, 06–10
- **Proactive:** 11, 13, 15
- **Alibaba:** 12–15
- **Current triangle:** **16–19**

A new scenario gets the next number (`22-…`). Do not renumber existing files when you edit them.

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/16-demo_400_triangle.yaml
.venv/bin/python examples/compare_trace_vs_log.py "$RUN_DIR"
```
