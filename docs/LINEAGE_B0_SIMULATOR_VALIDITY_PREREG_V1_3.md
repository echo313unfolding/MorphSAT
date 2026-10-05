# Lineage B0 — Simulator Validity: Preregistration v1.3 (CANDIDATE — not frozen)

Status: **candidate for review.**
* Amends v1.1 (`docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1.md` @ `642d3fd`).
* Supersedes v1.2 (`docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_2.md` @ `72e8925`)
  for Amendment 1 and the B0 root only.
* Everything in v1.1 not amended here stays in force.
* No v1.3 code exists. B1 stays unfrozen and unimplemented.

## Audit trail

| Commit | What |
|---|---|
| `642d3fd` | B0 v1.1 FROZEN (100 × 0.02 m grid filter) |
| `5b8f965`, `1471e2e` | v1.1 implementation; gate-6 fix. Pre-gate-commit slip disclosed (permanent) |
| `c3996e7`, `3d9529b` | v1.1 run 1 ABORTED at gate 18. Level predictor under-confident from grid diffusion |
| `72e8925` | B0 v1.2 FROZEN (400 × 0.005 m grid; fresh disjoint roots; implementation-only test) |
| `8b23ce5` | v1.2 implementation, committed before any execution |
| `4a8767f` | v1.2 **STOPPED** at its implementation-only diffusion test |

v1.2 diffusion ratios: equilibrium **7.32** (frozen rule ≥ 8), rising
10.26, draining 17.00.

**v1.2 disposition (user decision, 2026-10-05):** CLOSED as an
implementation-stage failure.
* No v1.2 validity gate or pilot ran.
* The ≥ 8 threshold is not lowered or reinterpreted.
* The 0.005 m grid still added numerical diffusion of about 70% of σ_w² in
  the equilibrium case (2.78e-6 against 4e-6). Grid discretization is
  therefore still materially contaminating the predictor.
* Per the v1.2 contingency, the grid is not refined further. The
  representation class changes instead, under this new preregistration.

## Amendment 1 — Level-state representation (replaces v1.1 §7 grid; replaces v1.2 Amendment 1)

**Rationale.** B0 v1.1 and v1.2 showed that a level grid adds numerical
diffusion that contaminates the predictor. That is the confound gate 18
exists to exclude, and the one B1's G2 noise update would absorb. v1.3
replaces the level grid with a Gaussian per (inflow, leak) hypothesis. The
goal is to remove grid-induced diffusion while keeping the same nominal
transition model, the same information boundary and the same validity
criteria.

### 1.1 Belief

The hypotheses are c = (j, ℓ):
* j ∈ {0..10} indexes the v1.1 inflow grid `QG`. The 11 points, the AR(1)
  transition matrix `q_matrix()` and the stationary weights are unchanged.
* ℓ ∈ {none, slow, fast}.

The belief is B = {(π_c, m_c, v_c)}:
* π_c ≥ 0 with Σ π_c = 1;
* the level given c is approximately N(m_c, v_c), with v_c ≥ 0.

Components with π_c = 0 carry placeholder moments (m = 0, v = 0). Every
expectation weights by π_c, so placeholders never contribute.

**Initial belief** (same distribution as v1.1, without a grid):
* π_(j,none) = q_stationary[j]; π_(j,slow) = π_(j,fast) = 0;
* m = 1.0, v = 0.05².

### 1.2 Gauss–Hermite moments (the only nonlinear approximation)

For a function φ of h, E_N(m,v)[φ] ≈ Σ_k ω_k φ(m + √(2v)·x_k):
* x_k, ω_k are the **n = 20** probabilists'-normalized Gauss–Hermite nodes
  and weights (ω normalized to sum to 1);
* `numpy.polynomial.hermite.hermgauss(20)`, with ω_k = w_k/√π.

The same rule computes every expectation of √h. No other approximation of
√h is used. When v = 0, all nodes coincide at m and the rule is exact.

### 1.3 Prediction (same §3 dynamics; same order as v1.1)

Given the committed next valve position u′ and a flag for whether a repair
occurs now:

**(a) Level step, per component.** Let c_ℓ = Cv·u′ + k(ℓ) and
f_c(h) = clip(h + (dt/A)(q_j − c_ℓ·√max(h, 0)), 0, H_max). Then:
* m′_c = Σ_k ω_k f_c(h_k);
* v′_c = Σ_k ω_k (f_c(h_k) − m′_c)² + σ_w²;
* π is unchanged by this step.

**Clipping.** This step clips the deterministic part, then adds σ_w². The
world clips *after* adding w. The residual mismatch is predictive mass
outside [0, H_max] of order σ_w = 0.002 m, at the boundary only. See open
question Q1.

**(b) Inflow transition** (v1.1 `q_matrix` Q). For each (r, ℓ), collapse
by moment matching the mixture with weights α_j = π_(j,ℓ)·Q[j, r]:
* π′ = Σ α_j;
* m′ = Σ α_j m_j / π′;
* v′ = Σ α_j (v_j + (m_j − m′)²) / π′.

This is the algebraically identical, nonnegative form of
Σα(v + m²)/π′ − m′². The subtractive form cancels catastrophically, giving
errors of about 1e-15 that can be negative, so it is not used. The collapse
preserves the first two moments of each (r, ℓ) mixture exactly. It adds no
variance beyond the exact mixture second moment.

**(c) Leak transition** (v1.1 §7 semantics). Without a repair:
* none ← none·(1 − λ);
* slow ← collapse(slow, none·λ·p_slow);
* fast ← collapse(fast, none·λ·(1 − p_slow)).

With a repair: none ← collapse(none, slow, fast), and slow = fast = 0. The
collapse is the 1.3(b) formula. Finally, renormalize π.

### 1.4 Assimilation (agent-visible fresh records only; v1.1 §7 unchanged)

Fresh values at t are processed **sequentially in fixed order**
L1, L2, L3, F, P (and L4 if present). This is the G0–G2 conditional
independence assumption, unchanged. Per sensor s with arm-supplied (b, σ),
per component c:

**Level (L*).** y = h + b + ε. Exact Kalman update:
* S = v + σ²; K = v/S;
* m ← m + K(y − m − b); v ← (1 − K)v;
* log π ← log π + log N(y; m + b, S), using the prior m.

**Pressure (P).** Same, with g = P_gain·h:
* S = P_gain²·v + σ²; K = P_gain·v/S;
* m ← m + K(y − P_gain·m − b); v ← (1 − K·P_gain)v.

**Flow (F).** y = Cv·u·√max(h, 0) + b + ε. Gauss–Hermite reweighting:
* λ_k = ω_k·N(y; Cv·u·√max(h_k, 0) + b, σ²);
* log π ← log π + log Σλ_k;
* m ← Σλ_k h_k / Σλ_k;
* v ← Σλ_k (h_k − m)² / Σλ_k, which is ≥ 0 by construction.

**Normalization.**
* π is renormalized with log-sum-exp.
* If every component likelihood underflows, the belief is left unchanged.
  This is the v1.1 `assimilate` rule, and the skip is logged.
* There is **no variance floor and no inflation.**

**Inspection.** Unchanged: the v1.1 likelihood on ℓ multiplies π.

**REF-S.** It uses the same machinery with its true fault parameters. Its
joint (L1, L2) update is the exact 2-D Kalman update with covariance
[[σ_A² + σ_12², σ_A²], [σ_A², σ_A² + σ_12²]]. v1.1's W²/12 terms are
removed because there are no bins. Stuck sensors are skipped and L4 is
ignored, as in v1.1.

### 1.5 Outputs that read the belief

**PredictionReceipt.** The scoring bins `BIN_EDGES` are unchanged (level
0.02 m, pressure 0.1962 kPa, flow 0.003).
* Level/pressure: the categorical is the exact mixture integral,
  Σ_c π_c [Φ((e − g_c − b)/√(G²v_c + σ²))] over edges, with under- and
  overflow bins.
* Flow: Σ_c π_c Σ_k ω_k Φ((e − Cv·u·√max(h_ck, 0) − b)/σ).
* `latent_mean` / `latent_var` are the mixture mean and variance of the
  measured quantity, using GH for flow. There is no W²/12 term.

**Controller (v1.1 §8, unchanged definition).**
* E[c_D(h′ − h*)²] = c_D Σ π_c((m_c − h*)² + v_c).
* P(h′ ∈ U) = Σ π_c [Φ((0.2 − m_c)/√v_c) + 1 − Φ((1.8 − m_c)/√v_c)].
  For v_c = 0 this is an indicator of m_c.
* v1.1 evaluated both on bin centres; v1.3 evaluates the same expectation
  over the new representation.

**Belief summary / digests.** `mean_h`, `sd_h` and `p_leak` are mixture
moments. The digest is the SHA-256 of the (π, m, v) arrays.

### 1.6 Unchanged, explicitly

* World equations, action set and valve semantics.
* Sensor models and fault fixtures C0–C5.
* Channel, delay, dropout and redelivery semantics.
* The §1 information boundary and AST import rule.
* Terminal authority and the authority layer.
* Logging policy and records (DecisionEvent, PredictionReceipt,
  FeedbackRecord).
* Inflow grid and AR(1) matrix; leak hazard, repair and inspection model.
* Nominal θ0 and the G2 update primitive.
* Every gate's test and threshold, including **gate 18:**
  cov90 ∈ [0.85, 0.95] and cov50 ∈ [0.40, 0.60].

Only the construction of gate 13's fixtures depends on the representation.
"h ∼ N(h0, 0.05²), q stationary, leak none" becomes π = q_stationary on
ℓ = none, m = h0 and v = 0.05², the same distribution without a grid. The
gate-13 test and threshold are unchanged.

### 1.7 Documented simplifications (new in v1.3)

* **S-G1.** Within each (j, ℓ), the level belief is Gaussian. The collapse
  keeps two moments and drops higher-order shape.
* **S-G2.** Clipping is applied before σ_w is added (see 1.3a).
* **S-G3.** √h expectations use 20-node Gauss–Hermite quadrature.
* **Known residual discretization:** the 11-point inflow grid is retained
  unchanged. This amendment replaces only the level representation.

## Amendment 2 — Seed roots (amends v1.2 Amendment 2)

| Purpose | v1.1 | v1.2 | **v1.3** |
|---|---|---|---|
| B0 validity gates | 20261005 | 2026100512000 (never used for gates) | **2026100515000** (offsets +0 … +999) |
| pilot (gate 17) | 20261006 | 2026100513000 (never used) | **2026100513000** (unchanged; never consumed) |
| B1 | 20261007 | 2026100514000 (never used) | **2026100514000** (unchanged; never consumed) |

* The v1.3 B0 offset range, …15000–…15999, is disjoint from every v1.1 and
  v1.2 root and offset range, and from the pilot and B1 roots.
* The gates assert this at import time.
* Implementation-only tests use only the fixture RNG seed **130515**. This
  is evaluator-side and is not a B0, pilot or B1 root.

## Amendment 3 — Implementation-only tests (before any validity gate)

These live in `tests/test_lineage_b0_v13_impl.py`, with a receipt from
`tools/run_lineage_b0_v13_impl.py`. They verify the implementation only and
are **not used to tune anything**. If any test fails: stop and report.

Fixtures use the nominal constants at q = Q̄. Q̄ is exactly `QG[5]`, because
`linspace(-3, 3, 11)[5] = 0`. The tests exercise a single component,
except T4 and T7. Tolerances derive from floating-point accuracy or the
frozen noise model, as follows.

| # | Test | Pass criterion | Tolerance derivation |
|---|---|---|---|
| T1 | **Zero-noise propagation = nominal transition.** σ_w = 0, v0 = 0. Compare against `World.step` with `noise=False` and q0 = Q̄ (world q stays at Q̄ exactly) for 200 steps. Fixtures: (u = 0.5, h0 = 1.0); (u = 0.25, h0 = 0.5), which rises into the H_max clip; (u = 0.75, h0 = 1.5), draining | \|m_n − h_n^world\| ≤ 1e-11 for all n | Per step: Σω = 1 ± 20ε, \|f\| ≤ 2, and ~10 rounded ops give ≤ ~1e-14. Over 200 steps ≤ ~2e-12. Tolerance ×5 |
| T2 | **Process variance = analytic process noise (equilibrium).** u = 0.5, h* = 1, ℓ = none. a = 1 − (dt/A)·Cv·u/(2√h*) = 0.975, so v* = σ_w²/(1 − a²) = 8.1013e-5. (i) From v0 = 0, 200 steps against v_n^ref = σ_w²(1 − a^{2n})/(1 − a²). (ii) From v0 = v*, 200 steps against v* | \|v_n/v_n^ref − 1\| ≤ 1e-4 and \|m_n − 1\| ≤ 1e-4 m | Second-order terms of the exact moment map relative to the linear reference: curvature-induced mean shift ≈ (dt/A)c·v/(8(1 − a)) ≈ 2.0e-5 m, giving δv/v ≈ 2aδa/(1 − a²) ≈ 1.0e-5. Direct curvature term ≈ ½f″²v ≈ 6e-9 relative. Tolerance ≈ 10× / 5× those bounds |
| T3 | **No artificial variance growth at zero noise.** σ_w = 0, Q = identity, λ = 0. (i) Full `predict` from point masses (v = 0) in all 33 components, 200 steps. (ii) Single component, v0 = 0.05², T1 fixtures | (i) max v_c ≤ 1e-26. (ii) v_{n+1} ≤ v_n for every n | (i) Node spread is 0; rounding of the mean leaves (≈ 4e-15)² ≈ 2e-29. (ii) f′(h) = 1 − c/(2√h) ∈ (0, 1) on the fixtures, so the exact map contracts. No tolerance is needed |
| T4 | **Update normalization and validity.** 1000 random beliefs (fixture seed), random fresh subsets of {L1, L2, L3, F, P}, random u ∈ U_LEVELS. Values are drawn from the predictive distribution, plus extremes y ∈ {−100, 100} and F at u = 0 | \|Σπ − 1\| ≤ 1e-12. Every m and v finite, v ≥ 0. For level/pressure, v_post ≤ v_prior(1 + 1e-12). Total underflow leaves the belief unchanged and is logged | 33 terms, one division: ≤ ~1e-14. Kalman (1 − K) ∈ [0, 1] in exact arithmetic; 1e-12 covers rounding |
| T5 | **Action sensitivity.** Gate-13 fixture beliefs (h0 ∈ {0.5, 1.0, 1.5}) | mean(open) − mean(close) equals −(dt/A)·Cv·0.5·Σπ_c E_GH[√h] within 1e-12 relative and is ≠ 0. Predicted L3 and F categoricals differ | Same arithmetic as T1, single step |
| T6 | **Gauss–Hermite adequacy.** E[√h] and Var[√h] by n = 20 against n = 200, for m ∈ [0.3, 1.9] and sd ∈ [1e-4, 0.05] | \|Δ\| ≤ 1e-10 | The integrand is analytic on the support carrying weight > 1e-12. The n = 200 rule is the reference. 1e-10 is ≈ 5 orders below σ_w² |
| T7 | **Collapse preserves moments.** Random two-component and 11-component mixtures | Mixture mean and variance equal before and after the collapse within 1e-12 relative | Exact identity; rounding only |

## Amendment 4 — Procedure

1. The user reviews this candidate and freezes it (any edits first).
2. Implement and run T1–T7. If any test fails, stop and report.
3. If all pass: commit the implementation **and** the T1–T7 receipt before
   any validity gate runs.
4. Run **all** validity gates (1–16, 18, 19) **once** on the v1.3 B0 root.
   Any failure means stop. No threshold is relaxed; this includes gate 5
   near its 3/√N bound.
5. Only if every gate passes, run the gate-17 pilot on the pilot root.
6. **Stop** after the B0 result. Do not freeze or implement B1.

**Contingency.** If v1.3 fails a gate, nothing further is pre-authorized.
The next step is the user's decision.

## Open questions for review (to resolve before freeze)

* **Q1, clipping.** Recommended: clip the deterministic part at the GH
  nodes (as written). This makes T1 match the world exactly, including the
  overflow fixture. Alternative: ignore clipping entirely, a larger
  deviation from §3 at the boundaries.
* **Q2, node count.** n = 20 is proposed. T6 checks it against n = 200. It
  is not tuned on any B0 outcome.
* **Q3, flow update.** GH reweighting (as written) is proposed instead of
  EKF linearization. It uses the same √h rule as prediction and has no
  Jacobian approximation.
* **Q4, step size.** Prediction stays per step (dt = 1), with no
  substepping, to match the v1.1 Euler form exactly.
