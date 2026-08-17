# S7 — Hold-over-spike out; Kubernetes-style up vs down cooldown

**Status:** done (code + Alibaba re-run). Scale-down **stairs** (`α_down` + `cooldown_C`) are next, not in this change.  
**Branch:** `proactive-integration`  
**Front-end:** [s7-proactive-front-end.md](./s7-proactive-front-end.md)  
**Numbers:** [alibaba-tcn-s7-results.md](./alibaba-tcn-s7-results.md), [alibaba-tcn-ms150-results.md](./alibaba-tcn-ms150-results.md)

The point of the TCN is: look a few minutes ahead, add cores **before** a spike, and **give them back** when the quiet stretch is coming. This note is what `hold_down_ticks` did instead, why that is not Kubernetes cooldown, what we changed, and what the new plots show.

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

What we did **not** copy from HPA (on purpose, next change):

- HPA’s down window is a **recommendation history**, not “after any apply, wait 5 min then bite 10%.”
- Default scale-down **rate** after the window can be 100% of pods in 15s. Ours is still `α_down = 0.10` per apply, then `cooldown_C` again. That is why μ walks down **stairs**. Out of scope here.

---

## How we tackled it

Removed `hold_down_ticks`. If a YAML file still sets it, loading fails with an error so the old timer cannot sneak back in.

`cooldown_C` is now **scale-down only**, like HPA’s 0s up / 300s down:

| After a successful apply | Scale-up | Scale-down |
|---|---|---|
| Before | Blocked for `cooldown_C` TTWs, unless “hot” bypass | Blocked for `cooldown_C`, **and** 55 min if hot |
| Now | **Never** delayed by `cooldown_C` (forecast may grow immediately) | Blocked for `cooldown_C` TTWs |

On Alibaba, 1 TTW = 1 minute, so `cooldown_C: 5` is the 300s down window. Cold-start (no hats yet) still uses the reactive `cooldown_ticks` on that path.

Decide is unchanged: Up if observed or any hat ≥ `θ_up`; Down only if **both** observed and all hats ≤ `θ_down`. The forecast still drives direction. Cooldown only **spaces** downs.

| File | Change |
|---|---|
| `proactive_auto_scaler/params.py` | Drop the field; reject leftover YAML |
| `proactive_auto_scaler/policy.py` | `_next_down_ttw`; Up ignores it |
| `configs/demo_alibaba_proactive.yaml` | No `hold_down_ticks`; comment on K8s windows |
| `configs/demo_alibaba_ms150_proactive.yaml` | Same |
| `tests/test_proactive_auto_scaler.py` | Down waits `cooldown_C`; Up does not |

---

## What the re-run showed

Same worlds as §B6 / §B7. Conservation still holds (trace = incoming = served + dropped).

| | MS_588 drop | After τ≥61 | Mean TCN CPU (τ≥61) |
|---|---|---|---|
| With hold (`42_20260816T104101Z`) | **3.79%** | 2.33% | 14.2 |
| **HEAD** (`42_20260817T102407Z`) | **6.50%** | 5.31% | **8.63** |
| Reactive (unchanged) | 15.44% | 15.11% | 3.24 |

MS_150 stayed **4.40%** / **0.14%** after τ≥61. The 55-minute freeze was not what held that plateau (load and hats stay high).

The first TCN spike is still a miss (τ=81: hat ~7.4k vs 29.8k incoming, 6.1 cores vs oracle ~13.9). Later spikes start poorer without the floor (τ=501: μ 16.5k vs 27.2k incoming). That is the honest trade: fewer idle cores in the valley, more drops on bursts the 5-step TCN does not see.

Story plots: `results/alibaba_proactive/42_20260817T102407Z/analysis/story/` (and the MS_150 twin). Start at `overview.png`.

---

## Next: the scale-down stairs

On `serve_capacity.png` the green μ line does not drop in one move after a spike. It **steps**: a bite, a flat, a bite, a flat.

That is **not** leftover `hold_down_ticks`. Two remaining limits:

1. **`α_down = 0.10`** — each Down may remove only 10% of current total CPU (and maybe terminate one floor replica on the same tick).
2. **`cooldown_C = 5`** — after that apply, the next Down is blocked until `τ+6`. The log is full of 6-minute gaps between shrinks.

The forecast can already want the bottom of the stairs on the first quiet tick; the ladder only allows one step, then waits. That family of rate-limit is reasonable (HPA has scale-down **policies** too). The **number** of steps is slower than default HPA (10% every 5 minutes vs a large cut after a 5-minute window). That is the follow-up: keep Kubernetes-style “don’t shrink on a one-minute dip,” without walking down a staircase for half the valley.
