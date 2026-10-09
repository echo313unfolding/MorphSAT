# Lineage B0 — Gate 17 CRN deviation disclosure

**Status: permanent, append-only disclosure.** B0 code and results are not
modified. The original B0 results commit is preserved unchanged.

## The intended design

Gate 17 (`lineage_b/gates.py:564–599`) is the B0 sizing pilot. It evaluates
G0 and REF-S on evaluation episodes for each condition and deployment. The
design intended G0 and REF-S to share **common random numbers** (CRN): each
arm evaluating the same episode should run on identical exogenous streams, so
the paired difference G0 − REF-S has reduced variance.

## What actually happened

In `g17_pilot()`, each `(condition, deployment)` gets one set of episode
`SeedSequence` objects via `episode_seeds()`. The evaluation loop
(`gates.py:577–587`) iterates over arms in order `("G0", "REF-S")`, and for
each arm iterates over the evaluation episodes calling
`make_streams(eps[ep])`.

Because `SeedSequence.spawn()` is stateful (it increments
`n_children_spawned` on each call), the sequential calls produce:

* **G0**: `make_streams(eps[ep])` — first spawn, children (0,)…(15,).
* **REF-S**: `make_streams(eps[ep])` — second spawn, children (16,)…(31,).

Therefore **Gate-17 G0/REF-S evaluations were not CRN-paired.**

## Impact assessment

1. **Per-arm means are unbiased.** Each arm was evaluated from its intended
   distribution. The defect removes the intended variance reduction (pairing),
   not the validity of the per-arm expected values.

2. **B0 validity gates 1–16, 18 and 19 are unaffected.** These gates either
   create a fresh `SeedSequence` per call or do not rely on CRN.

3. **B0 remains CLOSED / PASSED.** Gate 17 is a sizing pilot, not a
   simulator-validity gate.

4. **The old Gate-17 `N_required = 1659` is not used as B1's confirmatory N.**
   B1's frozen §7a explicitly replaces that conservative pilot bound with
   blinded empirical paired-difference variance sizing.

5. **`delta_null = 0.8876 J`** derives from the G0 C0 mean alone and is
   unaffected by G0/REF-S pairing.

6. **`DELTA_STAR = 1.737 J`** remains frozen for this B1 as the
   preregistered 10%-of-pilot effect-size anchor, derived from the original
   17.37 J pilot difference of means. That estimate is noisier than intended
   because CRN was absent, but it remains an independently obtained pre-B1
   anchor. It is **not recomputed or altered**.

## What is NOT done

* B0 code is not modified.
* The B0 pilot is not re-run.
* `DELTA_STAR` and `delta_null` are not changed.
* A corrected paired B0 pilot may be run **only after B1 is completely
  closed**, as a post-hoc replication/diagnostic. It may not retroactively
  redefine this B1's `DELTA_STAR`.
