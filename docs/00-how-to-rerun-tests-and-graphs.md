# Re-run Tests and Generate Graphs

This guide shows how to:

1. run the test suite
2. run demo simulations (1 container, 2 containers, 2 clusters / 2 apps)
3. generate per-application analysis plots
4. read the `reactive_local` 60-tick figures against `08-demo_60_reactive_local.yaml` (§7)

Docs catalog: [README.md](./README.md) (higher number = later). Results catalog:
[../results/README.md](../results/README.md). Simulation outputs go under
`results/` and are **gitignored** except that catalog. Commit the configs,
traces, model weights, and the numbers in
[29-alibaba-tcn-s7-results.md](./29-alibaba-tcn-s7-results.md); regenerate plots
locally. Run ids are `{seed}_{UTC}`, so folder names will not match anyone
else’s machine.

---

## 1) Setup

```bash
# from the repository root (Python 3.14+; see pyproject.toml)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,plot]"
```

Add `.[tcn]` (torch) only for §B6. `.mplconfig/` is also gitignored; set
`MPLCONFIGDIR=$PWD/.mplconfig` if matplotlib cannot write a home cache.

---

## 2) Run tests

```bash
.venv/bin/pytest tests/ -v
```

---

## 3) Demo scenarios

### A) Single container

```bash
.venv/bin/python examples/run_env_only.py configs/01-demo_60.yaml
```

### B) Two containers, one app (heterogeneous routing)

```bash
.venv/bin/python examples/run_env_only.py configs/02-demo_60_two_containers.yaml
```

### B2) Same world with reactive vertical autoscaler (60-tick smoke)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/03-demo_60_two_containers_reactive.yaml
```

### B3) Long phased scenario (300 ticks) — static vs reactive

```bash
.venv/bin/python examples/run_env_only.py configs/05-demo_300_two_containers.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/06-demo_300_two_containers_reactive.yaml
# Compare dropped_requests in the two run dirs; reactive writes actions.csv
```

### B4) Long phased scenario — reactive_local (BEV then BEH)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/07-demo_300_two_containers_reactive_local.yaml
```

### B5) Same 60-tick local world — proactive persistence smoke (no torch)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/11-demo_60_proactive.yaml
```

### B6) Alibaba MS_588 — reactive_local vs Option A TCN

721 one-minute ticks (`tick_sec=60`), seed 42. This is the S7 claim: same
world, TCN vs `reactive_local`. Diagnosis:
[27-s7-proactive-drop-diagnosis.md](./27-s7-proactive-drop-diagnosis.md). Cooldown
(no 55-minute hold): [28-s7-k8s-scale-cooldown.md](./28-s7-k8s-scale-cooldown.md).
Recorded numbers: [29-alibaba-tcn-s7-results.md](./29-alibaba-tcn-s7-results.md).

Needs torch. Prefer the project extra; if that has no wheel for your Python,
use any interpreter where `import torch` works and put `$PWD/src:$PWD/examples`
on `PYTHONPATH`.

```bash
.venv/bin/pip install -e ".[dev,plot,tcn]"
export MPLCONFIGDIR=$PWD/.mplconfig

REACTIVE=$(.venv/bin/python examples/run_with_autoscaler.py configs/12-demo_alibaba_reactive_local.yaml | sed -n 's/^Run complete. Outputs written to: //p')
PROACTIVE=$(.venv/bin/python examples/run_with_autoscaler.py configs/13-demo_alibaba_proactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
.venv/bin/python examples/compare_trace_vs_log.py "$REACTIVE"
.venv/bin/python examples/compare_trace_vs_log.py "$PROACTIVE"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run reactive_local "$REACTIVE" \
  --run proactive_tcn "$PROACTIVE"
```

Outputs land in `results/04-alibaba-ms588/reactive_local/42_<UTC>/` and
`results/04-alibaba-ms588/proactive/42_<UTC>/`. The UTC stamp is new every run; do
**not** expect the folder names in the results doc. On current HEAD:

| | Drop rate | Incoming | Served | Dropped |
|---|---|---|---|---|
| `reactive_local` | **15.44%** | 3,385,510 | 2,862,823 | 522,687 |
| proactive TCN | **7.48%** | 3,385,510 | 3,132,439 | 253,071 |

After τ≥61: reactive **15.11%**, TCN **6.38%**. Conservation should hold
(trace = incoming = served + dropped). TCN BEV-downs are ~11 (one large cut
per valley, not the old 10% stairs).

`trace_vs_log_requests.png` is the conservation check. TCN plots shade τ=1…60
(no hats) and annotate drop rate after τ=61.

Overlay story plots: [31-alibaba-story-plots.md](./31-alibaba-story-plots.md).

The 69% → 3.79% rows in the results doc are historical (including hold-over-spike).
Do not commit `results/`.

### B8) Alibaba MS_588 evaluation (campaign 11)

Same trace, five configs: in-cluster reactive / persistence / TCN, plus a
vicinity split (home 8 cores, fat neighbor 24) so VicinityRound covers the
hourly spike. Details: [33-alibaba-ms588-eval.md](./33-alibaba-ms588-eval.md).

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig
.venv/bin/python examples/run_with_autoscaler.py configs/26-demo_alibaba_ms588_horizontal_reactive.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/27-demo_alibaba_ms588_horizontal_persistence.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/28-demo_alibaba_ms588_horizontal_tcn.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/29-demo_alibaba_ms588_vicinity_reactive.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/30-demo_alibaba_ms588_vicinity_tcn.yaml
# then compare_trace_vs_log.py on each run dir
```

### B7) Alibaba MS_150 — same world, transfer of the MS_588 controller

Same 4×8-core cluster, same initial `2.0 / 1024`, same TCN weights. Only the
trace and the per-MS min–max change (`models/tcn_delta_v1_ms150/`, 240–40083).
MS_150 is ~4.6× heavier than MS_588 and is not 60-minute periodic. Recorded
numbers: [30-alibaba-tcn-ms150-results.md](./30-alibaba-tcn-ms150-results.md).

`/usr/bin/python3` may not have torch. Put the interpreter that can
`import torch` on `PYTHONPATH` (this machine: the `alibaba-trace` venv
site-packages) together with `$PWD/src:$PWD/examples`.

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

REACTIVE=$(python3 examples/run_with_autoscaler.py configs/14-demo_alibaba_ms150_reactive_local.yaml | sed -n 's/^Run complete. Outputs written to: //p')
PROACTIVE=$(python3 examples/run_with_autoscaler.py configs/15-demo_alibaba_ms150_proactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
python3 examples/compare_trace_vs_log.py "$REACTIVE"
python3 examples/compare_trace_vs_log.py "$PROACTIVE"
python3 examples/compare_reactive_baseline.py \
  --run reactive_local "$REACTIVE" \
  --run proactive_tcn "$PROACTIVE" \
  --out "$PROACTIVE/analysis/baseline_comparison.png"
```

Outputs land in `results/05-alibaba-ms150/reactive_local/42_<UTC>/` and
`results/05-alibaba-ms150/proactive/42_<UTC>/`. On current HEAD:

| | Drop rate | Incoming | Served | Dropped |
|---|---|---|---|---|
| `reactive_local` | **5.51%** | 15,655,433 | 14,793,013 | 862,420 |
| proactive TCN | **4.71%** | 15,655,433 | 14,917,593 | 737,840 |

The first 60 ticks are identical (TCN cold-start is reactive). After TCN is
on (τ≥61), TCN drop is **0.49%** vs reactive **1.37%**.

### C) Two clusters, one app per cluster (this guide's focus)

```bash
.venv/bin/python examples/run_env_only.py configs/04-demo_60_two_clusters.yaml
```

Topology:

| Cluster | Servers | App | MS | Container |
|---|---|---|---|---|
| `c1` | 2 (`c1-w1`, `c1-w2`) | `web_app` | `api` | `c-web-api-1` on `c1-w1` |
| `c2` | 1 (`c2-w1`) | `media_app` | `ingest` | `c-media-ingest-1` on `c2-w1` |

Traces (both N=60):

- `traces/demo/api_60.csv`
- `traces/demo/ingest_60.csv`

Each command prints `<RUN_DIR>`, e.g. `results/02-env-60tick/two_clusters/42_YYYYMMDDTHHMMSSZ`.

This config now has cluster `coords` and **no** hand `vicinities:`. Algorithm 1 publishes one group `{c1,c2}` with leader `c1`. How to read that in `run_meta.yaml`, plus the five-site coords and RTT-matrix demos:

```bash
.venv/bin/python examples/run_env_only.py configs/20-demo_partition.yaml
.venv/bin/python examples/run_env_only.py configs/21-demo_partition_latency.yaml
```

See [21-vicinity-partition.md](./21-vicinity-partition.md) (coords vs latency, checklist, sample excerpts).

---

## 4) Analysis helper (modular)

Code lives under `examples/analysis/`:

```text
examples/analysis/
  io.py          # read traces / logs / actions / run_meta
  aggregate.py   # sum, align partial replica lives, site labels
  plots.py       # request / CPU / RAM + ladder QoS / replica-site / comparison
  report.py      # analyze_run(run_dir) orchestration
  compare.py     # labeled run-dir comparison
  __main__.py    # CLI entry
```

Thin wrapper (preferred):

```bash
.venv/bin/python examples/compare_trace_vs_log.py <RUN_DIR>
```

Optional: analyze only one app

```bash
.venv/bin/python examples/compare_trace_vs_log.py <RUN_DIR> --app web_app
```

### Output layout (per application)

```text
<RUN_DIR>/analysis/
  web_app/
    trace_vs_log_requests.png
    ladder_qos.png              # top: incoming + drops; bottom: sum CPU alloc; markers
    user_latency.png            # offered mean/p95/p99 (timeouts included) + SLA miss %
    replicas_by_site.png        # home / vicinity / global (or remote)
    c-web-api-1_cpu.png
    c-web-api-1_ram.png
  media_app/
    trace_vs_log_requests.png
    ladder_qos.png
    user_latency.png
    replicas_by_site.png
    c-media-ingest-1_cpu.png
    c-media-ingest-1_ram.png
```

For each app the requests plot checks:

- MS trace == sum(incoming) over that app's containers for that MS
- per container: incoming == served + dropped

---

## 5) One-command two-cluster flow

```bash
.venv/bin/pytest tests/ -q && \
RUN_DIR=$(.venv/bin/python examples/run_env_only.py configs/04-demo_60_two_clusters.yaml | sed -n 's/^Run complete. Outputs written to: //p') && \
.venv/bin/python examples/compare_trace_vs_log.py "$RUN_DIR"
```

---

## 6) Reactive ladder figures (before S7)

`compare_trace_vs_log.py` now also writes **ladder_qos.png** (incoming and drops on one request axis; sum CPU alloc on a panel below; vertical/horizontal/vicinity/cascade markers from `actions.csv`) and **replicas_by_site.png**. Terminated replicas are kept on disk so those series stay honest. Proactive runs also write **forecast_vs_actual.png** (trace vs t+1 / t+H hats).

### Ladder smoke configs

These 60-tick runs are also the Algorithm 2 check (`autoscaler.cycle: cluster_manager` in `run_meta.yaml`). What to open: [22-cluster-manager-cycle.md](./22-cluster-manager-cycle.md). They are also the Algorithm 4 check (`autoscaler.allocate: allocate_resources`): [25-allocate-resources.md](./25-allocate-resources.md). `11-demo_60_proactive.yaml` is also the Algorithm 3 check (`autoscaler.decide: predict_and_decide`): [24-predict-and-decide.md](./24-predict-and-decide.md).

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/08-demo_60_reactive_local.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/09-demo_60_vicinity_help.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/10-demo_60_unmet_demand.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/11-demo_60_proactive.yaml
# then: python examples/compare_trace_vs_log.py <RUN_DIR>
```

Those 60-tick traces climb/oscillate; they do **not** hold at a quiet Λ, so they
do not prove surplus reclaim. For that, use the four 400-tick triangle slices
(same load, four topologies). Why four, and what each must/must-not do:
[19-triangle-ladder-scenarios.md](./19-triangle-ladder-scenarios.md).

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/17-demo_400_triangle_horizontal.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/18-demo_400_triangle_vicinity.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/19-demo_400_triangle_skip_neighbor.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/16-demo_400_triangle.yaml
# then: python examples/compare_trace_vs_log.py <RUN_DIR>
```

Same four topologies with `proactive_auto_scaler` (persistence; `sim.theta_route: 0.80`). Results land under `results/10-triangle-proactive/`:

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/23-demo_400_triangle_horizontal_proactive.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/24-demo_400_triangle_vicinity_proactive.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/25-demo_400_triangle_skip_neighbor_proactive.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/22-demo_400_triangle_proactive.yaml
# then: python examples/compare_trace_vs_log.py <RUN_DIR>
```

### Same-trace comparison (off / vertical / local)

Use the 300-tick phased pair plus `07-demo_300_two_containers_reactive_local.yaml`:

```bash
OFF=$(.venv/bin/python examples/run_env_only.py configs/05-demo_300_two_containers.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VERT=$(.venv/bin/python examples/run_with_autoscaler.py configs/06-demo_300_two_containers_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
LOCAL=$(.venv/bin/python examples/run_with_autoscaler.py configs/07-demo_300_two_containers_reactive_local.yaml | sed -n 's/^Run complete. Outputs written to: //p')
.venv/bin/python examples/compare_reactive_baseline.py \
  --run off "$OFF" --run vertical "$VERT" --run local "$LOCAL"
```

Writes `baseline_comparison.png` under the first run’s `analysis/` (or `--out PATH`): dropped time series, live replica count, and a bar of whole-run total drops. Peak replicas stay on the time-series panel — they cannot share a bar axis with drop counts (hundreds of thousands vs a handful of replicas). When a proactive run is in the set, the first ``W`` ticks (lookback, no hats; first apply at τ=W+1) are grey on the time series.

S7 should reuse these two figure types (per-run ladder + labeled comparison) rather than a new plotting stack.

---

## 7) How to read the `reactive_local` 60-tick plots

Worked example: `configs/08-demo_60_reactive_local.yaml` → `results/08-ladder-60tick/reactive_local/<RUN_DIR>/analysis/demo_app/`.

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/08-demo_60_reactive_local.yaml
.venv/bin/python examples/compare_trace_vs_log.py <RUN_DIR>
```

### What this config is

Single cluster `c1`, two workers (`c1-w1`, `c1-w2`). One app / one MS (`demo_app` / `api`) on the 60-tick trace `traces/demo/api_60_two.csv`. Autoscaler is `reactive_local` (BEV then in-cluster BEH).

| Lock | Value |
|---|---|
| Initial replica | `c-api-1` on `c1-w1` at 1.0 core / 512 MB |
| MS bounds | `cpu_min` 0.5, `cpu_max` 2.0, `ram_min` 256 |
| Cost | `cpu_per_request` 0.01, `ram_per_request` 0.5 |
| Streaks | `x_up_streak` 3, `sustained_up_streak` 6, `y_down_streak` 8, `cooldown` 5 (glossary: [08-reactive-local-params.md](./08-reactive-local-params.md)) |

Serving capacity per replica is `μ = min((cpu_alloc − cpu_min) / 0.01, (ram_alloc − ram_min) / 0.5)`. CPU is the bottleneck. Routing fills home-cluster μ first, then leftover to loans; within a pool it is CPU-headroom weighted.

Actions are decided at the end of tick `τ` and apply on tick `τ+1`. Vertical lines on the plots mark the **decision** tick.

A representative run of this config had 8228 incoming, ~6630 served, ~1598 dropped (~19%). Trace vs sum(incoming) matched exactly. Those totals will move if the trace or params change; the *shapes* below should not.

### `ladder_qos.png` — did load overwhelm capacity?

Two stacked panels, shared time axis. Do **not** put requests and CPU cores on one axis: incoming is tens–hundreds of requests, sum CPU alloc is a few cores (here 1.0–3.6), so alloc would sit on the baseline.

- **Top (requests):** incoming and dropped on the same axis. The gap is served load. Drops track the three load peaks; they fall after the BEH spawn (`τ=19` in the worked run) and return on later peaks because the scaler is reactive.
- **Bottom (CPU cores):** sum of replica allocs as a step series. BEV is the small stairs; BEH is the jump when a new replica appears (1.73 → 2.5 when the spawn at `cpu_min` 0.5 becomes live). BEV-down is the later dip.

Marker families: `BEV up` / `BEV down` / `BEH spawn` / `BEH terminate` / vicinity / vicinity terminate / BEG / BEG terminate / cascade / escalate. A marker at `τ` and a step at `τ+1` is the apply delay, not a logging bug. Scale-in reasons follow the loan rung (`beg_terminate`, `vicinity_terminate`, `beh_terminate`); they are not all `beh_terminate`.

### `user_latency.png` — what delay does offered load see?

Analytic delay, not a request-level trace. Mean is demand-weighted; p95/p99 are the mix across replicas of offered load (if more than 1% timed out that tick, p99 is the timeout). Dropped requests are timeouts; a full replica that still served is not treated as 100% timeout.

### `trace_vs_log_requests.png` — is the env honest?

This is the physics check, not the scaler claim.

- Thick **trace** is the MS offered load. Analysis already asserts `trace == sum(incoming)` before this figure is written, so the plot does not draw a second “sum incoming” line.
- **sum served** + **sum dropped** = incoming. Served is the stepped ceiling from `μ`; each BEV resize raises the plateau.
- Per-replica incoming is on **routing_split.png**, not this figure. Those thin lines must add up to the trace. After BEH they will *not* each look like the trace.

On this config the new replica (`c-api-c1-w1-1`, spawned at `cpu_min`) stays at **0 incoming** until BEV gives it headroom (around `τ=35–40` in the worked run). Until then weighted routing sends everything to `c-api-1`. That is the model, not a missing container.

### `replicas_by_site.png` — did scale-out stay home?

Site labels: home / vicinity / global when `topology.vicinities` is set; home / **remote** when it is omitted (this config).

Counts are integers and drawn as steps. This demo never leaves the cluster, so home goes 1 → 2 at the first live tick of the spawn (`τ=20` after a BEH decision at `τ=19`) and remote stays 0. BEV markers do not change replica count; they only align the timeline with `ladder_qos.png`.

### `c-api-1_cpu.png` — original replica, vertical only

Usage is `min(alloc, cpu_min + served × 0.01)`. When usage sits on alloc, the replica is saturated and extra arrivals drop.

Alloc climbs 1.0 → 2.0 with BEV up and hits `cpu_max` (that is why BEH fires). Shrink waits for `y_down_streak` and `cooldown`, so a down step can land while load is already rising again. Y-axis starts at 0; alloc is a dashed step so it stays visible when usage is pinned to the ceiling.

### `c-api-c1-w1-1_cpu.png` — spawned replica

Same formulas; the series starts on the first live tick (`τ=20`). Flat 0.5 / 0.5 until the first BEV-up on this replica: spawn-at-min means `μ = 0`, so it cannot serve until alloc rises. Later stairs (0.54 → ~1.0 → ~1.4 → ~2.0) are leftover demand packed onto it. Usage catching alloc at the end is saturation again.

The id `c-api-c1-w1-1` means BEH packed onto `c1-w1` (still room under 8 cores). `c1-w2` stays empty in this run; that is placement, not a dropped log.

### `c-api-1_ram.png` and `c-api-c1-w1-1_ram.png`

Usage is `min(alloc, ram_min + served × 0.5)`. These plots *should* look over-provisioned: `μ_cpu ≪ μ_ram`, so BEV grows RAM in lockstep with CPU while usage stays near 270–330 MB on the original replica and on `ram_min` (256 MB) for the spawn until RAM is raised. The scaler is not RAM-driven here.

### What is not a plot bug on this config

| Looks wrong | Why it is expected |
|---|---|
| ~20% drops | Reactive + `cpu_max` 2.0 + new replica spawned at minima |
| New replica idle after BEH | Headroom 0 → no routed share until BEV |
| RAM unused | CPU is the serving bottleneck |
| `remote = 0` | In-cluster BEH; no vicinity block |
| Marker at `τ`, series change at `τ+1` | Apply-next-tick |
| BEV-down while load recovers | `y_down_streak` / cooldown hysteresis |
