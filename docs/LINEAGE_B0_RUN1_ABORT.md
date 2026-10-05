# Lineage B0 — Run 1 aborted at gate 18 (2026-10-05)

Prereg: B0 v1.1 `642d3fd` (frozen). Receipt:
`receipts/lineage_b0/b0_validity_ABORTED_20261005T060136Z.json`. Status **ABORTED**: 18 of 19 run gates pass;
**gate 18 (nominal predictor calibration) fails**. Gate 17 (pilot) was not
run. No B1 arm (G1/G2/G3/G2-S) exists in code; no B1 outcome exists.

## Procedure disclosure

* B0 §8 step 2 says to commit the implementation before running any gate.
  I ran the gate tests once before the first commit. That run: gates 1–5
  passed, then gate 6 failed (pytest `-x`).
* The code as first exercised is committed as `5b8f965`, with that
  disclosure in its message.
* **Fix 1 (gate 6), its own commit.** `SensorModel` initialized sensors
  lazily, so `theta_hash` changed on first use without any update. Fixed by
  eager initialization of the base sensors.
* A second development run then showed gate 18 failing. The official run
  (this receipt) reproduces exactly that.
* No other code change was made after any gate result.

## Gate 18 result (C0, μ behaviour, θ0, 20 deployments, B0 seeds)

Range required: cov90 ∈ [0.85, 0.95] and cov50 ∈ [0.40, 0.60].

| Sensor | cov90 | cov50 | mean PIT | E[r²] / predicted var |
|---|---|---|---|---|
| L1 | **0.952** | 0.586 | 0.498 | 0.79 |
| L2 | **0.959** | 0.587 | 0.495 | 0.77 |
| L3 | **0.959** | 0.590 | 0.500 | 0.75 |
| F | 0.932 | 0.548 | 0.505 | 0.98 |
| P | 0.944 | 0.566 | 0.499 | 0.83 |

The predictor is **unbiased but under-confident** for the level sensors.
Their predictive variance is overstated by about 20–25%.

## Diagnosis (characterization only; nothing changed)

About half of the level predictive variance is the filter's own uncertainty
about h. The frozen grid (§7: h in 100 bins of 0.02 m) re-spreads mass
uniformly within each bin at every transition. That adds roughly
w²/12 ≈ 3.3e-5 m² per step of purely numerical diffusion, about 8× the true
process noise σ_w² = 4e-6. Flow, whose latent share is about 2%, is well
calibrated, which is consistent with this explanation.

## Why it matters for B1 (and why the range should not just be widened)

G2's noise update is `σ² = v − s²_ref`. If the latent predictive variance
`s²_ref` is overstated, G2 underestimates sensor noise and may clamp at
σ_min. That is exactly the "compensating for a bad predictor" confound the
gate exists to exclude. G1's reference variance has a different origin, so
the bias would not be matched across arms.

## Other gates (all pass; details in the receipt)

* Mass balance exact to 2e-16, with the spill and shortfall branches hit.
* Replay and common random numbers hold.
* L1–L2 error correlation is 0.502 (target 0.5, SE 0.005).
* Largest stray correlation is 0.0197 against a limit of 0.0202. This is
  close to the bound, as 3/√N over 9 pairs makes plausible.
* Separation holds: the replay and NaN-poisoned replay are identical while
  the hidden worlds differ.
* Interlock and terminal-abstain paths are exercised and θ-blind.
* `terminal_authority.py` is unchanged versus `eb3f6d3`.
* Action-sensitivity KL: L3 0.22–0.66 nats, F 138–689 nats.
* 25/25 redeliveries counted once.
* 1,144 FeedbackRecords recompute exactly.

## Status

B0 not passed. A §7 amendment needs the user's decision. B1 stays
unfrozen.
