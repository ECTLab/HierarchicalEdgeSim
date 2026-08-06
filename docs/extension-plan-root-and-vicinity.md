# Extension Plan — Root & Vicinity (simplified)

**Status:** implemented (T0–T5)  
**Goal:** Add static vicinity / leader topology **and a minimal root orchestrator object** so Part B can escalate later — without growing Part A into a policy engine.

---

## 1. Scope

| In scope | Out of scope (for now) |
|---|---|
| Static **vicinity groups** + **leader** in YAML | Inter-cluster **latency / distance** |
| Minimal **`RootOrchestrator`** (topology owner / query façade) | Algorithmic partition / leader election |
| Validation + read APIs | BEVi packing, BEG ranking, loans, admissions |
| Keep Part A tick loop unchanged | Live spawn/resize/terminate |

---

## 2. Role of the root orchestrator *in this phase*

In the paper, the root:

1. Publishes vicinities and leaders  
2. Later handles **BEG** global escalation  

In **this** phase we only implement (1) as a first-class env object.

| Responsibility now | Responsibility later (Part B) |
|---|---|
| Own the published `{vicinity → members, leader}` map | BEG admission / ranking |
| Answer topology queries used by CM / plugins | Serialize global escalations |
| Be the single place Part B will later attach policy | Forecast-aware remote placement |

So the root **does almost no work during Part A ticks**, but it **exists** as the object that *holds and exposes* hierarchy state. That avoids a Part B refactor where “root” is only an implicit dict on `World`.

**Minimal class sketch (conceptual):**

```text
RootOrchestrator
  + vicinities: dict[id, Vicinity]
  + list_vicinities()
  + get_vicinity(id)
  + vicinity_of(cluster_id)
  + leader_of(vicinity_id)
  + is_leader(cluster_id)
  + list_vicinity_members(vicinity_id)
  # stubs reserved for Part B (raise NotImplementedError or no-op):
  # + beg_admit(...)   # not implemented in this phase
```

Wiring: `World.root: RootOrchestrator` (or `Env.root` pointing at the same instance).  
Source of truth for membership/leader lives **on the root** (its `vicinities` map), not duplicated as independent mutable state on each cluster (clusters may cache derived `vicinity_id` / `is_vicinity_leader`).

---

## 3. Config (hand-specified only)

```yaml
topology:
  clusters:
    - id: c1
      servers: [...]
    - id: c2
      servers: [...]
    - id: c3
      servers: [...]

  vicinities:
    - id: v1
      members: [c1, c2]
      leader: c1
    - id: v2
      members: [c3]
      leader: c3
```

No `latency_ms`, no coords, no partition knobs.  
Building the world constructs `RootOrchestrator` from this block.

---

## 4. Validation rules

| Rule | Error if |
|---|---|
| Covering | Every cluster appears in **exactly one** vicinity |
| Non-empty | Each vicinity has ≥ 1 member |
| Leader ∈ members | `leader` must be listed in `members` |
| Unique ids | No duplicate vicinity id |

Feature gate: configs **without** `vicinities` stay valid until Topology v2 is required. When the block is absent, `World.root` may be `None` or an empty root (choose one in T1 and test it).

**Recommendation:** if `vicinities` is omitted → `root is None` and hierarchy APIs raise a clear error; if present → root is always built and validated.

---

## 5. Object model

| Type | Role |
|---|---|
| `Vicinity` | `id`, `member_cluster_ids`, `leader_cluster_id` |
| `RootOrchestrator` | Owns `vicinities`; query methods above; no Part A tick side effects |
| `World.root` | Optional/`RootOrchestrator` reference |

---

## 6. Env read APIs

Prefer delegating through the root so there is one path:

```text
Env.root -> RootOrchestrator | None

# convenience wrappers (optional but nice):
Env.list_vicinities()
Env.vicinity_of(cluster_id)
Env.leader_of(vicinity_id)
Env.is_leader(cluster_id)
Env.list_vicinity_members(vicinity_id)
```

---

## 7. What does not change

- Tick loop: trace → route → serve/drop → log  
- No cross-cluster request routing  
- No autoscaler / BEG behavior in Part A  
- Root is **not** called from `engine.tick` in this phase  

---

## 8. Milestones

| ID | Work | Exit |
|---|---|---|
| **T0** | Accept this plan | Review sign-off |
| **T1** | Config parse + validate `vicinities` | Reject fixtures + golden YAML |
| **T2** | `Vicinity` model + `RootOrchestrator` minimal class; `build_world` attaches `World.root` | Unit tests: covering, leader∈members, queries on root |
| **T3** | Env wrappers / read APIs over `root` | API tests; clear error if `root is None` |
| **T4** | Example config with static vicinities (e.g. extend `demo_60_two_clusters` or add 3-cluster fixture) | `run_env_only` green; root unused by tick loop but present in world |
| **T5** | Part B stub surface only: document / empty `NotImplementedError` placeholders on root for future `beg_*` (optional) | Importable; no call sites in Part A |

**Deferred:** latency matrix, algorithmic partition, BEVi/BEG logic, loans.

---

## 9. Part B preview

- BEVi: use `root.vicinity_of` / `leader_of` / members  
- BEG: implement on `RootOrchestrator` (or a plugin that *uses* root) in Part B — not now  
- Distance ranking: later extension when latency exists  

---

## 10. Review checklist

- [x] Static YAML vicinities + leader — accepted  
- [x] Minimal `RootOrchestrator` as topology owner (no Part A policy) — accepted  
- [x] No latency for now — accepted  
- [x] Tick loop does not call root — accepted  
- [x] Old configs remain valid until gated — accepted  

---

## Document history

| Version | Change |
|---|---|
| v1 | Broader draft (latency, partition algorithm, BEG helpers) |
| v2 | Simplified: static config; no latency |
| v3 | Explicit minimal `RootOrchestrator` step (T2) + role table; Env delegates to root |
