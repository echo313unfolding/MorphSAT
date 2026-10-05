# Lineage B0 v1.2 — Stopped at the implementation-only test (2026-10-05)

Prereg: B0 v1.2 `72e8925`. Implementation: `8b23ce5`, committed before
anything ran. Receipt: `receipts/lineage_b0/b0_v12_impl_FAIL_20261005T185858Z.json`.

**Status: STOPPED** under v1.2 Amendment 3 step 2: if (a) or (b) fails, stop
and report.
* **No validity gate has run** on v1.2 code or v1.2 seeds.
* The pilot has not run.
* B1 is unfrozen and unimplemented.

## Result

**(a) Equivalence: pass.** The banded kernel equals the v1.1 dense kernel,
max |Δ| = 0.0 at 100 bins (band 4) and at 400 bins (band 10).

**(b) Diffusion: fail.** The frozen pass rule was ratio ≥ 8 in every
scenario.

| Scenario (q = Q̄) | excess/step, 0.02 m | excess/step, 0.005 m | ratio | Pass |
|---|---|---|---|---|
| equilibrium, u = 0.5 | 2.03e-5 | 2.78e-6 | **7.32** | **no** |
| rising, u = 0.25 | 3.41e-5 | 3.32e-6 | 10.26 | yes |
| draining, u = 0.75 | 3.24e-5 | 1.91e-6 | 17.00 | yes |

For reference, W²/12 is 3.33e-5 at 0.02 m and 2.08e-6 at 0.005 m.

## Characterization (nothing changed; no rerun)

**The excess is lower in every scenario.** In all three, the 0.005 m grid
has 7–17× less excess variance per step. Its absolute excess,
1.9–3.3e-6 per step, sits near W²/12 for that grid.

**Why equilibrium misses 8.** In the near-zero-drift scenario the *coarse*
grid diffuses less than W²/12 (2.03e-5 against 3.33e-5): with σ_w = 0.1 W
and almost no drift, most mass stays in its own bin. The *fine* grid
(σ_w = 0.4 W) diffuses slightly more than W²/12. So the frozen "about 16×,
at least 8×" expectation, derived from pure W² scaling, did not hold in the
low-drift case. This is a mis-specification of the test's expectation by
the test's author (me). It is not, by itself, evidence of an implementation
error: (a) shows exact equivalence with v1.1.

**Monte Carlo noise.** The frozen test does not quantify the Monte Carlo
uncertainty of the ratio. How much of the 7.32 vs 8 miss is noise is
therefore not established.

**Relevance to gate 18 (not a prediction).** The residual numerical
diffusion at 0.005 m is still about 50–80% of the true process noise
σ_w² = 4e-6. At 0.02 m it was about 5–8×.

## Procedural record

* The pre-gate-commit slip from v1.1 remains in the record.
* This time, the doc freeze, the implementation commit and the first
  execution were in that order.
* The test criterion is not revised here. The grid is not changed.
* Whether to proceed to the gates is the user's decision.

## Disposition (addendum, 2026-10-05)

The user closed B0 v1.2 as an implementation-stage failure.

* The frozen ≥ 8 threshold is not lowered or reinterpreted.
* No v1.2 validity gate or pilot ran.
* Per the v1.2 contingency, the grid is not refined further.
* The next step is a new representation-class amendment, B0 v1.3
  (Gaussian per inflow/leak hypothesis). It starts as a candidate in
  `docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_3.md`.
* The record above is unchanged.
