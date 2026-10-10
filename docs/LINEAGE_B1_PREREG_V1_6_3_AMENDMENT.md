# Lineage B1 — v1.6.3 CORRECTIVE AMENDMENT: LAZY L4 INITIALIZATION

**Status: binding amendment.** Preserved unchanged:
* all prior amendments through v1.6.2 `b06cb48`;
* all prior implementation commits through `dbaa4b1`;
* all prior receipts (including consumed-root failure evidence).

No scientific design parameter is changed.

## Consumed root

Sizing root `2026100519000` is permanently consumed. Evidence:

* `b1_sizing_STARTED_20261009T214321Z.json`
  SHA256: `899e7a497adce102f9ad02e68d4489a7f683e5d3374a8475b66592ba5b1f3655`
* `b1_sizing_CRASHED_20261010T003748Z.json`
  SHA256: `84a760d39afa720a7de9e2c8bffed38414859fee9edc65e7d854be443d7d8518`

Stage A completed 300/300 deployments. SV1–SV4 passed (runner entered Stage B).
Stage B crashed after approximately 150 completed deployments.
No completed sizing result exists. No N was produced.

Exception: `RuntimeError: G0: theta changed during evaluation`

## Proven root cause

`SensorModel.__init__()` eagerly initializes only `{L1, L2, L3, F, P}`.
The channel creates `L4` only in C3 after `T_F` (`channel.py:50–52`).
During `evaluate_arm("G0", ...)`, a fresh `SensorModel()` is constructed
with no L4. The first C3 L4 observation triggers `_ensure("L4")`, adding
L4 to `b`, `sigma`, and `v`. Since `theta_hash()` hashes those
dictionaries, the hash changes despite zero learning. The crash occurs
exactly at the C2→C3 Stage-B boundary (task index 150 = first C3
deployment with `--workers 1`).

This is an implementation-validity failure, not a scientific B1 result.
The frozen-theta invariant performed correctly by detecting structural
mutation. No information from the partial Stage-B run may be used for
scientific inference or design tuning.

## Correction (v1.6.3)

### B1-local complete-schema construction

A `b1_sensor_model()` factory in `b1_protocol.py` materializes the
complete B1-visible independent-sensor schema (including L4) before theta
identity is ever frozen or receipted. All B1 ordinary `SensorModel`
construction sites use this factory:

* pass-1 G0 behavior agent
* `make_learner("G1")`, `make_learner("G2")`, `make_learner("G2-S")`
* fresh G0 in `evaluate_arm`
* fresh G0 in `ope_data`

`SensorModel` itself (shared B0 infrastructure) is not modified. G3
`DependencyModel` and REF-S `RefSensorModel` are not modified.

### Expanded validation coverage

A new validation check exercises the frozen-theta invariant for all
`SIZING_ARMS` on C3 through the actual `evaluate_arm` path used by
sizing. This directly covers the gap that allowed the bug to reach a
one-shot sizing run undetected.

## New roots

* new validation: `2026100520000`
* new sizing: `2026100521000`

Retired to disjointness set:

* `2026100516000` (v1.5.x sizing, consumed)
* `2026100517000` (v1.5.x validation, consumed)
* `2026100518000` (v1.6 validation, consumed)
* `2026100519000` (v1.6 sizing, consumed — this crash)

Confirmatory root `2026100514000` remains unchanged.

## What is NOT changed

* `B1_LOGGING_EPSILON = 0.5`
* B0 `params.EPSILON = 0.2`
* B0 `SensorModel` source code
* G1/G2/G3/G2-S algorithms
* max-mismatch sham
* SV1–SV4 definitions and thresholds
* DELTA_STAR, delta_null, safety margins
* predictor, authority, terminal authority
* sizing equations, N_min/N_max
* confirmatory analysis and root
