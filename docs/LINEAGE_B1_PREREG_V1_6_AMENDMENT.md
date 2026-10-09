# Lineage B1 — v1.6 EXPLORATION-POLICY AMENDMENT

**Status: binding amendment.** Preserved unchanged:
* sizing-design freeze `2473c2a`;
* first implementation `2206373`;
* v1.5.1 amendment `f4f5990`;
* corrective implementation `ac7ecf7`;
* v1.5.2 amendment `1e8bd91`;
* validation-attempt-1 implementation `3877889`;
* failed validation evidence `cff70ac`;
* v1.5.3 corrective validation-failure amendment `39313b6`;
* immutable seed-spec fix `b3f443c`;
* validation-attempt-2 PASSED `13c3472`;
* **sizing-attempt-1 STOPPED (SV3 failure) `5e5b82b`**.

All prior commits remain in history unchanged.

## Sizing attempt 1 result

* Root: 2026100516000 (consumed; must never be reused).
* Stage A: completed all 300 deployments (6 conditions x 50).
* SV1: PASS (all deployments).
* SV2: PASS (all deployments).
* **SV3: FAIL** — pooled mismatch fraction 0.583 < 0.80; minimum deployment
  fraction 0.436.
* SV4: PASS (mean KL 0.725 nats > 0.05).
* Stage B: **never reached**. No evaluation outcome was generated. No N was
  computed. No arm mean, effect estimate, or between-arm comparison exists.
* Receipts:
  - `b1_sizing_STARTED_20261009T163712Z.json`
    (sha256 `8a9f209cc6d41aa8f10eca3032e4cb6424ba8c8646d5440b1a6a22a7badbff5b`)
  - `b1_sizing_STOPPED_20261009T181653Z.json`
    (sha256 `b084de4ab6a6bc4414e0dad29e2984212dabee1cda323cdea219309f7a7b7ba7`)

## Interpretation

B1 v1.5.x did **not** falsify the action-conditioned-learning hypothesis. It
falsified the frozen sham/control design because the behavior log lacked
enough action diversity for an exact-marginal sham to satisfy SV3.

The structural reason is now mathematically clear. For the maximum-mismatch
exact-marginal sham, if the most common logged action occupies fraction
p_max of the DEFER steps, then:

    max_mismatch_fraction = min(1, 2*(1 - p_max))

Therefore SV3 >= 0.80 requires:

    p_max <= 0.60

The v1.5.x logging policy uses `EPSILON = 0.2`. At a DEFER step the G0
proposal is retained with probability `1 - EPSILON = 0.8`. If G0 proposes the
same action most of the time (which it does when the tank is near setpoint),
that one action can dominate the log near 80%, giving a theoretical sham
ceiling near 40%. The observed 58.3% is consistent with a **structural lack
of intervention diversity**, not a coding failure.

## What this amendment changes

Exactly one thing: the B1 learning-phase exploration rate.

### B1_LOGGING_EPSILON = 0.5

A new constant `B1_LOGGING_EPSILON` is introduced in `lineage_b/b1_protocol.py`.
It is used only for B1 `RecordingPolicy` construction and B1 provenance
validation. The shared frozen B0 constant `params.EPSILON = 0.2` is **not
modified**.

**Rationale from the design algebra, not from the observed 58.3%.** With four
actions and epsilon-greedy logging:

    P_logged(a) = epsilon/3 + q_a * (1 - 4*epsilon/3)

where q_a is the fraction of DEFER steps on which G0 proposes action a.

At `epsilon = 0.5`:

    P_logged(a) = 1/6 + q_a/3

Thus even if G0 proposes one action on every DEFER step (q_a = 1), that
action's expected logged marginal is `1/6 + 1/3 = 0.5`. This satisfies
`p_max <= 0.60` with structural margin. The choice comes from the feasibility
algebra, not from tuning to the sizing-1 result.

At `epsilon = 0.2` (v1.5.x): `P_logged(a) = 1/15 + 11*q_a/15`, giving
p_max = 0.8 when q_a = 1 — structurally impossible.

### Threading

`B1_LOGGING_EPSILON` is explicitly passed through:

1. `RecordingPolicy.__init__` — the `epsilon` argument (already supported by
   `LoggingPolicy.__init__`).
2. `behavior_records` — the `epsilon` argument (already has this parameter).
3. `verify_provenance` — propensity checks use the B1-specific epsilon.

The frozen B0 `LoggingPolicy` default remains `epsilon = 0.2`. No B0 code
path is modified.

### New seed roots

The consumed sizing root `2026100516000` and the used validation root
`2026100517000` are retired. Two new roots are assigned:

* **validation**: `2026100518000`
* **sizing**: `2026100519000`

Both are verified absent from the entire repository, all branches, all git
history, and the `_EARLIER` disjointness set. The confirmatory root
`2026100514000` remains untouched and has never been opened.

### Tests added

Seed-free synthetic tests proving:
* Proposal retention probability is exactly 0.5 at `epsilon = 0.5`
* Each alternative probability is exactly `1/6`
* Propensities sum to 1
* Provenance validation accepts v1.6 epsilon records
* Provenance validation rejects old-epsilon propensity records at v1.6
* B0 `LoggingPolicy` default remains `epsilon = 0.2`
* Max-mismatch formula and SV3 feasibility condition are unchanged
* `B1_LOGGING_EPSILON` produces feasible SV3 at worst-case concentration

## What is NOT changed

* G1/G2/G3/G2-S learning rules
* Maximum-mismatch exact-marginal sham construction
* SV1-SV4 definitions
* SV3 threshold = 0.80
* SV4 threshold = 0.05
* DELTA_STAR = 1.737 J
* delta_null = 0.8876 J
* delta_cond and safety margins
* Terminal authority
* B0 predictor (predictor.py at `94f4f11`)
* Sizing formulas (chi-square constants, N_min, N_max)
* Confirmatory analysis
* Confirmatory root `2026100514000`
* Frozen B0 `params.EPSILON = 0.2`
* Frozen B0 `LoggingPolicy` class
* All existing receipts, amendments, and evidence
