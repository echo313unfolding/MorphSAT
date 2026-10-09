# Lineage B1 — v1.5.3 CORRECTIVE VALIDATION-FAILURE AMENDMENT

**Status: binding amendment.** Preserved unchanged:
* sizing-design freeze `2473c2a`;
* first implementation `2206373`;
* v1.5.1 amendment `f4f5990`;
* corrective implementation `ac7ecf7`;
* v1.5.2 amendment `1e8bd91`;
* validation-attempt-1 implementation `3877889`;
* failed validation evidence and receipt `cff70ac`.

The failed §7b attempt is **permanent evidence** and must never be replaced
or rewritten.

## Validation attempt 1 result

* Root: 2026100517000 (the only root opened).
* V0-static: **PASS** (predictor.py matches `94f4f11`).
* V0-runtime: **FAIL**: `RuntimeError: pass 2 diverged from the log at (0, 0)`.
* Gates 7, 11, 12: **not run** (the runner stops at the first failure).
* Receipt: `receipts/lineage_b1/b1_validation_FAILED_20261007T163340Z.json`
  (sha256 `082404d931b99b9725cfabd74785c8985667739bca99065fabd4642577d401d0`).

No sizing or confirmatory root was touched (2026100516000, 2026100514000).
No B1 scientific comparison, sizing variance, N, or F1–F6 result was observed.

## Cause

`lineage_b.world.make_streams(seed_seq)` calls `seed_seq.spawn(16)`. NumPy's
`SeedSequence.spawn` is **stateful**: each call advances
`n_children_spawned`, so a second `make_streams` on the same `SeedSequence`
object yields different streams.

B1 treated the episode `SeedSequence` objects returned by
`deployment_seeds()` as though they were immutable specifications. They are
not: each is a mutable object carrying internal state that changes on every
`spawn()` call. This caused pass 2 to execute a different world than pass 1,
and would have caused each evaluation arm to receive different exogenous
streams even when materialized from the same episode seed.

## Frozen rule (v1.5.3)

> **B1 episode seeds are immutable specifications.** Every world/stream
> materialization from an episode seed must reconstruct a fresh
> `SeedSequence` from the episode seed's `entropy`, `spawn_key` and
> `pool_size` before calling `make_streams`. The original `SeedSequence`
> object must never itself be consumed by `make_streams`.

The fresh reconstruction intentionally begins with zero spawned children.
`n_children_spawned` is deliberately **not** propagated.

## Centralized helper

One B1-side helper (`b1_make_streams` in `lineage_b/b1_seeds.py`) implements
this rule. It is the sole path from episode seed to streams for all B1 code:

```python
def fresh_seedsequence(ss):
    return np.random.SeedSequence(
        entropy=ss.entropy,
        spawn_key=ss.spawn_key,
        pool_size=ss.pool_size,
    )

def b1_make_streams(ss):
    return make_streams(fresh_seedsequence(ss))
```

**Every B1 materialization must use it:**
* pass 1;
* pass 2;
* G0 evaluation;
* G1 evaluation;
* G2 evaluation;
* G3 evaluation;
* G2-S evaluation;
* REF-S evaluation;
* REF-Z evaluation;
* validation replay paths;
* poisoned/replayed validation paths;
* confirmatory stage-A/stage-B replay paths.

**Mechanical enforcement.** A source-level test verifies that no B1 file
(except `b1_seeds.py` itself) imports or calls `make_streams` directly. Only
`b1_make_streams` is permitted at B1 call sites.

## What is NOT changed

* Frozen B0 `world.make_streams` is not modified.
* B0 gates, receipts, results and code are not modified.
* No hypothesis, arm, margin, endpoint, sham criterion, sizing formula,
  analysis rule, seed root or B0 artifact is changed.
* The sizing-design freeze `2473c2a` and all earlier commits remain in
  history.

## Re-validation

Validation attempt 2, when authorized, may reuse root 2026100517000 because
frozen §7b explicitly permits re-validation after a disclosed corrective
implementation commit.

The original FAILED receipt remains permanent and must never be replaced or
rewritten.
