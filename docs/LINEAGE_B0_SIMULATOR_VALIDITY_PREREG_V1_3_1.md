# Lineage B0 — Preregistration v1.3.1: T6 amendment (CANDIDATE r2 — not frozen)

Status: **candidate; pre-implementation amendment to v1.3.**
* Applies to v1.3 (`docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_3.md`),
  FROZEN @ `701c4c2`. That commit stays permanently frozen and is not
  edited. Its T6 text remains the historical record.
* This amendment **supersedes only T6** in v1.3 Amendment 3. Everything
  else in v1.3 stays in force, including D1–D3, seeds, §0–§1, T1–T5, T7,
  T8, gate 18 and the procedure.
* **Implementation is on HOLD** until this amendment is frozen.
* No v1.3 code exists, and T1–T8 have not been implemented or executed.
* No quadrature or integration value was computed in preparing this
  amendment.
* Candidate r1 (`dca71bc`) is superseded by this r2.

## Why T6 is superseded

Frozen T6 assumed analyticity over all probability mass above 1e-12. At the
preregistered corner m = 0.3, σ = 0.05, about 9.87e-10 of the probability
lies below h = 0, across the kink in √max(h, 0). T6 also omitted the
covariance term required for the variance of the complete nonlinear
transition. These defects were found before implementation or execution of
T1–T8. T6 is therefore superseded by an independent-reference test of the
complete deterministic transition moments.

A second GH rule (GH100) is not an adequate reference at the kink: it is
the same quadrature family applied across the same non-analytic point.

## Roles

* **GH20 (§1.2):** the predictor's approximation. Unchanged.
* **Independent adaptive integral (below):** the validation reference only.
* **T6 (new):** does GH20 introduce negligible error in the propagated mean
  and variance of the deterministic step?
* **T8:** remains responsible for the process-noise / clipping
  (censored-moment) calculation.

## T6 (replaces v1.3 T6)

### Quantity

The complete deterministic one-step map, without process noise and without
clipping:

  f(h) = h + α(q − c·√max(h, 0)),  α = dt/A = 1.

For H ~ N(m, σ²), compare **E[f(H)]** and **Var[f(H)]**:
* by GH20, computed exactly as §1.3(a) computes them. That is
  Σ ω_k f(h_k), and Σ ω_k (f(h_k) − mean)²;
* against the reference below.

This exercises E[√H₊], Var[√H₊] and Cov(H, √H₊) in exactly the combination
the predictor uses. No separate covariance check is needed.

### Fixture grid (the frozen T6 domain, made explicit)

* m ∈ {0.30, 0.35, …, 1.90}: 33 values.
* σ ∈ {1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2}: 9 values.
* c = Cv·u + k(ℓ) for u ∈ U_LEVELS and ℓ ∈ {none, slow, fast}: 15 values,
  c ∈ [0, 0.13].
* q ∈ QG: 11 values.
* **No m/σ restriction.** The corner m = 0.3, σ = 0.05 is included. r1's
  m/σ ≥ 10 restriction is withdrawn.

### Reference: adaptive Gauss–Kronrod in z, split at the kink

Substitute H = m + σz:

  E[g(H)] = ∫ g(m + σz) φ(z) dz.

The algorithm, frozen:
1. **Interval.** Integrate over z ∈ [−12, 12].
   * The omitted tail mass is 2Φ(−12) ≈ 3.6e-33.
   * On \|z\| > 12, \|f\| ≤ \|m\| + σ\|z\| + α(q + c·√(\|m\| + σ\|z\|)), which
     grows at most linearly in \|z\|.
   * So each omitted contribution to E[f] or E[(f − E)²] is ≤ 1e-30 in its
     units. This is analytically negligible.
2. **Kink split.** z₀ = −m/σ. If z₀ ∈ (−12, 12), integrate [−12, z₀] and
   [z₀, 12] separately; otherwise use the single interval.
   * Below z₀, f is linear (√max(h, 0) = 0).
   * Above z₀, f is smooth in the interior. Its derivative is singular only
     at the endpoint z₀, where the singularity is integrable, of type √.
   * The reference does not integrate across the kink.
3. **Rule.** Gauss–Kronrod 7–15 on each subinterval. Use the standard
   QUADPACK QK15 nodes and weights, hard-coded to the published 15
   significant digits. The error estimate is \|K15 − G7\|.
4. **Adaptivity.** Global bisection:
   * Repeatedly bisect the subinterval with the largest error estimate until
     the summed error estimate is ≤ τ.
   * Accept with **τ_E = 1e-14 m** for E[f], and **τ_V = 1e-16 m²** for
     Var[f].
   * Recursion limit: depth ≤ 50 and ≤ 2000 subintervals per integral.
5. **Variance.** Two passes. First E_ref, then
   Var_ref = ∫ (f − E_ref)² φ dz with the same splitting. This centred
   form avoids cancellation.
6. **Failure.** If the reference fails to reach its tolerance within the
   limits, T6 **fails**, and the receipt reports it as a reference failure.
   Stop and report; do not retune.

The reference uses the exact φ and needs no Φ.
* τ_E is ≥ 7e5× below the smallest c > 0 mean tolerance (7.3e-9 m, derived
  below).
* τ_V is 4e7× below the variance tolerance.
* At c = 0, f is linear. GH20 and GK15 are then both exact up to rounding,
  and only the rounding allowance applies.

So reference error cannot decide a borderline case.

### Acceptance tolerance, derived in level units before execution

Let ρ = **1e-3**: the largest fraction of the frozen process-noise scale that
GH20 error may contribute.

**Why ρ = 1e-3.** Gate 18 tests 90% coverage within [0.85, 0.95].
* A relative predictive-variance error r changes 90% coverage by about
  z·φ(z)·r ≈ 0.17r (z = 1.645).
* A standardized mean shift s changes it by at most about 2φ(z)·s ≈ 0.21s.
* At ρ = 1e-3, both are ≲ 2e-4 coverage. That is ≥ 250× inside the ±0.05
  band.

For comparison, v1.1 overstated variance by 20–25%, and v1.2's residual
diffusion was ≈ 0.7σ_w² per step.

**Variance.** Linearize the step as h′ ≈ a·h + const, with
a = 1 − αc/(2√m) ∈ (0, 1] on the grid.
* A per-step variance error e accumulates to e/(1 − a²) at steady state.
* σ_w² accumulates to σ_w²/(1 − a²).
* Their ratio is e/σ_w² for every a < 1.

Criterion: **\|Var_GH20 − Var_ref\| ≤ ρ·σ_w² + 1e-15 = 4.0e-9 m²** (plus a
rounding allowance).

**Mean.** The quadrature error in E[f] is αc·ΔE[√H₊], and the steady-state
shift is that divided by (1 − a) = αc/(2√m). To bound the steady-state shift
by ρ·σ_w (that is, ≤ ρ standardized, because predictive sd ≥ σ_w), require
per point:

**\|E_GH20 − E_ref\| ≤ ρ·σ_w·αc/(2√m) + 1e-13 m.**

Over the grid this ranges from 0 + 1e-13 (c = 0, where f is linear and GH20
is exact up to rounding) through ≈ 7.3e-9 m (c = 0.01, m = 1.9) to
≈ 2.4e-7 m (c = 0.13, m = 0.3).

**Rounding allowances.** The 1e-13 m and 1e-15 m² allowances bound
floating-point error:
* means ≈ 2 m over ≤ 20 terms give ≲ 1e-14 m;
* centred variances ≤ 2.5e-3 m² give ≲ 1e-18 m².

### Pass

Both criteria hold at every grid point (33 × 9 × 15 × 11 = 49,005), and the
reference meets its tolerance everywhere. Any failure means stop and
report. No criterion, grid value or reference setting is changed after
execution.

## Procedure

1. The user freezes this amendment.
2. The v1.3 procedure (Amendment 4) then resumes from its step 2, with T6
   as defined here. The implementation-only receipt reports T1–T5, T6 (this
   definition), T7 and T8.
