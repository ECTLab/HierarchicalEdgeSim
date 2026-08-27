# S7 — Hold-over-spike out; Kubernetes-style up vs down cooldown

**Status:** done (code + Alibaba re-run), including faster scale-down (`α_down = 1.0`, cooldown armed on Up only).  
**Branch:** `proactive-integration`  
**Front-end:** [s7-proactive-front-end.md](./s7-proactive-front-end.md)  
**Numbers:** [alibaba-tcn-s7-results.md](./alibaba-tcn-s7-results.md), [alibaba-tcn-ms150-results.md](./alibaba-tcn-ms150-results.md)

The point of the TCN is: look a few minutes ahead, add cores **before** a spike, and **give them back** when the quiet stretch is coming. This note is two steps:

1. Remove `hold_down_ticks` (a 55-minute “you were hot” freeze) and match Kubernetes **up vs down** cooldown.
2. Make shrink **fast** after that window (`α_down = 1.0`), so we do not walk down 10% stairs for half the valley.

---

## The problem with `hold_down_ticks`

**In one sentence:** after any busy moment, the scaler was forbidden to shrink for **55 minutes**, even if the next 54 minutes were quiet.

It did **not** start because we had just scaled. It started because the service looked “hot” (utilization, or the TCN’s guess, at or above 80%). Grow was still allowed. Only giving cores back was blocked.

**Why it existed.** MS_588 has a huge spike about every **60** minutes. The TCN only looks **5** minutes ahead, so it usually does not see that spike in time. After a spike the quiet period looks idle, the scaler shrinks, and the **next** hourly spike arrives with too few cores. `hold_down_ticks=55` was a patch: keep last hour’s extra machines until the next spike is due. 55 was chosen to cover almost the whole gap between spikes — not because Kubernetes (or anyone) uses a 55-minute cooldown.

**Why that is the wrong tool for “proactive.”**

We wanted: *the forecast says the load will fall, so release cores; the forecast says a spike is coming, so add cores now.*

What we actually did: *you were busy once, so keep spike-sized CPU for almost an hour no matter what the forecast says next.*

That is overprovisioning with a timer. You do not need a predictor for it. “Never shrink for 55 minutes after a busy period” would work the same on a purely reactive scaler. A fixed pool of ~14 cores would also have killed most MS_588 drops.

**What it looked like on the plots.** Drop rate looked excellent (**3.79%** vs reactive **15.44%**) because we were still carrying the spike’s cores through the valley. Quiet minutes only need about **2** cores to serve everyone; we kept about **14**. The green line on `cpu_needed_vs_provided.png` was a high floor, not “I saw the future and sized for it.”

Do not mix this up with **θ_target = 0.60**. That only means “aim to run about 60% busy,” which is a bit of spare **this minute**. It does not mean “keep last hour’s spike forever.”

MS_150 used the same 55-minute setting. That workload stays high and is not hourly, so the freeze was not doing the same “cover the next spike” job there.

---

## Kubernetes preferences (what we matched)

Kubernetes HPA v2 `behavior` is **asymmetric**. Defaults ([HPA concept](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/), [API](https://kubernetes.io/docs/reference/kubernetes-api/workload-resources/horizontal-pod-autoscaler-v2/)):

| Direction | Default | Meaning |
|---|---|---|
| **Scale-up** | `stabilizationWindowSeconds: 0` | If the metric says grow, grow **now**. No “wait until not in cooldown.” Rate limits (e.g. double pods / +4 per 15s) still apply. |
| **Scale-down** | `stabilizationWindowSeconds: 300` | Look at recommendations from the last **5 minutes** and keep the **highest** (do not strip on a brief dip). After that, a percent policy can remove a lot in 15s. |

Older docs also call the 5-minute down window `--horizontal-pod-autoscaler-downscale-stabilization` (default `5m`). KEDA’s `cooldownPeriod` (default 300s) is a related “wait before scale-to-zero,” not a 55-minute hot freeze.

What we did **not** copy from HPA (and then fixed for scale-down rate):

- HPA’s down window is a **recommendation history**. We approximate it as “no Down for `cooldown_C` after an **Up**.”
- Default scale-down **rate** after that window is 100% of pods per 15s. Alibaba TCN now uses `α_down = 1.0` and does not re-arm cooldown on Down. See below.

---

## Step 1 — How we tackled `hold_down_ticks`

Removed `hold_down_ticks`. If a YAML file still sets it, loading fails with an error so the old timer cannot sneak back in.

`cooldown_C` is **scale-down only**, like HPA’s 0s up / 300s down, and it is armed **after Up**, not after Down:

| After a successful apply | Scale-up | Scale-down |
|---|---|---|
| Before (with hold) | Blocked unless “hot” | Blocked for `cooldown_C` **and** 55 min if hot |
| After hold removal | Never delayed | Blocked for `cooldown_C` after **any** apply (10% stairs) |
| **HEAD** | Never delayed | Blocked for `cooldown_C` after an **Up** only; `α_down = 1.0` |

On Alibaba, 1 window = 1 minute, so `cooldown_C: 5` is the 300s down window. Cold-start (no hats yet) still uses the reactive `cooldown_ticks` on that path.

Decide is unchanged: Up if observed or any hat ≥ `θ_up`; Down only if **both** observed and all hats ≤ `θ_down`. The forecast still drives direction. Cooldown after Up only **delays the first shrink**.

| File | Change |
|---|---|
| `proactive_auto_scaler/params.py` | Drop the field; reject leftover YAML |
| `proactive_auto_scaler/policy.py` | `_next_down_window` on Up only; Down ignores it |
| `configs/demo_alibaba_proactive.yaml` | No hold; `α_down: 1.0`; K8s comments |
| `configs/demo_alibaba_ms150_proactive.yaml` | Same |
| `tests/test_proactive_auto_scaler.py` | Down waits after Up; Down may repeat; Up ignores cooldown |

---

## Step 2 — Faster resource removal (the 10% stairs)

After hold was gone, `serve_capacity.png` still walked down in **steps**: a small bite, a flat, another bite. That was **not** leftover `hold_down_ticks`. Two limits were still on:

1. **`α_down = 0.10`** — each Down could remove only 10% of current CPU.
2. **`cooldown_C` after every apply, including Down** — the next shrink waited until `τ+6`. The action log was full of 6-minute gaps.

Decide could already want the bottom of the stairs on the first quiet tick. The ladder only allowed one 10% step, then froze. That is a slow-motion hold: extra cores linger through most of the hour, so the next MS_588 spike does not start naked. Better drop numbers, wrong reason.

Kubernetes HPA scale-down is: wait **5 minutes** (stabilization), then a policy of **100% of pods per 15s period** ([HPA behavior](https://kubernetes.io/docs/concepts/workloads/autoscaling/horizontal-pod-autoscale/)). HEAD now matches that on the Alibaba TCN configs:

- After an **Up**, `cooldown_C=5` still blocks Down for 5 minutes (do not strip on a one-minute dip).
- Down does **not** restart that wait, so further shrinks can happen on the next ticks.
- `α_down = 1.0` lets one Down take the full decide residual (100% policy; one tick ≈ HPA’s 15s period on this 1-minute world).

`prefer_consolidate_down` still peels one replica vertically, then BEH may terminate extras on the **same** tick. On MS_588, shrink ticks are now ~60 minutes apart (one large cut per valley), not 6-minute 10% stairs.

---

## Numbers (same worlds, three TCN policies)

Headline drop, then drop after τ≥61 in parentheses (TCN has hats). Mean CPU is TCN after warmup. Reactive is unchanged across these runs.

| Policy | MS_588 drop (after τ≥61) | Mean TCN CPU | MS_150 drop (after τ≥61) |
|---|---|---|---|
| Hold 55 min (`42_20260816T104101Z`) | 3.79% (2.33%) | 14.2 | 4.40% (0.14%) |
| 10% stairs (`42_20260817T102407Z`) | 6.50% (5.31%) | 8.63 | 4.40% (0.14%) |
| **HEAD, K8s rate** (`42_20260817T105250Z` / `…T105251Z`) | **7.48% (6.38%)** | **7.42** | **4.71% (0.49%)** |
| Reactive | 15.44% (15.11%) | 3.24 | 5.51% (1.37%) |

Conservation still holds (trace = incoming = served + dropped).

Story plots: `results/alibaba_proactive/42_20260817T105250Z/analysis/story/` and `results/alibaba_ms150_proactive/42_20260817T105251Z/analysis/story/`. Start at `overview.png`. The serve-capacity panel is the one that showed the stairs.

---

## Why keep 100%, not the 10% cap

The **100%** version is the better controller. The 10% version had better drop numbers for the wrong reason.

- **10% + wait after every shrink** is still “don’t give cores back quickly.” You do not need a predictor for that. It is a milder `hold_down_ticks`.
- **100% after a 5-minute wait following Up** is what Kubernetes’s default scale-down **rate** is. If the forecast says quiet, go to the target.
- The extra ~1 pp drop on MS_588 (6.50% → 7.48%) and MS_150 after warmup (0.14% → 0.49%) is the cost of arriving at the next burst closer to valley size. The 5-step TCN still misses the hourly spike; slower shrink was a bandage for that miss.
- Mean TCN CPU after warmup: 14.2 (hold) → 8.63 (stairs) → **7.42** (HEAD).

If the goal is a lower Alibaba headline with *this* TCN, 10% “wins.” If the goal is “the forecast drives size, and cooldown matches HPA,” keep 100%. Fix later drops with a longer horizon / better hats, not by dripping 10% for half the valley.

