# Lineage B0 v1.3 — Results (2026-10-06)

Preregs: v1.3 `701c4c2` + v1.3.1 `ebdb0f1`. Implementation `94f4f11`.
Implementation-only receipt `944db55`. Validity receipt
`receipts/lineage_b0/b0_validity_PASSED_20261006T190325Z.json`
(sha256 `268d9c53…5ee003`).

**Status: B0 PASSED.**
* All validity gates (1–16, 18, 19) passed on the first and only run, on B0
  root 2026100515000.
* The gate-17 pilot then ran on root 2026100513000.
* No code changed between the implementation commit and either run.
* B1 is unfrozen and unimplemented.

## Sequence

1. v1.3 frozen (`701c4c2`); T6 amendment v1.3.1 frozen (`ebdb0f1`).
2. Implementation committed before any execution (`94f4f11`). Pre-commit
   execution was limited to compile/import and one shape/finiteness smoke
   call on arbitrary inputs.
3. R1–R5, then T1–T8: one run, all PASS. Receipt committed before any gate
   (`944db55`).
4. All validity gates: one run, all PASS. The pilot followed in the same
   run.

## Gate 18 (unchanged criterion: cov90 ∈ [0.85, 0.95], cov50 ∈ [0.40, 0.60])

Setup: C0, μ behaviour, θ0, 20 deployments, n = 3980 per sensor.

| Sensor | cov90 | cov50 | mean PIT | v1.1 cov90 / cov50 |
|---|---|---|---|---|
| L1 | 0.9309 | 0.5482 | 0.501 | 0.952 / 0.586 |
| L2 | 0.9307 | 0.5477 | 0.507 | 0.959 / 0.587 |
| L3 | 0.9314 | 0.5490 | 0.506 | 0.959 / 0.590 |
| F | 0.9246 | 0.5342 | 0.507 | 0.932 / 0.548 |
| P | 0.9188 | 0.5299 | 0.500 | 0.944 / 0.566 |

* All sensors pass.
* The smallest margin is L3 cov90: 0.9314 against the 0.95 bound (0.019).
* The level sensors moved from outside the bound (0.952–0.959) to about
  0.931, under the same criterion.
* **Observation, not a criterion:** coverage remains above nominal for every
  sensor (cov90 0.92–0.93, cov50 0.53–0.55). Some under-confidence
  therefore persists, within the frozen range. No cause has been tested; P1
  and P4 (v1.3 §0.3) are untested candidates.

## Other gates

* **Gate 4:** corr(L1 err, L2 err) = 0.4933. Target 0.5, SE 0.0051 (1.3 SE);
  n = 22,000; the C2 shift is exact.
* **Gate 5:** the largest stray \|corr\| is 0.00851 (L1–F), against a limit of
  3/√N = 0.02023. In v1.1 it was 0.0197 against 0.0202.
* **Gate 13 KL (nats):** L3 0.23 / 0.46 / 0.69 and F 485 / 689 / 689 at
  h0 = 0.5 / 1.0 / 1.5. The threshold is 0.05.
* **Gates 1–3, 2b, 6–12, 14–16, 19:** PASS. Details are in the receipt.

## Gate 17 pilot (sizes N only; no G1/G2/G3/G2-S code exists or ran)

| Condition | mean J G0 | var J G0 | mean J REF-S | gap (G0 − REF-S) |
|---|---|---|---|---|
| C0 | 44.38 | 416.8 | 47.83 | −3.45 |
| C1 | 68.04 | 1418.8 | 45.83 | 22.20 |
| C2 | 72.51 | 1178.8 | 49.80 | 22.71 |
| C3 | 86.58 | 755.3 | 44.68 | 41.90 |
| C4 | 50.24 | 202.5 | 48.36 | 1.88 |
| C5 | 48.66 | 515.3 | 50.51 | −1.85 |

* Pooled fault gap (C1–C5): 17.37.
* **N_required = 1659, above the frozen cap N_max = 200.** The frozen rule
  therefore yields N_frozen_for_B1 = 200, the cap.
* By the pilot's own formula, B1 at N = 200 has a detection margin about
  √(1659/200) ≈ 2.9× wider than the formula targets. The B1 power and
  design implications are a user decision, not made here.
* The negative gaps in C0 and C5 are within pilot noise. For C0 the SE of
  the mean J is ≈ √(417/20) ≈ 4.6.

## Implementation-only results (receipt `944db55`)

* **R1–R5:** max error 2.2e-16 against limits ≥ 1e-14.
* **T6:** 49,005 points, 0 failures, 0 reference failures.
  * Worst mean discrepancy 6.7e-12 m, 0.44% of its per-point limit.
  * Worst variance discrepancy 3.2e-12 m², 0.08% of 4.0e-9 m².
  * The reference used at most 29 subintervals, depth 11.
  * The receipt records worst magnitudes and ratios but **not** the fixture
    coordinates (m, σ, u, leak, q) where they occurred. That is a receipt-design
    gap; the coordinates were not recovered because recovering them would
    re-execute T6.
* **T2:** relative variance error 2.2e-5 and mean drift 2.0e-5 m. This
  matches the frozen analytic prediction (≈ 1e-5 / 2e-5); the limits are
  1e-4.
* **T1:** max error 0. No world leak onsets occurred in the fixtures.
* **T3:** max v 2.8e-31; no monotonicity violations.
* **T4:** 13,514 updates; normalization error ≤ 4.4e-16; no underflows.
* **T5:** relative error ≤ 5.9e-15.
* **T7:** relative error ≤ 4.6e-16.
* **T8:** dE ≤ 2.8e-10 m, dV ≤ 1.4e-12 m².

## Procedural record

* The v1.1 pre-gate-commit slip remains permanently disclosed.
* v1.2 closed at its implementation-only test.
* The v1.3 T6 defect was found before implementation and fixed by
  amendment v1.3.1.
* In this run, freeze, implementation commit, implementation-test receipt,
  gate run and pilot happened in that order, each once.
