# Reactive scaler params (plain language)

These keys live under `autoscaler.params` for `reactive_vertical` and `reactive_local`. They answer three questions: **when** to move, **how big** a step, and **which replica** gets it. The window residual is not \(\alpha\)-clipped; see [25-allocate-resources.md](./25-allocate-resources.md).

Default demo values are below. Triangle configs 16–19 use `theta_high: 0.80` and `use_near_saturation_up: true` so the scaler and prefer-local routing share that bar. Toy tests may use smaller streaks/cooldowns.

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
| `theta_free` | Unused-headroom bar for down-pressure: slack ≥ `θ_free` × current serving μ. Also a shrink target: keep about `Λ / (1 − θ_free)` spare. On a **tiny** leftover that relative slack is not enough for M/M/1 p99 vs \(T_{\mathrm{slo}}\) (Λ=5 at 62% of μ=8 still has p99≈1.5 s). Leftover μ is then `max` of that, `min_mu_step`, and an absolute margin so p99 sojourn ≤ \(T_{\mathrm{slo}}/2\). |
| `theta_high` | Near-saturation bar. When `use_near_saturation_up` is true, scale-up can fire without drops. **Also** the prefer-local routing cap while this scaler is attached: home gets up to `theta_high · μ`, leftover goes to loans. |
| `use_near_saturation_up` | If `false`, up is **drops only**. `theta_high` still caps prefer-local routing. |

---

## How big a step

One scale-up tick is **one serving-μ step**, not two independent CPU and RAM wallets.

Dropped demand (or the decide residual) becomes a μ increment (`leftover / ρ_cpu`), then both resources move by `Δμ × ρ`. There is no \(\alpha_{up}\) fraction of current alloc. RAM is not grown toward `ram_max` on its own.

| Param | What it does |
|---|---|
| `min_mu_step` | Smallest serving-μ change that counts as a real step (`25` req/tick). On the triangle spec (`ρ_cpu=0.01`) that is `0.25` cores; RAM follows as `Δμ × ρ_ram`. Floor extras (μ=0) terminate because they add no μ. Surplus-down also **will not shrink the last replica below this μ** while load is live, so leftover is a real serving quantum rather than μ≈8. |

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
