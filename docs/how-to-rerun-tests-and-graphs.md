# Re-run Tests and Generate Graphs

This guide shows how to:

1. run the test suite
2. run demo simulations (1 container, 2 containers, 2 clusters / 2 apps)
3. generate per-application analysis plots
4. read the `reactive_local` 60-tick figures against `demo_60_reactive_local.yaml` (§7)

Simulation outputs go under `results/` and are **gitignored**. Commit the
configs, traces, model weights, and the numbers in
[alibaba-tcn-s7-results.md](./alibaba-tcn-s7-results.md); regenerate plots
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
.venv/bin/python examples/run_env_only.py configs/demo_60.yaml
```

### B) Two containers, one app (heterogeneous routing)

```bash
.venv/bin/python examples/run_env_only.py configs/demo_60_two_containers.yaml
```

### B2) Same world with reactive vertical autoscaler (60-tick smoke)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_60_two_containers_reactive.yaml
```

### B3) Long phased scenario (300 ticks) — static vs reactive

```bash
.venv/bin/python examples/run_env_only.py configs/demo_300_two_containers.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/demo_300_two_containers_reactive.yaml
# Compare dropped_requests in the two run dirs; reactive writes actions.csv
```

### B4) Long phased scenario — reactive_local (BEV then BEH)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_300_two_containers_reactive_local.yaml
```

### B5) Same 60-tick local world — proactive persistence smoke (no torch)

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_60_proactive.yaml
```

### B6) Alibaba MS_588 — reactive_local vs Option A TCN

721 one-minute ticks (`tick_sec=60`), seed 42. This is the S7 claim: same
world, TCN vs `reactive_local`. Diagnosis:
[s7-proactive-drop-diagnosis.md](./s7-proactive-drop-diagnosis.md). Cooldown
(no 55-minute hold): [s7-k8s-scale-cooldown.md](./s7-k8s-scale-cooldown.md).
Recorded numbers: [alibaba-tcn-s7-results.md](./alibaba-tcn-s7-results.md).

Needs torch. Prefer the project extra; if that has no wheel for your Python,
use any interpreter where `import torch` works and put `$PWD/src:$PWD/examples`
on `PYTHONPATH`.

```bash
.venv/bin/pip install -e ".[dev,plot,tcn]"
export MPLCONFIGDIR=$PWD/.mplconfig

REACTIVE=$(.venv/bin/python examples/run_with_autoscaler.py configs/demo_alibaba_reactive_local.yaml | sed -n 's/^Run complete. Outputs written to: //p')
PROACTIVE=$(.venv/bin/python examples/run_with_autoscaler.py configs/demo_alibaba_proactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
.venv/bin/python examples/compare_trace_vs_log.py "$REACTIVE"
.venv/bin/python examples/compare_trace_vs_log.py "$PROACTIVE"
.venv/bin/python examples/compare_reactive_baseline.py \
  --run reactive_local "$REACTIVE" \
  --run proactive_tcn "$PROACTIVE"
```

Outputs land in `results/alibaba_reactive_local/42_<UTC>/` and
`results/alibaba_proactive/42_<UTC>/`. The UTC stamp is new every run; do
**not** expect the folder names in the results doc. On current HEAD:

| | Drop rate | Incoming | Served | Dropped |
|---|---|---|---|---|
| `reactive_local` | **15.44%** | 3,385,510 | 2,862,823 | 522,687 |
| proactive TCN | **6.50%** | 3,385,510 | 3,165,404 | 220,106 |

After τ≥61: reactive **15.11%**, TCN **5.31%**. Conservation should hold
(trace = incoming = served + dropped). TCN BEV-downs are ~27 (not the old ~10
from `hold_down_ticks=55`).

`trace_vs_log_requests.png` is the conservation check. TCN plots shade τ=1…60
(no hats) and annotate drop rate after τ=61.

Overlay story plots: [alibaba-story-plots.md](./alibaba-story-plots.md).

The 69% → 3.79% rows in the results doc are historical (including hold-over-spike).
Do not commit `results/`.

### B7) Alibaba MS_150 — same world, transfer of the MS_588 controller

Same 4×8-core cluster, same initial `2.0 / 1024`, same TCN weights. Only the
trace and the per-MS min–max change (`models/tcn_delta_v1_ms150/`, 240–40083).
MS_150 is ~4.6× heavier than MS_588 and is not 60-minute periodic. Recorded
numbers: [alibaba-tcn-ms150-results.md](./alibaba-tcn-ms150-results.md).

`/usr/bin/python3` may not have torch. Put the interpreter that can
`import torch` on `PYTHONPATH` (this machine: the `alibaba-trace` venv
site-packages) together with `$PWD/src:$PWD/examples`.

```bash
export PYTHONPATH="/home/sky/alibaba-trace/.venv/lib/python3.12/site-packages:$PWD/src:$PWD/examples"
export MPLCONFIGDIR=$PWD/.mplconfig

REACTIVE=$(python3 examples/run_with_autoscaler.py configs/demo_alibaba_ms150_reactive_local.yaml | sed -n 's/^Run complete. Outputs written to: //p')
PROACTIVE=$(python3 examples/run_with_autoscaler.py configs/demo_alibaba_ms150_proactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
python3 examples/compare_trace_vs_log.py "$REACTIVE"
python3 examples/compare_trace_vs_log.py "$PROACTIVE"
python3 examples/compare_reactive_baseline.py \
  --run reactive_local "$REACTIVE" \
  --run proactive_tcn "$PROACTIVE" \
  --out "$PROACTIVE/analysis/baseline_comparison.png"
```

Outputs land in `results/alibaba_ms150_reactive_local/42_<UTC>/` and
`results/alibaba_ms150_proactive/42_<UTC>/`. On current HEAD:

| | Drop rate | Incoming | Served | Dropped |
|---|---|---|---|---|
| `reactive_local` | **5.51%** | 15,655,433 | 14,793,013 | 862,420 |
| proactive TCN | **4.40%** | 15,655,433 | 14,966,340 | 689,093 |

The first 60 ticks are identical (TCN cold-start is reactive). After TCN is
on (τ≥61), TCN drop is **0.14%** vs reactive **1.37%**. Removing
`hold_down_ticks` did not change this pair.

### C) Two clusters, one app per cluster (this guide's focus)

```bash
.venv/bin/python examples/run_env_only.py configs/demo_60_two_clusters.yaml
```

Topology:

| Cluster | Servers | App | MS | Container |
|---|---|---|---|---|
| `c1` | 2 (`c1-w1`, `c1-w2`) | `web_app` | `api` | `c-web-api-1` on `c1-w1` |
| `c2` | 1 (`c2-w1`) | `media_app` | `ingest` | `c-media-ingest-1` on `c2-w1` |

Traces (both N=60):

- `traces/demo/api_60.csv`
- `traces/demo/ingest_60.csv`

Each command prints `<RUN_DIR>`, e.g. `results/42_YYYYMMDDTHHMMSSZ`.

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
    replicas_by_site.png        # home / vicinity / global (or remote)
    c-web-api-1_cpu.png
    c-web-api-1_ram.png
  media_app/
    trace_vs_log_requests.png
    ladder_qos.png
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
RUN_DIR=$(.venv/bin/python examples/run_env_only.py configs/demo_60_two_clusters.yaml | sed -n 's/^Run complete. Outputs written to: //p') && \
.venv/bin/python examples/compare_trace_vs_log.py "$RUN_DIR"
```

---

## 6) Reactive ladder figures (before S7)

`compare_trace_vs_log.py` now also writes **ladder_qos.png** (incoming and drops on one request axis; sum CPU alloc on a panel below; BEV/BEH/vicinity/BEG/cascade markers from `actions.csv`) and **replicas_by_site.png**. Terminated replicas are kept on disk so those series stay honest.

### Ladder smoke configs

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_60_vicinity_help.yaml
.venv/bin/python examples/run_with_autoscaler.py configs/demo_60_global_help.yaml
# then: python examples/compare_trace_vs_log.py <RUN_DIR>
```

### Same-trace comparison (off / vertical / local)

Use the 300-tick phased pair plus `demo_300_two_containers_reactive_local.yaml`:

```bash
OFF=$(.venv/bin/python examples/run_env_only.py configs/demo_300_two_containers.yaml | sed -n 's/^Run complete. Outputs written to: //p')
VERT=$(.venv/bin/python examples/run_with_autoscaler.py configs/demo_300_two_containers_reactive.yaml | sed -n 's/^Run complete. Outputs written to: //p')
LOCAL=$(.venv/bin/python examples/run_with_autoscaler.py configs/demo_300_two_containers_reactive_local.yaml | sed -n 's/^Run complete. Outputs written to: //p')
.venv/bin/python examples/compare_reactive_baseline.py \
  --run off "$OFF" --run vertical "$VERT" --run local "$LOCAL"
```

Writes `baseline_comparison.png` under the first run’s `analysis/` (or `--out PATH`): dropped time series, live replica count, and bars for total drops / peak replicas / OK actions. When a TCN run is in the set, the first ``W`` ticks (lookback, no hats; first apply at τ=W+1) are grey, and the bar panel splits dropped load into τ≤W vs τ≥W+1.

S7 should reuse these two figure types (per-run ladder + labeled comparison) rather than a new plotting stack.

---

## 7) How to read the `reactive_local` 60-tick plots

Worked example: `configs/demo_60_reactive_local.yaml` → `results/reactive_local_60/<RUN_DIR>/analysis/demo_app/`.

```bash
.venv/bin/python examples/run_with_autoscaler.py configs/demo_60_reactive_local.yaml
.venv/bin/python examples/compare_trace_vs_log.py <RUN_DIR>
```

### What this config is

Single cluster `c1`, two workers (`c1-w1`, `c1-w2`). One app / one MS (`demo_app` / `api`) on the 60-tick trace `traces/demo/api_60_two.csv`. Autoscaler is `reactive_local` (BEV then in-cluster BEH).

| Lock | Value |
|---|---|
| Initial replica | `c-api-1` on `c1-w1` at 1.0 core / 512 MB |
| MS bounds | `cpu_min` 0.5, `cpu_max` 2.0, `ram_min` 256 |
| Cost | `cpu_per_request` 0.01, `ram_per_request` 0.5 |
| Streaks | `x_up_streak` 3, `sustained_up_streak` 6, `y_down_streak` 8, `cooldown` 5 |

Serving capacity per replica is `μ = min((cpu_alloc − cpu_min) / 0.01, (ram_alloc − ram_min) / 0.5)`. CPU is the bottleneck. Routing is CPU-headroom weighted: a replica at `cpu_min` has headroom 0 and receives no share until BEV grows it (equal-share only if *every* replica is at min).

Actions are decided at the end of tick `τ` and apply on tick `τ+1`. Vertical lines on the plots mark the **decision** tick.

A representative run of this config had 8228 incoming, ~6630 served, ~1598 dropped (~19%). Trace vs sum(incoming) matched exactly. Those totals will move if the trace or params change; the *shapes* below should not.

### `ladder_qos.png` — did load overwhelm capacity?

Two stacked panels, shared time axis. Do **not** put requests and CPU cores on one axis: incoming is tens–hundreds of requests, sum CPU alloc is a few cores (here 1.0–3.6), so alloc would sit on the baseline.

- **Top (requests):** incoming and dropped on the same axis. The gap is served load. Drops track the three load peaks; they fall after the BEH spawn (`τ=19` in the worked run) and return on later peaks because the scaler is reactive.
- **Bottom (CPU cores):** sum of replica allocs as a step series. BEV is the small stairs; BEH is the jump when a new replica appears (1.73 → 2.5 when the spawn at `cpu_min` 0.5 becomes live). BEV-down is the later dip.

Marker families: `BEV up` / `BEV down` / `BEH spawn` / `BEH terminate` / vicinity / BEG / cascade / escalate. A marker at `τ` and a step at `τ+1` is the apply delay, not a logging bug.

### `trace_vs_log_requests.png` — is the env honest?

This is the physics check, not the scaler claim.

- Thick **trace** under dashed **sum incoming** means the MS trace was fully offered (`trace == sum(incoming)`).
- **sum served** + **sum dropped** = incoming. Served is the stepped ceiling from `μ`; each BEV resize raises the plateau.
- Thin per-replica incoming lines are the **routing split**, not a second total. They must add up to sum incoming. After BEH they will *not* each look like the trace.

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
