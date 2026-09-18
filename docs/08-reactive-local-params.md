# Reactive scaler params (plain language)

These keys live under `autoscaler.params` for `reactive_vertical` and `reactive_local`. They answer three questions: **when** to move, **how big** a step, and **which replica** gets it. The window residual is not \(\alpha\)-clipped; see [25-allocate-resources.md](./25-allocate-resources.md).

Triangle demos use the values below. Toy tests may use smaller streaks/cooldowns.

```yaml
x_up_streak: 3
y_down_streak: 8
cooldown_ticks: 5
eps_drop: 1.0e-9
theta_free: 0.35
theta_high: 0.90
use_near_saturation_up: false
min_mu_step: 25
prefer_consolidate_down: true
grow_weights: { drop: 0.5, util: 0.3, room: 0.2 }
shrink_weights: { slack: 0.5, no_drop: 0.3, room: 0.2 }
```

`reactive_local` also has ladder keys (`sustained_up_streak`, `cascade_home`, …). Those are not in this glossary; see [12-s2-reactive-local-ladder.md](./12-s2-reactive-local-ladder.md).

---

## When to move

| Param | What it does |
|---|---|
| `eps_drop` | Treat drop totals smaller than this as **no drop**. Stops float noise from looking like a request was dropped. |
| `x_up_streak` | How many **consecutive** decision ticks with a real drop before scale-up. `3` means one isolated drop is ignored. |
| `y_down_streak` | How many consecutive ticks of **down-pressure** (enough unused serving headroom) before scale-down. Larger than `x_up_streak` so shrink is slower than grow. |
| `cooldown_ticks` | After a successful resize/spawn/terminate, skip further moves for this many ticks. With `y_down_streak: 8` and `cooldown_ticks: 5`, a lasting down-pressure run typically fires every **8** ticks after cooldown, not every 5. |
| `theta_free` | Unused-headroom bar for down-pressure: slack ≥ `θ_free` × current serving μ. Also sets the shrink target μ: keep about `Λ / (1 − θ_free)` so some spare stays. At `0.35` that is roughly 54% extra μ above live load. |
| `theta_high` | Near-saturation bar for an **optional** scale-up that does not wait for drops. |
| `use_near_saturation_up` | If `false` (all current demos), up is **drops only**. `theta_high` is unused until this is turned on. |

---

## How big a step

One scale-up tick is **one serving-μ step**, not two independent CPU and RAM wallets.

Dropped demand (or the decide residual) becomes a μ increment (`leftover / ρ_cpu`), then both resources move by `Δμ × ρ`. There is no \(\alpha_{up}\) fraction of current alloc. RAM is not grown toward `ram_max` on its own.

| Param | What it does |
|---|---|
| `min_mu_step` | Smallest serving-μ change that counts as a real step (`25` req/tick). On the triangle spec (`ρ_cpu=0.01`) that is `0.25` cores; RAM follows as `Δμ × ρ_ram`. Floor extras (μ=0) terminate because they add no μ — not because a leftover token was invented. Alloc still quantizes to `0.01`. |

Floors (`cpu_min`, `ram_min`) buy **no** throughput. Extra above the floor is what makes μ.

---

## Which replica

| Param | What it does |
|---|---|
| `prefer_consolidate_down` | If `true`, each down tick prefers to shrink **one** replica (often toward terminate) instead of peeling every replica a little. |
| `grow_weights` | Who receives extra first: more **drops**, higher **util**, more **room** to grow. Weights are `{drop, util, room}`. |
| `shrink_weights` | Who shrinks first: more **slack**, **no drops**, more **room** to shrink. Weights are `{slack, no_drop, room}`. |

---

## Defaults vs the plug-in plan

[07-autoscaler-implementation-steps.md](./07-autoscaler-implementation-steps.md) locks these numbers for tests and demos. The examples in [06-autoscaler-plug-in-plan.md](./06-autoscaler-plug-in-plan.md) (§6.8 / §7.1) are illustrative and may differ (`theta_free: 0.40`). Mechanism lives in the plan; **exact demo numbers** live here and in the implementation-steps table.
