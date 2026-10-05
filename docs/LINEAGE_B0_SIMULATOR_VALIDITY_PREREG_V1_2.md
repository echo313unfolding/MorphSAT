# Lineage B0 — Simulator Validity: Preregistration v1.2 (FROZEN; amendment to v1.1)

Status: **amendment to v1.1** (`docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1.md`
@ `642d3fd`), authorized by the user on 2026-10-05 after run 1 aborted at
gate 18. Everything in v1.1 that is not amended here stays in force
unchanged. B1 stays unfrozen and unimplemented.

## Audit trail

| Commit | What |
|---|---|
| `c57185c` | B0 v1.0 candidate |
| `642d3fd` | B0 v1.1 FROZEN |
| `5b8f965` | Implementation as first exercised |
| `1471e2e` | Fix 1: eager `SensorModel` init (gate 6) |
| `c3996e7` | Run 1 ABORTED at gate 18. Receipt `receipts/lineage_b0/b0_validity_ABORTED_20261005T060136Z.json` |
| `3d9529b` | Run-1 note fix (`docs/LINEAGE_B0_RUN1_ABORT.md`) |

**Permanent procedural record.** v1.1 §8 step 2 required committing the
implementation before running any gate. The gate tests were run once before
the first commit. That run: gates 1–5 passed, gate 6 failed. It is disclosed
in `5b8f965` and in the run-1 note. It does not by itself invalidate B0, but
it stays in the provenance chain of every later B0 result.

## Amendment 1 — Level-grid resolution (amends v1.1 §7 and `params.NH`)

**Rationale.** B0 v1.1 failed because the 0.02 m discretization introduced
excess numerical diffusion into an otherwise unbiased nominal predictor. B0
v1.2 changes only the numerical resolution of the frozen level-grid
representation from 0.02 m to 0.005 m. The predictor equations, information
boundary, world model, calibration bounds and validity criteria remain
unchanged.

| Item | v1.1 | v1.2 |
|---|---|---|
| h grid of the §7 filter | 100 bins × 0.02 m | **400 bins × 0.005 m** |
| q_in grid, leak states | 11, 3 | unchanged |
| h-transition kernel | dense `K[u, q, ℓ, from, to]` | **banded form of the same kernel** (below) |

**Banded kernel (computational form only).** The kernel formula is the v1.1
one: the §3 mean at 8 uniform sub-points per from-bin, Gaussian `σ_w`, and
tails clipped into the end bins. Each row stores only the to-bins within
±10 σ_w of its sub-point means. The dropped mass is < 1e-22 per row, and
under the frozen `ncdf` those entries are exactly 0 in the dense kernel
anyway. The prediction step is the same sum, `Σ_h B[h,q,ℓ] K[q,ℓ,h,k]`,
evaluated by scatter-add.

**Pre-freeze disclosure.** Before this freeze I checked the banded kernel
against the v1.1 dense code. Max |Δ| was 0.0 at both 100 and 400 bins
(band widths 4 and 10). I also timed a step on a synthetic belief (~10.5 ms
at 400 bins). No seed, episode, gate or calibration quantity was computed.

**Unchanged, explicitly.**
* The §3 transition equations.
* Process noise σ_w, σ_η and the q_in AR(1).
* Sensor-noise specifications, nominal θ0 and the sensor-model form.
* The within-bin variance term `W²/12`. Its formula is unchanged; its value
  follows W.
* The §1 information boundary.
* World, sensors, channel, faults and the authority layer.
* The receipt scoring bins (`BIN_EDGES`: level 0.02 m, pressure 0.1962 kPa,
  flow 0.003).
* Every gate's test and threshold, including gate 18's ranges
  (cov90 ∈ [0.85, 0.95], cov50 ∈ [0.40, 0.60]) and gate 5's 3/√N.

## Amendment 2 — Seed roots (amends v1.1 §11)

**Disclosure (v1.1 defect).** Several gates seed from `B0_SEED + k` with
k ∈ {0, 1, 2, 3, 7, 11, 12, 21, 22, 100, 999}. Gate 2 used k = 1 and k = 2,
i.e. 20261006 and 20261007: exactly the v1.1 pilot and B1 roots. That gate
consumed, at deployment key 0:
* the world streams of pilot deployment 0 / C0;
* the world streams of B1 deployment 0.

Only replay-hash equality was checked; no J, score or outcome was computed.
The v1.1 claim "spawned children are disjoint" was therefore false.

| Purpose | v1.1 root | v1.2 root |
|---|---|---|
| B0 gates | 20261005 | **2026100512000** (offsets used: +0 … +999) |
| pilot (gate 17) | 20261006 | **2026100513000** |
| B1 | 20261007 | **2026100514000** |

* The roots are 1000 apart, so no B0 offset can reach the pilot or B1 root.
  `gates.py` asserts this at import time.
* All three roots are replaced. The user chose to replace the pilot and B1
  roots too; neither had run.
* **v1.1 reproduction set.** Root 20261005 with the code at `3d9529b`
  reproduces the run-1 failure. Nothing in v1.2 uses it.

## Amendment 3 — Procedure for this run (restates v1.1 §8; adds an implementation-only test)

1. Commit this document. Then commit the implementation, before any gate or
   implementation-only test runs.
2. **Implementation-only test.** `tests/test_lineage_b0_v12_impl.py`
   uses no B0, pilot or B1 seeds. It has two parts:
   * **(a) Equivalence.** The banded kernel equals the v1.1 dense kernel,
     max |Δ| ≤ 1e-12, at 100 and 400 bins.
   * **(b) Diffusion.** Setup: an open-loop h-transition at q = Q̄ (nearest
     q grid point), no leak, h0 ~ N(1, 0.05²), over 20 steps. Three
     scenarios: u ∈ {0.5, 0.25, 0.75}. The reference is a 2·10⁶-particle
     Monte Carlo of the §3 dynamics (MC seed 120512, evaluator-only). Excess
     variance per step is the grid variance growth minus the MC variance
     growth. **Pass:** in every scenario, excess(0.02 m) > 0 and
     excess(0.02 m) / excess(0.005 m) ≥ 8. W² scaling predicts 16.

   The test verifies the implementation only. **It is not used to choose or
   tune the grid.** If (a) or (b) fails, stop and report.
3. Run **all** validity gates (1–16, 18, 19) **once**, on the v1.2 B0 root.
   This writes a receipt.
4. If any gate fails: **stop**. In particular, gate 5 is not relaxed if its
   near-threshold correlation crosses 3/√N on the new seeds.
5. Only if every gate passes, run the gate-17 G0 / REF-S variance pilot on
   the v1.2 pilot root.
6. **Stop.** Do not freeze or implement B1.

**Contingency, frozen now.** If gate 18 still fails, the grid is not refined
further: no 0.0025 m and no other resolution. The grid-filter
representation itself then becomes questionable. A Gaussian alternative
would be considered only under a separately frozen amendment.

## Implementation consequence

* `lineage_b/params.py`: `NH = 400`.
* `lineage_b/agent/predictor.py`: banded `h_kernels()` / `apply_band()`
  replace the dense kernel and its einsum.
* `lineage_b/gates.py`: v1.2 seed roots and the disjointness assertion.
* `tools/run_lineage_b0.py`: the receipt cites v1.2 and records the Python
  and numpy versions.
* `tests/test_lineage_b0_v12_impl.py` and `tools/run_lineage_b0_v12_impl.py`:
  the Amendment 3 step 2 test and its receipt.
