# S3 — Ownership bookkeeping

**Status:** done  
**Branch:** `ladder-based-implementation`  
**Roadmap:** [proposed-implementation-roadmap.md](./proposed-implementation-roadmap.md) §3 S3  
**Paper:** RequestWorkerOwnerScale (Alg. owner) — worker-owner is the only writer; app-owner issues intents.

S3 does **not** place replicas on other clusters. It makes that later step safe: every scaler mutation goes through one authorized writer per worker.

---

## Model

| Field | Meaning |
|---|---|
| `App.owner_cluster_id` | Paper stamp: cluster that first hosted the app. Inferred at world build from the first live replica (sorted container id). |
| `Server.loans` | `L_j`: list of `LoanRecord(borrower_cluster_id, ms_id, tier, ts)`. Empty until S4 grants. |

`LoanTier` is `vicinity` or `global`. Helpers in `env/loans.py`: `add_loan`, `get_loan`, `has_loan`, `drop_loan`.

---

## Authorized mutation path

Physical ops stay: `Env.resize` / `spawn` / `terminate` (tests, world setup).

**Policy path:** `Env.request_worker_owner_scale(actor_cluster_id, act, …)`

Authorized if:

1. `actor_cluster_id == server.cluster_id` (worker-owner), or
2. a loan exists on that server for `(actor, ms_id)` (borrower intent)

Otherwise `NOT_AUTHORIZED` and no mutation.

`apply_actions` uses this path. Actor is `action.actor_cluster_id` if set, else the app owner of the microservice. Local S2 BEH still works because home cluster **is** the app owner.

On a successful borrower **terminate**, if that MS has no remaining instances on the worker, the loan record is dropped.

S4 will call `add_loan` when a vicinity/global grant is accepted; S3 only tests that the registry and auth honor an inserted loan.

---

## Tests

`tests/test_ownership.py`

- Owner stamp on `tiny.yaml` → `c1`
- Loan add / get / idempotent add / drop
- Owner can resize, spawn, terminate on own servers
- App owner spawn on a foreign server without loan → `NOT_AUTHORIZED`
- Worker-owner of the foreign server can still spawn (single writer is that owner)
- With a loan, borrower can spawn/resize/terminate; last borrowed instance drops the loan
- `apply_actions` infers app owner and rejects foreign spawn

```bash
python3 -m pytest tests/test_ownership.py -v
python3 -m pytest tests/ -q
```

---

## Out of scope (S4)

Vicinity leader grants, auto `add_loan` on remote spawn, Reserve/safe ceilings.

---

## Document history

| Version | Date | Note |
|---|---|---|
| v1 | 2026-08-15 | S3 owner stamp, loan registry, authorized mutation path |
