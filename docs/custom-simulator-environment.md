# Custom Simulator — Environment Design

High-level design for an in-process edge autoscaling simulator. This document focuses on **how we model the world** (servers, clusters, applications, containers, workloads, metrics). Autoscaling policy details are out of scope here; see `algorithm.tex` and the options doc for that.

Related: [implementation-evaluation-options.md](./implementation-evaluation-options.md) · [implementation-plan.md](./implementation-plan.md) (BSP phases, modules, milestones) · candidate bases at the end of this file / in the plan.


---

## 1. What we are simulating

We do **not** run real Docker/Kubernetes in the evaluation loop. We simulate:

| Real-world thing | Simulator object | Role |
|---|---|---|
| Edge machine / VM | `EdgeServer` | Finite CPU & RAM capacity; hosts containers |
| Local orchestrator site | `Cluster` | Owns a set of servers; has a manager |
| Cloud coordinator | `RootOrchestrator` | Topology, admission, global fallback |
| Deployable product | `Application` | Graph of microservices |
| One running replica | `Container` (instance) | Holds allocated CPU/RAM; reports usage |
| Client demand over time | `Workload` / trace | Drives offered load → usage → latency |
| WAN / inter-site RTT | `Link` / distance matrix | Communication delay between servers/clusters |

Time advances in **discrete decision windows** \(t = 1, 2, \ldots, T\) (e.g. 1 minute). Inside a window, load is treated as stationary enough to compute utilization and make one scaling decision.

```text
                    ┌─────────────────────┐
                    │  RootOrchestrator   │
                    └─────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
     ┌─────────┐         ┌─────────┐         ┌─────────┐
     │Cluster A│         │Cluster B│         │Cluster C│
     │ manager │         │ manager │         │ manager │
     └───┬─────┘         └───┬─────┘         └───┬─────┘
         │                   │                   │
    ┌────┴────┐         ┌────┴────┐         ┌────┴────┐
    ▼         ▼         ▼         ▼         ▼         ▼
 Server   Server    Server   Server    Server   Server
  c1w1     c1w2      c2w1     c2w2      c3w1     c3w2
    │         │         │
    └─ Container(s) of app microservices ─┘
```

---

## 2. Edge servers

### 2.1 Representation

An edge server is a resource box, not a process:

```python
@dataclass
class EdgeServer:
    id: str
    cluster_id: str
    cpu_capacity: float      # e.g. 4.0 cores
    ram_capacity: float      # e.g. 8192 MB
    location: tuple[float, float] | None  # optional geo / grid coords

    # derived each window
    cpu_used: float = 0.0    # sum of container *usage* (or allocated—see §6)
    ram_used: float = 0.0
    containers: list[Container] = field(default_factory=list)
```

**Free capacity** (what placement checks):

\[
f^{cpu} = CPU_{cap} - \sum_{i \in server} a_i^{cpu},
\quad
f^{ram} = MEM_{cap} - \sum_{i \in server} a_i^{ram}
\]

where \(a_i\) is the **allocation** (limit) of container \(i\), not instantaneous usage. This matches how orchestrators reserve resources.

### 2.2 What we deliberately omit (v1)

- Disk, GPU, NUMA  
- OS scheduling noise / noisy neighbors beyond shared capacity  
- Real container image pull time (optional constant cold-start delay later)  
- Failure/reboot (optional Phase 2)

Heterogeneity is enough realism: different servers can have different `cpu_capacity` / `ram_capacity`.

### 2.3 Config example

```yaml
servers:
  - id: c1-w1
    cluster: c1
    cpu: 4.0
    ram_mb: 8192
  - id: c1-w2
    cluster: c1
    cpu: 2.0
    ram_mb: 4096
```

---

## 3. Clusters

### 3.1 Representation

A cluster is an administrative domain: a manager plus the servers it **owns**.

```python
@dataclass
class Cluster:
    id: str
    server_ids: list[str]
    # filled by topology init
    vicinity_id: str | None = None
    is_vicinity_leader: bool = False
```

Ownership rules for the environment (independent of scaling policy):

- Every server belongs to **exactly one** home cluster.  
- A container may run on a **foreign** server (borrow); the environment still knows `owner_cluster(server)` vs `app_home_cluster`.  
- Aggregate cluster load for global decisions can be a capacity-weighted mean of server utilizations (see options/algorithm docs).

### 3.2 Topology and distance

Clusters (or servers) sit in a metric space:

```yaml
clusters:
  - id: c1
    coords: [0.0, 0.0]
  - id: c2
    coords: [1.0, 0.2]
  - id: c3
    coords: [5.0, 4.0]

# either derive latency from coords, or set explicitly:
latency_ms:
  c1-c2: 5
  c1-c3: 40
  c2-c3: 38
```

**Propagation delay** between request origin server \(e\) and serving server \(e'\):

\[
D(e,e') = \texttt{latency}(cluster(e), cluster(e'))
\]

(or finer server-level matrix if needed). Bandwidth \(B(e,e')\) can be a constant per link class (intra-cluster vs inter-cluster) for transmission delay \(\bar{s}/B\).

**Current HierarchicalEdgeSim:** `coords` and `topology.latency_ms` exist as topology \(d(c,c')\) for Algorithm 1 and `Env.distance`. They do **not** delay user requests (no \(D(e,e')\) on the serving path). See [vicinity-partition.md](./vicinity-partition.md).

### 3.3 Vicinities (environment fact, not policy)

Vicinity membership is part of the **environment configuration** after init:

- Non-overlapping groups of clusters (size typically 3–5).  
- Built from distances (z-score / gap heuristic) or hand-specified for controlled experiments.  
- One leader flag per vicinity for the control plane to use later.

The environment only needs to expose: `vicinity_of(c)`, `leader_of(vicinity)`, `distance(c, c')`.

---

## 4. Applications and microservices

### 4.1 Application

An application is a deployable product assigned to a **home cluster** at admission time.

```python
@dataclass
class Application:
    id: str
    home_cluster_id: str
    microservices: list[str]   # ids
```

v1 can treat microservice interactions lightly (independent demand per MS). v2 can add a call graph (A→B→C) so end-to-end latency sums stage delays.

### 4.2 Microservice type (deployment descriptor)

This is the “Helm values / k8s resources” of the sim:

```python
@dataclass
class MicroserviceSpec:
    id: str
    app_id: str
    cpu_min: float
    cpu_max: float
    ram_min: float
    ram_max: float
    # optional: service time at 1 core, payload size, etc.
    work_per_request: float   # CPU-seconds per request at reference speed
```

Floors (`cpu_min`, `ram_min`) are environment constraints: a container cannot be created or shrunk below them without crashing (policy must respect them).

### 4.3 Config example

```yaml
applications:
  - id: video_pipe
    home_cluster: c1
    microservices:
      - id: ingest
        cpu_min: 0.5
        cpu_max: 2.0
        ram_min_mb: 256
        ram_max_mb: 2048
        work_per_request: 0.01
      - id: infer
        cpu_min: 1.0
        cpu_max: 4.0
        ram_min_mb: 512
        ram_max_mb: 4096
        work_per_request: 0.05
```

---

## 5. Containers (instances)

### 5.1 Representation

A container is one running replica of a microservice on one server:

```python
@dataclass
class Container:
    id: str
    microservice_id: str
    app_id: str
    server_id: str
    # who “owns” the app vs who owns the machine
    app_home_cluster_id: str
    server_owner_cluster_id: str

    cpu_alloc: float          # limit / reservation
    ram_alloc: float

    # measured each window (see §6)
    cpu_usage: float = 0.0    # actual used cores in [0, cpu_alloc]
    ram_usage: float = 0.0

    tier: str = "local"       # local | vicinity | global (loan bookkeeping)
```

**Allocation vs usage** (critical distinction):

| Quantity | Meaning | Used for |
|---|---|---|
| `cpu_alloc` / `ram_alloc` | Reserved resources (vertical size) | Placement feasibility, cost, free capacity |
| `cpu_usage` / `ram_usage` | Observed consumption this window | Utilization ratios, scale up/down signals |

Utilization reported to the control plane:

\[
q^{cpu} = \frac{\texttt{cpu\_usage}}{\texttt{cpu\_alloc}},
\quad
q^{ram} = \frac{\texttt{ram\_usage}}{\texttt{ram\_alloc}}
\]

(clamp alloc > 0). This is what mimics `kubectl top` / cAdvisor.

### 5.2 Lifecycle events the environment supports

- `spawn(ms, server, cpu_alloc, ram_alloc)` — usually at minima  
- `resize(container, cpu_alloc', ram_alloc')` — vertical; must stay within floors/caps and free capacity  
- `terminate(container)` — free allocation  

Cold start can be modeled as “container becomes Ready after \(t_{start}\) windows” if we want realism later; v1 can be instant.

---

## 6. How a trace becomes CPU/RAM usage

This is the core of “mimicking containers.” Demand does **not** magically set allocation; the trace sets **offered load**, and usage is derived from load + current replicas + allocations.

### 6.1 Trace formats

**Simple (what the current thesis repo uses):**

```csv
minute,request_count
1,50
2,150
3,740
```

Mapped to one app (or one microservice) at one gateway cluster:

\[
\Lambda(t) = \texttt{request\_count}(t)
\quad\text{(requests per window)}
\]

**Richer (recommended):**

```csv
t,cluster_id,app_id,microservice_id,request_count
10,c1,video_pipe,ingest,400
10,c1,video_pipe,infer,380
10,c2,video_pipe,ingest,20
```

This enables spatial hotspots (load arrives at different clusters).

### 6.2 From requests to instance arrival rates

Given active instances \(I_m(t)\) of microservice \(m\), split demand by weight (e.g. proportional to `cpu_alloc` or equal share):

\[
\lambda_i(t) = w_i(t)\,\Lambda_m(t),
\quad
\sum_i w_i = 1
\]

### 6.3 CPU usage model (primary)

Two practical options; pick one and stick to it for all baselines.

#### Option A — Linear demand model (simple, matches current repo)

Define a conversion factor \(\rho\) (CPU-cores per request/window), possibly equal to `work_per_request` normalized by window length:

\[
\texttt{cpu\_usage}_i(t)
=
\min\big(\texttt{cpu\_alloc}_i,\;
\lambda_i(t)\cdot\rho\big)
\]

If demand exceeds allocation, usage saturates at `cpu_alloc` and **excess demand** becomes queueing / SLA violation (unmet or delayed work).

This is what the existing prototype approximates with `RequiredCPU = Requests × 0.01`.

#### Option B — Queueing / service-rate model (closer to the paper)

Service rate grows with allocation:

\[
\mu_i(t) = f(\texttt{cpu\_alloc}_i, \texttt{ram\_alloc}_i)
\]

e.g. \(\mu_i = \texttt{cpu\_alloc}_i / \texttt{work\_per\_request}\).

Then:

- If \(\lambda_i < \mu_i\): stable; mean queue delay \(1/(\mu_i-\lambda_i)\);  
  CPU usage ≈ \(\lambda_i / \mu_i \cdot \texttt{cpu\_alloc}_i\) (busy fraction × allocation).  
- If \(\lambda_i \ge \mu_i\): saturated; usage ≈ `cpu_alloc`; large / infinite delay → bad latency metric.

**Recommendation:** start with **Option A** for bring-up (fast, debuggable), then switch evaluation metrics to **Option B** when aligning with `auto-scaling.tex`.

### 6.4 RAM usage model

RAM is rarely linear in request rate the same way CPU is. Practical v1:

1. **Floor-dominated:** `ram_usage = ram_min + α · (cpu_usage/cpu_alloc) · (ram_alloc - ram_min)`  
   — usage rises with load but stays within allocation.  
2. **Trace column:** if a real memory trace exists, set `ram_usage` from the trace scaled into `[ram_min, ram_alloc]`.  
3. **Constant working set:** `ram_usage ≈ ram_alloc` (forces RAM to act mostly as a placement constraint).

For autoscaling signals, many systems scale on CPU first; RAM still matters for **spawn/shrink floors** and packing.

### 6.5 End-to-end picture for one window

```text
trace Λ_m(t)
    │
    ▼
split across containers  →  λ_i(t)
    │
    ▼
usage model  →  cpu_usage_i, ram_usage_i
    │
    ▼
server aggregates  →  u_server, free capacity from *allocations*
    │
    ▼
metrics API  →  vectors (h, a, q, f, …) for the control plane
    │
    ▼
(optional) latency model from λ, μ, D(e,e')
```

The control plane may then change allocations / instance counts; those take effect in window \(t+1\) (or after cooldown).

### 6.6 Worked numeric example

- Window = 1 minute, \(\rho = 0.01\) cores per request/min  
- Microservice has 2 containers on a 4-core server, each `cpu_alloc = 1.0`  
- Trace: \(\Lambda = 150\) requests  

Equal split: \(\lambda_i = 75\) → desired CPU \(75 \times 0.01 = 0.75\)  
→ each `cpu_usage = 0.75`, `q = 0.75`  

If \(\Lambda = 400\): desired \(2.0\) cores per instance → capped at `cpu_alloc=1.0`, `q=1.0`, overload flagged.

Horizontal scale-out adding two more instances at `cpu_min=0.5` changes the split and reduces per-instance \(q\).

---

## 7. Network and latency (environment side)

Keep this thin in v1:

```python
def communication_delay(origin_server, serving_server, payload_bytes) -> float:
    d = latency_ms(origin, serving) / 1000.0
    b = bandwidth_bps(origin, serving)
    return d + (payload_bytes * 8) / b
```

Intra-cluster latency ≪ inter-cluster ≪ cross-region. Request **routing** can be:

- sticky to nearest instance of the MS, or  
- capacity-weighted among all active instances (as in the formulation).

Latency is an **output metric**, not required to drive usage if you use Option A; it becomes essential for comparing placement quality (local vs vicinity vs global).

---

## 8. Root orchestrator (environment role)

In the **implementation** ([implementation-plan.md](./implementation-plan.md)), the env does **not** own a `RootOrchestrator` class. The env only stores topology metadata (latencies, vicinity members, leader id). Admission ranking, vicinity packing, and global fallback live in the **hierarchical autoscaler plugin**. Conceptually those are still “root / leader” responsibilities; they are just not Part A objects.

---

## 9. Simulator clock and measurement API

### 9.1 Window loop (environment only)

```text
for t in 1..T:
    1. read workload Λ(·, t)
    2. for each container: update cpu_usage, ram_usage   # §6
    3. recompute server aggregates
    4. expose metrics snapshot Metrics(t)
    5. [control plane decides actions]                  # elsewhere
    6. apply spawn/resize/terminate queued for t
    7. log metrics / actions
```

### 9.2 Metrics snapshot (what “monitoring” returns)

Per server: `cpu_capacity`, `ram_capacity`, `cpu_alloc_sum`, `ram_alloc_sum`, `cpu_usage_sum`, `ram_usage_sum`  
Per microservice: instance counts per server, allocs, utilizations \(q\), eligibility  

This replaces Prometheus for the sim.

---

## 10. Suggested config: full tiny environment

```yaml
sim:
  window_sec: 60
  horizon_windows: 60
  seed: 42

clusters:
  - { id: c1, coords: [0, 0] }
  - { id: c2, coords: [1, 0] }
  - { id: c3, coords: [6, 1] }

servers:
  - { id: c1-w1, cluster: c1, cpu: 4.0, ram_mb: 8192 }
  - { id: c1-w2, cluster: c1, cpu: 4.0, ram_mb: 8192 }
  - { id: c2-w1, cluster: c2, cpu: 4.0, ram_mb: 8192 }
  - { id: c2-w2, cluster: c2, cpu: 4.0, ram_mb: 8192 }
  - { id: c3-w1, cluster: c3, cpu: 8.0, ram_mb: 16384 }
  - { id: c3-w2, cluster: c3, cpu: 8.0, ram_mb: 16384 }

latency_ms:
  c1-c2: 5
  c1-c3: 45
  c2-c3: 40

vicinities:                 # optional hand-spec for controlled tests
  - id: v1
    members: [c1, c2]
    leader: c1

applications:
  - id: demo_app
    home_cluster: c1
    microservices:
      - id: api
        cpu_min: 0.5
        cpu_max: 2.0
        ram_min_mb: 256
        ram_max_mb: 2048
        work_per_request: 0.01

workload:
  type: csv
  path: traces/wc_day6_1_bursts.csv
  # maps all rows to:
  target:
    cluster: c1
    app: demo_app
    microservice: api
  rho_cpu_per_request: 0.01   # Option A
```

---

## 11. Codebase layout (environment-focused)

```text
sim/
  configs/
  traces/
  src/
    domain/
      server.py
      cluster.py
      application.py
      container.py
      topology.py
    workload/
      trace_replay.py
      usage_model.py      # Λ → cpu_usage/ram_usage
    network/
      latency.py
    engine/
      clock.py
      metrics.py
      simulator.py        # window loop §9
    # policy/             # added later — not required to validate the env
  tests/
    test_usage_model.py
    test_placement_capacity.py
    test_trace_replay.py
```

Validate the environment **before** wiring autoscaling: replay a trace with a *fixed* number of containers and check that usage, saturation, and free capacity evolve as expected.

---

## 12. Candidate external bases (short)

| Base | Use for environment? |
|---|---|
| [edge_computing_thesis](https://github.com/Sky-himself/edge_computing_thesis) | Domain inspiration + traces; rewrite in-process |
| [EdgeSimPy](https://github.com/EdgeSimPy/EdgeSimPy) | Optional entity/provisioning library |
| YAFS / RegionalEdgeSimPy | Patterns only unless you already prefer them |

Default: **greenfield environment modules** shaped like §2–§9, seeded with concepts and CSVs from the thesis repo.

---

## 13. Open environment decisions

1. **Usage model A vs B** for the paper’s main results?  
2. **Single MS vs call-graph apps** in v1?  
3. **Hand-specified vicinities** for experiments vs only algorithmic partition?  
4. Should RAM usage track CPU, stay near `ram_alloc`, or come from a separate trace?  
5. Instant container start vs fixed cold-start delay?

Once these are fixed, implementing the environment is mostly straightforward dataclasses + a window loop; the autoscaling policy can plug into step 5 of §9.1 later.

---

## 14. End-to-end example: 30‑minute trace + LSTM


This section answers: *if I have an LSTM and a 30‑minute request-rate trace at 1 Hz (1800 points), what does a run actually do?*

### 14.1 Inputs you bring

| Input | Example |
|---|---|
| Trace file | `trace_30min.csv` with columns `t_sec, request_rate` → 1800 rows (1 sample/sec) |
| LSTM | Already trained offline on *other* days/hours; at test time we only run **inference** |
| Environment YAML | 3 clusters, 6 servers, 1 app / 1 microservice `api`, ρ = 0.01 cores per req/s, etc. |
| Decision window | **60 seconds** (typical); then the 30‑minute test has \(T = 30\) decisions |

**Important:** the autoscaler does **not** make a new decision every second. Seconds are for fine-grained load; decisions happen once per window.

### 14.2 Step 0 — Aggregate the trace into windows

```text
1800 samples @ 1 Hz
        │
        ▼  group every 60 consecutive seconds
30 windows, each with a scalar demand Λ(t)

Λ(t) = mean(request_rate over that minute)
     # or sum, or p95 — pick one definition and keep it fixed
```

Example:

| Window \(t\) | Seconds covered | Mean req/s → \(\Lambda(t)\) |
|---|---|---|
| 1 | 1–60 | 12.4 |
| 2 | 61–120 | 45.0 |
| … | … | … |
| 30 | 1741–1800 | 8.1 |

Optionally keep the 60 raw seconds inside the window if you later want sub-minute queue simulation; v1 only needs \(\Lambda(t)\).

### 14.3 Step 0b — LSTM is ready for inference (not training)

Offline (before the test):

```text
historical traces  →  train LSTM  →  saved weights (e.g. lstm.pt)
```

Online (during the 30‑minute test):

```text
recent window history [u(t-L), …, u(t)]  →  LSTM.predict  →  û(t+1), …, û(t+H)
```

- Input to LSTM: usually past **utilizations** or past \(\Lambda\), length \(L\) (e.g. last 10 windows).  
- Output: next \(H\) windows (e.g. \(H=3\) if cooldown is 3 minutes).  
- First few windows (\(t < L\) or low confidence): **reactive** mode (no trust in forecast yet).

The 1800-point file is the **ground-truth load** for the test. The LSTM does **not** read the future part of that file; that would be cheating. It only sees what has already happened (or metrics derived from it).

### 14.4 Initial world state (before \(t=1\))

Suppose config says:

- Home cluster `c1` with servers `c1-w1`, `c1-w2` (4 cores each)  
- App `demo_app` / MS `api`: `cpu_min=0.5`, `cpu_max=2.0`, `ram_min=256MB`  
- Start with **1 container** on `c1-w1`: `cpu_alloc=0.5`, `ram_alloc=256`

### 14.5 What one window looks like (e.g. minute \(t=7\))

```text
┌─────────────────────────────────────────────────────────────┐
│ Window t = 7 (seconds 361–420 of the raw trace)             │
└─────────────────────────────────────────────────────────────┘

(1) LOAD
    Λ(7) = mean(req/s in that minute) = 80   # from the 1800-point trace

(2) USAGE (environment)
    One container i on c1-w1, cpu_alloc = 1.0
    cpu_usage = min(cpu_alloc, Λ(7) * ρ) = min(1.0, 80*0.01) = 0.80
    q_cpu = 0.80 / 1.0 = 0.80
    # RAM via whatever model you chose (e.g. rises with q)

(3) METRICS SNAPSHOT
    Cluster manager reads vectors: has_instance, alloc, usage, free_cpu, …

(4) PREDICT (LSTM inference)
    history = [q(2), q(3), q(4), q(5), q(6), q(7)]   # length L
    û(8), û(9), û(10) = lstm.predict(history)         # horizon H=3
    # compare past predictions vs realized q → update confidence κ

(5) DECIDE
    if κ high: use û to choose Up / Down / None and residual δ
    else:      reactive on current q only
    # e.g. q=0.80 and û peaks at 0.95 → scale Up, compute δ_cpu, δ_ram

(6) ACT (policy ladder — BEV then BEH then …)
    e.g. vertical grow: cpu_alloc 1.0 → 1.2 on same container
    or spawn second container at cpu_min if vertical not enough
    actions are applied now (or marked ready for t+8)

(7) LOG
    row: t, Λ, q, alloc_total, n_replicas, latency_est, cost, actions
```

Then advance to \(t=8\) and repeat. After 30 windows, the run ends.

### 14.6 How the 1800 points relate to the 30 decisions

```text
Raw trace (1 Hz)          Windows (1/min)           Control plane
─────────────────         ───────────────           ─────────────
r[1]                      ┐
r[2]                      │
...                       ├─→ Λ(1)  ─────────────→  decision #1
r[60]                     ┘
r[61]                     ┐
...                       ├─→ Λ(2)  ─────────────→  decision #2
r[120]                    ┘
...
r[1741]                   ┐
...                       ├─→ Λ(30) ─────────────→  decision #30
r[1800]                   ┘
```

If you prefer **finer decisions** (e.g. every 10 s): then \(T = 180\) windows, LSTM horizon is in units of 10 s, and you aggregate 10 samples per window instead of 60. Same code path; only `window_sec` changes.

### 14.7 Pseudocode for the test harness

```python
trace = load_csv("trace_30min.csv")          # 1800 points
windows = aggregate(trace, window_sec=60)  # → 30 values Λ[1..30]

env = build_env_from_yaml("configs/demo.yaml")
lstm = load_lstm("models/lstm.pt")         # trained earlier on OTHER data
policy = HierarchicalAutoscaler(lstm=lstm, H=3, L=10)

logs = []
for t in range(1, 31):
    env.apply_load(windows[t])             # sets cpu_usage / ram_usage on containers
    snap = env.metrics_snapshot()          # monitoring vectors

    forecast = None
    if t >= L and policy.confidence_ok():
        hist = policy.history_features(snap, t)
        forecast = lstm.predict(hist, horizon=H)   # û(t+1)..û(t+H)

    actions = policy.decide(snap, forecast, t)     # Up/Down/None + BEV/BEH/...
    env.apply(actions)                             # spawn / resize / terminate

    logs.append(env.evaluate(snap, actions, t))    # latency, cost, replicas, …

write_csv("results_30min.csv", logs)
```

### 14.8 What you expect to have at the end

Artifacts after one 30‑minute test run:

1. **`results_30min.csv`** — one row per window:  
   `t, request_rate, cpu_usage, cpu_alloc, replicas, q, predicted_q, action, p95_latency, cost, loans, unmet`
2. **Time-series plots** — load vs allocated CPU vs replicas; vertical lines when vicinity/global kicks in  
3. **Summary metrics** — mean/p95 latency, total cost, # scale events, unmet demand fraction  
4. **(Optional) comparison** — same trace replayed with baselines (reactive-only, no vicinity, …)

You do **not** need to “run” 1800 scaling decisions. You need 30 (or 180) closed-loop steps where:

- the **trace** supplies truth \(\Lambda(t)\),  
- the **usage model** turns that into container CPU/RAM readings,  
- the **LSTM** forecasts the next few windows from history,  
- the **policy** changes alloc/replicas,  
- the **next** window’s usage reflects both new load and new capacity.

### 14.9 Common pitfalls

| Mistake | Why it’s wrong |
|---|---|
| LSTM peeks at \(\Lambda(t+1)\) from the CSV | Future leakage; inflate proactive gains |
| One decision per second on 1800 points | Unrealistically chatty; thrash + no cooldown |
| Setting `cpu_alloc = Λ*ρ` directly from the trace | Skips the closed loop; you’re not testing autoscaling |
| Training LSTM on the same 30‑minute test file | Overfit; use a different time range for training |

### 14.10 Mental model (one sentence)

**The 1800-point trace is the weather; windows are daily forecasts periods; containers are umbrellas whose size you adjust each period using LSTM guesses and current wetness (utilization); at the end you measure how dry users stayed (latency) and how many umbrellas you paid for (cost).**

---

## 15. Lessons from EdgeSimPy (local tree review)

We reviewed the vendored [`EdgeSimPy/`](../EdgeSimPy/) tree (simulator core, `ComponentManager`, `EdgeServer`, `Service`, `Application`, `User`, network links, dataset generators, packaging). Goal: steal practices that make a simulator credible and star-worthy, avoid patterns that fight *hierarchical autoscaling*, and tighten our §2–§11 design.

### 15.1 What EdgeSimPy is optimized for

EdgeSimPy is a **Mesa**-based, tick-driven edge simulator aimed at **service placement / migration / provisioning**, not at proactive horizontal+vertical autoscaling across cluster managers.

| Layer (their docs) | Main entities |
|---|---|
| Core | `Simulator`, dataset load/export, `monitor()` / msgpack logs |
| Physical | `EdgeServer`, `BaseStation`, `NetworkSwitch`, `NetworkLink`, NetworkX topology |
| Logical | `Application` → `Service` (container instance), image/layer/registry model |
| Management | User-supplied `resource_management_algorithm(parameters)` each tick |

Their service model stores a **fixed** `cpu_demand` / `memory_demand` per service. Servers track capacity vs **demand** (`cpu - cpu_demand`). That is reservation accounting, close to our `alloc`, but there is **no first-class usage vs allocation split**, no request-rate trace → utilization pipeline, and no cluster / vicinity / root hierarchy.

Provisioning realism is a strength: Docker-like **layers, images, registries**, pull queues, migration state machines, bandwidth sharing on links. That is excellent for migration papers; mostly **out of scope** for our v1 autoscaling thesis (optional later as cold-start delay).

### 15.2 Side-by-side: EdgeSimPy vs our proposed environment

| Concern | EdgeSimPy | Our design (§2–§11) | Takeaway |
|---|---|---|---|
| Time | Mesa ticks (`tick_duration` + unit) | Discrete **decision windows**; raw trace may be 1 Hz | Keep windows; allow `tick` alias for sub-window network if needed later |
| Policy hook | `resource_management_algorithm(parameters)` each step | `policy.decide(snap, forecast)` after `apply_load` | **Adopt** a single pluggable policy callable / protocol |
| Servers | `cpu/memory/disk` + `*_demand` | capacity + alloc sum + usage sum | Keep our **alloc ≠ usage**; name fields clearly |
| “Container” | `Service` with fixed demand | `Container` with alloc + usage + min/max | Do not copy fixed-demand-only services |
| App model | `Application` lists services; users access apps | App → microservice specs → many containers | Compatible; add **replica sets** on top |
| Topology | Full NetworkX graph (switches, links) | Cluster distance / latency matrix (v1) | Start simple; optional NetworkX later |
| Hierarchy | Flat servers (+ base stations) | Cluster → servers, root, vicinities | **Must add**; EdgeSimPy has no analogue |
| Workload | User access patterns (circular/random) | Trace replay → \(\Lambda(t)\) → usage model | Keep traces; optionally wrap as “access pattern” |
| Capacity check | `has_capacity_to_host(service)` | free ≥ min alloc for spawn/resize | **Adopt** explicit predicate + unit tests |
| Metrics | Per-agent `collect()`; periodic msgpack dump | Window CSV + summary | Adopt `collect()` style; CSV/Parquet is fine for MSc |
| Scenario I/O | JSON **attributes + relationships** | YAML config + CSV traces | Adopt structured scenario export/import |
| Object registry | Class-level `_instances`, `all()`, `find_by_id()` | Normal Python containers owned by `Simulator` | Prefer **instance-scoped** registries (parallel runs) |
| Packaging | Poetry, docs site, tutorials repo, paper | (planned) | **Required** for a public GitHub project |

### 15.3 Best practices to steal

1. **Pluggable management algorithm**  
   EdgeSimPy never hard-codes the policy inside `EdgeServer.step()`. The simulator calls one user function per tick (`simulator.py` `step()` → `resource_management_algorithm`).  
   **We should:** define a small protocol, e.g. `def step(ctx: SimContext) -> list[Action]`, and ship baselines as drop-in modules. Users star projects they can extend in one file.

2. **Scenario as data, not code**  
   JSON with `attributes` / `relationships`, plus `export_scenario()`, means experiments are reproducible and shareable.  
   **We should:** `configs/*.yaml` + `scenarios/*.json` export after init; never bury topology only in Python.

3. **First-class capacity API**  
   `EdgeServer.has_capacity_to_host(service)` is the right abstraction for placement.  
   **We should:** `server.can_spawn(ms_spec)`, `server.can_resize(container, new_cpu, new_ram)` returning bool + reason (for Reject paths).

4. **Per-entity metrics collection**  
   Override `collect()`; simulator aggregates with a time-step index; dump periodically so long runs do not explode RAM.  
   **We should:** `collect()` on Server/Cluster/Container/App; flush every \(N\) windows to Parquet/CSV.

5. **Clear entity vocabulary in docs**  
   Their README maps real systems (Docker layers, base stations) to classes.  
   **We should:** one diagram + glossary (Server, Cluster, Container, Loan, Window) on the repo front page.

6. **Dataset generators / presets**  
   Pre-built server models (RPi, Jetson, …) and placement helpers lower onboarding friction.  
   **We should:** ship 2–3 named topologies (`tiny_3x2`, `vicinity_9`, …) and at least one public trace adapter (FIFA-style).

7. **Separable network scheduling**  
   Bandwidth sharing is a separate callable (`network_flow_scheduling_algorithm`).  
   **We should:** keep latency model swappable (`ConstantLatency`, `MatrixLatency`) without touching the autoscaler.

8. **External tutorials + paper PDF**  
   Stars come from tutorials as much as from code. Plan a `examples/` folder early (even with 2 notebooks).

### 15.4 Mistakes / patterns to avoid (for our goals)

1. **Conflating demand with usage**  
   EdgeSimPy’s `cpu_demand` is really an **allocation**. Power models also key off demand. If we only copy that, we cannot drive autoscaling from utilization or show saturation under overload.  
   **Fix in our design:** always maintain `cpu_alloc` and `cpu_usage` (and the same for RAM).

2. **No replica / vertical scaling primitives**  
   A `Service` is one instance with fixed demand; “scale out” means creating more Service objects and placing them—possible, but not a built-in autoscaling loop. Vertical resize is not a first-class operation.  
   **We must** implement spawn/resize/terminate as environment operations with floors/caps.

3. **Global class registries (`_instances`)**  
   Convenient (`Service.all()`), but hostile to parallel experiments and clean test teardown (mutable process-global state). EdgeSimPy resets registries in `initialize()`, which is easy to get wrong.  
   **We should:** `sim.containers`, `sim.servers` owned by one `Simulator` instance; optional `sim.all(Container)` helper.

4. **Heavyweight Mesa dependency without need**  
   Mesa helps agent scheduling and tutorials, but adds conceptual overhead if our agents do not need independent `step()` behaviors beyond the window loop.  
   **Recommendation:** plain Python window loop for v1; do not inherit Mesa unless we later need rich agent interactions. Call this out in the README so reviewers do not ask “why not Mesa/EdgeSimPy?” without an answer.

5. **Overbuilding Docker layer simulation early**  
   Image digests, layer pull queues, and migration FSMs are impressive but orthogonal to BEV/BEH/BEVi. Shipping them unfinished invites criticism.  
   **Phase them:** v1 instant provision + optional constant `cold_start_windows`; v2 optional layer model if we claim provisioning delay.

6. **Empty `Application.collect()` / thin app metrics**  
   Apps exist but barely report metrics. Reviewers care about **application-level** latency and cost.  
   **We should:** aggregate metrics at app and microservice level every window by default.

7. **Mutation of capacity inside policy examples**  
   Their sample policies call `service.provision()`, which mutates server demand. That is fine if provision is transactional; it is easy for users to double-count if they also tweak `cpu_demand` by hand.  
   **We should:** only mutate state through `env.apply(actions)` after validation; policy returns intents, not raw field writes.

8. **Mute failures**  
   Prefer explicit exceptions with actionable messages (EdgeSimPy does this well on dataset load). Do the same for invalid traces, capacity violations, and future-leakage guards in predictors.

### 15.5 Gaps we must implement that EdgeSimPy does not provide

These are features our public simulator should advertise as the differentiator—not weak copies of EdgeSimPy:

- Cluster manager + root orchestrator entities  
- Vicinity partition / leader as topology metadata  
- Loan registry (owner vs borrower) on servers  
- Trace → window aggregation → usage model (§6, §14)  
- Predictor interface + confidence (even if LSTM is an optional plugin)  
- Allocation cost model and unmet-demand accounting  
- Baseline policy pack (reactive, local-only, no-leader, …) for fair comparison  

Do **not** claim to replace EdgeSimPy; claim a **focused hierarchical autoscaling workbench** that can optionally interoperate later.

### 15.6 Recommended architecture adjustments (inspired by EdgeSimPy)

Update §11 mentally as follows:

```text
sim/
  src/
    core/
      simulator.py       # window loop; owns all entity registries
      scenario.py        # load/export YAML/JSON (attributes + relationships)
      metrics.py         # collect() aggregation + flush
    domain/              # Server, Cluster, Container, Application, Topology
    workload/            # trace aggregate + usage model
    network/             # latency backends
    api/
      capacity.py        # can_spawn / can_resize
      actions.py         # Spawn, Resize, Terminate dataclasses
      policy.py          # Protocol: decide(ctx) -> list[Action]
    policies/            # hierarchical + baselines (plugins)
    predictors/          # optional LSTM / MA / oracle
  examples/              # 2–3 runnable scripts (star magnet)
  tests/
  configs/
  traces/
```

**Control flow to mirror EdgeSimPy’s clarity, with our semantics:**

```text
for each window t:
    workload.apply(t)           # environment: usage from Λ(t)
    metrics.collect(t)
    actions = policy.decide(ctx)  # user plug-in (like resource_management_algorithm)
    env.apply(actions)          # only validated mutations
    metrics.collect(t)          # post-action snapshot (optional)
```

### 15.7 Bar for a “hard to criticize” public repo

Checklist before calling the simulator release-worthy:

| Bar | Concrete requirement |
|---|---|
| Correctness | Unit tests for usage model, capacity, spawn/resize floors, window aggregation |
| Reproducibility | Seeded runs; scenario export; same trace → same CSV |
| Honesty | README states what is *not* modeled (no kernel scheduling, optional cold-start, …) |
| Extensibility | One-file custom policy example that runs in <30 lines |
| Comparison | At least two baselines + one hierarchical policy on the same scenario |
| Docs | Architecture diagram, entity glossary, 30‑min LSTM walkthrough (§14) |
| Packaging | `pyproject.toml`, typed public API, CI running tests |
| Citation | BibTeX / thesis link; acknowledge EdgeSimPy as related work (placement-oriented) |

### 15.8 Bottom line

- **Learn from EdgeSimPy:** plug-in policy hook, scenario I/O, capacity predicates, per-entity `collect()`, presets, docs/tutorials discipline.  
- **Do not become EdgeSimPy:** skip Mesa + Docker-layer migration as v1 foundations; add clusters, alloc/usage, traces, and hierarchical control as the core product.  
- **Positioning:** *hierarchical edge autoscaling simulator* (decision-window, trace-driven, multi-cluster), not a general edge placement toolkit. That focus is what makes the GitHub story defensible and, later, star-able.

