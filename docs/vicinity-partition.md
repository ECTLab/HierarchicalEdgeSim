# Vicinity partition and leader election (Algorithm 1)

**Status:** done  
**Paper:** `VicinityPartitionAndLeaderElection` in `proposed_method_complete.tex`  
**Code:** `src/hierarchical_edge_sim/env/partition.py` → `RootOrchestrator`

The root **computes** non-overlapping vicinities from inter-cluster distance and elects a leader. YAML `topology.vicinities` remains an override for ladder experiments that must pin a specific grouping (triangle BEG/vicinity slices).

This is topology only. User requests are still drop-overflow; nothing is delayed by RTT.

---

## When the algorithm runs

| Config | What the root does |
|---|---|
| No coords, no `latency_ms`, no `vicinities` | `World.root is None` (same as before, e.g. `tiny.yaml`) |
| Complete coords **or** complete `latency_ms`, no `vicinities` | Run Algorithm 1; `vicinity_source=algorithm` |
| `topology.vicinities` present | Use the hand list; `vicinity_source=yaml`. Coords/`latency_ms` still fill `Env.distance` if complete |

---

## Coords vs latency (what is implemented)

**Inter-cluster latency is implemented as topology distance \(d(c,c')\), not as delay on user requests.** Nothing in the serving path waits on RTT. There are no per-worker request queues. `Env.distance(a, b)` and Algorithm 1 read the same matrix.

Two ways to supply \(d\):

| YAML | How \(d(c,c')\) is built |
|---|---|
| `coords: [x, y]` on **every** cluster | Euclidean \(\sqrt{(x_1-x_2)^2+(y_1-y_2)^2}\) |
| Complete `topology.latency_ms` | The `ms` values **are** \(d\) (undirected pairs) |

**Whose job?** The scenario config’s. You do **not** have to invent RTTs for every demo. Coords are enough when geography is the story. Use `latency_ms` when you want measured or synthetic RTTs that are not a plane embedding.

**If a scenario gives both:** a **complete** `latency_ms` list wins; coords are ignored for \(d\). You cannot mix “some RTTs + fill the rest from coords.” If `latency_ms` is present but incomplete, validation fails. If `topology.vicinities` is also present, the **hand groups still win** for membership/leaders; distance is still stored so `Env.distance` works, but Algorithm 1 is not run.

`latency_ms` is **not** used to rank BEG (still free CPU) or to pick a vicinity helper (still published member order).

Example RTT list (every unordered pair):

```yaml
topology:
  latency_ms:
    - {from: c1, to: c2, ms: 5.0}
    - {from: c1, to: c3, ms: 40.0}
    - {from: c2, to: c3, ms: 38.0}
```

---

## Algorithm (mapped)

1. While unassigned clusters remain, pick the **densest seed**: most others at or inside the median pairwise distance of the remainder; tie → smallest cluster id.
2. Sort others by distance from the seed.
3. If at least two distances and \(\sigma>0\): keep those with z-score \(\le -k\) (paper).
4. Else (σ=0, or exactly one neighbor): largest-gap cut, or the single neighbor. The tex gap loop is empty when \(|D|=1\); without this, two clusters could never share a vicinity.
5. Cap at \(m_{\max}\) (default 5).
6. Elect \(\ell(V)\) by \(\rho = \alpha z(\mathrm{cap}) - \beta \overline{d}\) to the rest of \(V\); tie → smallest id. \(\mathrm{cap}(c)=w_{\mathrm{cpu}}\cdot\mathrm{cpuCap}+w_{\mathrm{ram}}\cdot\mathrm{ramCap}\) with default \(w_{\mathrm{ram}}=1/1024\) so GiB and cores are comparable.
7. Publish `v1`, `v2`, … in formation order. Members are seed first, then closest.

Knobs (optional `topology.partition`): `k` (default 1), `m_max` (5), `alpha` (10), `beta` (1), `w_cpu`, `w_ram`.

**k is sensitive.** Isolated sites inflate \(\sigma\), so \(k=1\) can yield an empty z-score cut and a singleton seed. The five-site demos use \(k=0.5\) so two close pairs plus an isolate appear. That is the paper’s sensitivity knob, not a second algorithm.

Not in this stage (tex paragraph *after* the listing): \(T_{\mathit{repart}}\), join/leave, heartbeat → BEG, simulated leader RPCs.

---

## How to check a run

`examples/run_env_only.py` only builds the world, plays traces, and writes logs. The partition is decided **once at bootstrap**. Proof is in `run_meta.yaml`, not in request drops.

| File | What to look at |
|---|---|
| `run_meta.yaml` | **Algorithm 1 check.** `vicinity_source`, `published_vicinities`, `latency_ms`, `clusters[*].coords` |
| `actions.csv` | Header only is correct for env-only (no autoscaler → no spawn/resize) |
| `*.log.csv` | Physics only: incoming = served + dropped. Drops on a 1-core container vs a peaked trace are expected |

A run is fine when:

- `vicinity_source: algorithm` (or `yaml` if you listed `vicinities:`)
- `published_vicinities` covers every cluster, disjoint, with the expected groups and capacity-first leaders
- For a **coords** demo: every cluster has `coords`, and `latency_ms: []`. The results do **not** store a computed distance table; rebuild Euclidean \(d\) from those coords if you need the numbers
- For a **latency** demo: `coords: null`, and `config.latency_ms` lists every pair (`a` / `b` / `ms`). Those milliseconds **are** \(d\)

A run is **not** a failure because:

- `actions.csv` is empty — you did not pass an autoscaler
- the container log has drops — Part A is drop-overflow; Algorithm 1 does not add RTT
- serving does not change because a neighbor is in the same vicinity — that only happens with `reactive_local` (S4/S5)

If `vicinity_source` is missing/`null`, or `published_vicinities` is empty while coords or a complete RTT list were set, that is a failure.

Dump the partition fields:

```bash
python3 -c "
import yaml
from pathlib import Path
p = Path('results/partition/42_20260826T164636Z/run_meta.yaml')  # your run dir
m = yaml.safe_load(p.read_text())
c = m['config']
print('source_path    ', m['source_path'])
print('N              ', m['N'])
print('vicinities yaml', c['vicinities'])
print('vicinity_source', c['vicinity_source'])
print('latency_ms     ', c['latency_ms'])
print('published      ', c['published_vicinities'])
"
```

---

## Demos and sample results

```bash
PYTHONPATH=src python3 examples/run_env_only.py configs/demo_60_two_clusters.yaml
PYTHONPATH=src python3 examples/run_env_only.py configs/demo_partition.yaml
PYTHONPATH=src python3 examples/run_env_only.py configs/demo_partition_latency.yaml
```

(`pytest` already sets `pythonpath = ["src"]` in `pyproject.toml`. A one-off `python3 examples/...` does not, unless the package is installed with `pip install -e .`.)

Run ids are `{seed}_{UTC}`. Folder names below are from 2026-08-26 checks; a new run gets a new stamp. Triangle configs still list `vicinities:` by hand so the up-ladder rungs stay forced.

### `demo_60_two_clusters.yaml` — coords, two clusters

Expected: one vicinity `{c1,c2}`, leader `c1` (more installed CPU/RAM). Sample: `results/42_20260826T164731Z`.

```yaml
vicinities: []
latency_ms: []
partition: null
vicinity_source: algorithm
published_vicinities:
  - id: v1
    members: [c1, c2]
    leader: c1
```

`c1` coords `[0, 0]`, `c2` coords `[1, 0]` → Euclidean \(d=1\). Two 60-tick logs; request conservation held. Drops (about 1085 and 840) are the 1-core cap vs the trace peaks, not a partition bug.

### `demo_partition.yaml` — coords, five sites

Expected groups: `{west-a, west-b}` leader `west-a`; `{east-a, east-b}` leader `east-a`; `{isolated}`. Uses \(k=0.5\). Sample: `results/partition/42_20260826T164636Z`.

This run used **coords**, not latency: every cluster has `coords`, and `latency_ms: []`. Pairwise \(d\) is Euclidean, for example west-a↔west-b = 0.2, east pair = 0.2, west↔east ≈ 10, anyone↔isolated ≈ 64–71. Those close 0.2 pairs are why two vicinities plus a singleton appear.

```yaml
vicinities: []
latency_ms: []
partition: {k: 0.5, m_max: 5}
vicinity_source: algorithm
published_vicinities:
  - id: v1
    members: [east-a, east-b]
    leader: east-a
  - id: v2
    members: [west-b, west-a]
    leader: west-a
  - id: v3
    members: [isolated]
    leader: isolated
```

Vicinity **ids** follow formation order (`east-a` was the densest seed, so it became `v1`). The **groups** are what matter. `N: 5` is the short `traces/demo/api.csv`, not a 60-tick load test.

Rebuild \(d\) from that run file (there is no stored latency table):

```bash
python3 - <<'PY'
import math, yaml
from pathlib import Path
from itertools import combinations
meta = yaml.safe_load(Path("results/partition/42_20260826T164636Z/run_meta.yaml").read_text())
print("latency_ms in this run:", meta["config"]["latency_ms"])
coords = {c["id"]: tuple(c["coords"]) for c in meta["config"]["clusters"]}
for a, b in combinations(coords, 2):
    (x1, y1), (x2, y2) = coords[a], coords[b]
    print(f"{a:10} {b:10}  {math.hypot(x1-x2, y1-y2):.3f}")
PY
```

### `demo_partition_latency.yaml` — complete RTT matrix, no coords

Same grouping story as the five-site coords demo, but \(d\) is milliseconds: 2 ms inside each metro, 40 ms NYC–London, 200 ms to `remote`. No `coords`. Sample: `results/partition_latency/42_20260826T170605Z`.

Those RTTs appear twice: in the YAML `topology.latency_ms` list, and in `run_meta.yaml` as `config.latency_ms` (`a` / `b` / `ms`). That is how you see the values when latency was involved.

```yaml
clusters:
  - {id: nyc-a, coords: null, ...}
  # nyc-b, lon-a, lon-b, remote also coords: null
vicinities: []
latency_ms:
  - {a: nyc-a, b: nyc-b, ms: 2.0}
  - {a: nyc-a, b: lon-a, ms: 40.0}
  # ... ten undirected edges; remote pairs are 200.0
vicinity_source: algorithm
published_vicinities:
  - id: v1
    members: [lon-a, lon-b]
    leader: lon-a
  - id: v2
    members: [nyc-a, nyc-b]
    leader: nyc-a
  - id: v3
    members: [remote]
    leader: remote
```

---

## Tests

```bash
python3 -m pytest tests/test_partition.py tests/test_root_vicinity.py -v
```

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-26 | Algorithm 1 on the root; YAML override kept |
| v2 | 2026-08-26 | `demo_partition_latency.yaml` — complete RTT matrix, no coords |
| v3 | 2026-08-26 | Coords vs latency, how to read `run_meta.yaml`, sample run excerpts |
