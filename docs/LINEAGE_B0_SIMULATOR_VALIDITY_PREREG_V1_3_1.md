# Lineage B0 — Preregistration v1.3.1: T6 amendment (CANDIDATE — not frozen)

Status: **candidate; pre-implementation amendment to v1.3.**
* Applies to v1.3 (`docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_3.md`),
  FROZEN @ `701c4c2`. That commit is not rewritten.
* This amendment changes **only T6**, in Amendment 3 of v1.3.
* Everything else in v1.3 stays in force, including D1–D3, seeds, §0–§1,
  T1–T5, T7, T8, gate 18 and the procedure.
* **Implementation is on HOLD** until this amendment is frozen (user
  decision, 2026-10-06).
* No v1.3 code exists. Nothing has been executed. No quadrature value was
  computed in preparing this amendment.

## Why

**1. Coverage gap** (disclosed at the v1.3 freeze as a known limitation).
The predictor propagates the variance of the one-step deterministic map.
With α = dt/A:

  Var[μ(h)] = Var[h] + α²c²·Var[√h] − 2αc·Cov(h, √h).

The frozen T6 checks E[√h] and Var[√h] but not Cov(h, √h), so it does not
validate the GH20 variance actually propagated.

**2. Domain defect in the frozen T6** (found while deriving this amendment;
analysis only).
* The frozen T6 justification says "the integrand is analytic where weight
  > 1e-12". This is false at the domain corner m = 0.3, sd = 0.05.
* There h = 0 is only 6 sd away. Φ(−6) ≈ 1e-9 of the Gaussian mass lies at
  h < 0, where √max(h, 0) is not analytic.
* Two of the 20 GH20 nodes fall below 0 (standardized nodes ≈ −7.6 and
  −6.5).

Series estimate. Write √(m + sd·z) = √m·√(1 + (sd/m)z). GH20 is exact for
polynomials of degree ≤ 39. The first neglected term is about
binom(½, 20)·(sd/m)^40·E[z^40] ≈ 0.004·√m·39!!/(m/sd)^40.
* At m/sd = 6: ≈ 5e-11, plus a non-analytic contribution of order Φ(−6).
  The 20-vs-100-point difference there can therefore plausibly exceed 1e-10.
* At m/sd = 10: ≈ 1e-19, and the non-analytic mass is Φ(−10) ≈ 8e-24.

The frozen T6 domain was also never discretized; it gave only intervals.

## Amendment T6 (replaces v1.3 T6)

**Fixture grid (both parts).**
* m ∈ {0.30, 0.35, …, 1.90}: 33 values.
* sd ∈ {1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2}.
* Keep only pairs with **m/sd ≥ 10**.

Why that domain:
* The largest standardized GH20 node is ≈ 7.6 < 10. Every GH20 node is
  therefore at h > 0, and the series bound above holds.
* GH100 nodes beyond z = 10 carry weight < 1e-20.
* The domain covers every belief fixed in v1.3: the initial belief
  (m/sd = 20) and the gate-13 fixtures (m/sd ≥ 10).
* It also covers the operating regime. Interlock bounds m ≥ 0.3, and the
  posterior sd ≈ 0.01, giving m/sd ≈ 30.
* Beliefs with m/sd < 10 arise only near h = 0, below the interlock. Their
  closure accuracy is **not** validated by T6. This is a disclosed
  limitation.

**T6(a): √h moments (retained).**
* E[√h] and Var[√h], GH20 against GH100, on the grid.
* Criterion unchanged: \|Δ\| ≤ 1e-10 (m^½ and m respectively).

**T6(b): complete one-step deterministic map (new; user-specified).**
* Quantity: μ(h) = h + α(q − c·√max(h, 0)), without process noise and
  without clipping. Noise adds σ_w² exactly. The clip and censored moments
  are covered by T1, T3 and T8.
* Compare GH20 against GH100, both computed exactly as §1.3(a) computes
  them, on the grid:
  * the mean, Σω μ(h_k);
  * the variance, Σω (μ(h_k) − mean)² (the stable centred form).
* All c = Cv·u + k(ℓ) for u ∈ U_LEVELS and ℓ ∈ {none, slow, fast}
  (15 values; c_max = 0.13).
* All q ∈ QG (11 values).

T6(b) criterion:
* \|ΔE[μ]\| ≤ **1.3e-11 m**;
* \|ΔVar[μ]\| ≤ **2.8e-11 m²**.

**Derivation of the T6(b) tolerance.** These are not new numbers. They
carry the frozen 1e-10 per-quantity budget into level units:
* q enters μ as the additive constant αq. It is exact in the mean, up to
  rounding, and cancels from the variance.
* Mean: \|ΔE[μ]\| = αc·\|ΔE[√h]\| ≤ 1·0.13·1e-10 = 1.3e-11 m. That is
  6.5e-9 of σ_w = 2e-3 m.
* Variance: a 1e-10 budget each on Var[√h] and on Cov(h, √h) (in m^{3/2})
  gives \|ΔVar[μ]\| ≤ 2αc_max·1e-10 + α²c_max²·1e-10 = 2.6e-11 + 1.7e-12
  ≤ 2.8e-11 m². That is 7e-6 of σ_w² = 4e-6 m², the variance added every
  step.
* Var[h] is exact under both rules (degree 2), so it contributes rounding
  only.
* Rounding: means are ≈ 2 m, so 20 terms give ≲ 1e-14 m. The variance uses
  the centred form, so rounding is ≈ ε·Var. Both are far below the
  criteria.

**Pass:** T6(a) and T6(b) hold at every grid point. Any failure means stop
and report. The criteria are not adjusted after execution.

## Procedure

1. The user freezes this amendment.
2. Then the v1.3 procedure (Amendment 4) resumes from its step 2, with T6
   as defined here.
