# Lineage B0 — Simulator Validity: Preregistration v1.3 (CANDIDATE r3 — not frozen)

Status: **candidate for review; decisions D1–D3 recorded.**
* Amends v1.1 (`docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1.md` @ `642d3fd`).
* Supersedes v1.2 (`docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_2.md` @ `72e8925`)
  for Amendment 1 and the B0 root only.
* Everything in v1.1 not amended here stays in force.
* No v1.3 code exists. B1 stays unfrozen and unimplemented.

## Framing

v1.3 does not claim that a Gaussian predictor is better or exact. It
removes grid diffusion but introduces a **moment-closure approximation**
(§1.7). B0 exists to test whether a predictor is numerically adequate before
B1. The question v1.3 answers is:

> Can we construct a predictor whose numerical approximation error is small
> enough that feedback learning is not dominated by the predictor itself?

Gate 18, unchanged, is the operational test of that question.

v1.3 changes only the level-state representation (v1.1/v1.2 grid →
Gaussian moment closure). The rest of the imperfect v1.1 predictor is left
alone (§0.3), so a change in gate 18 can be attributed narrowly to removing
level-grid numerical diffusion.

## Audit trail

| Commit | What |
|---|---|
| `642d3fd` | B0 v1.1 FROZEN (100 × 0.02 m grid filter) |
| `5b8f965`, `1471e2e` | v1.1 implementation; gate-6 fix. Pre-gate-commit slip disclosed (permanent) |
| `c3996e7`, `3d9529b` | v1.1 run 1 ABORTED at gate 18. Level predictor under-confident from grid diffusion |
| `72e8925` | B0 v1.2 FROZEN (400 × 0.005 m grid; fresh disjoint roots; implementation-only test) |
| `8b23ce5` | v1.2 implementation, committed before any execution |
| `4a8767f` | v1.2 **STOPPED** at its implementation-only diffusion test |
| `9ac875a` | v1.2 closed (addendum to its stop note); v1.3 candidate r1 |
| `7257501` | v1.3 candidate r2: semantics extracted from code; clipping order corrected to match the world |

v1.2 diffusion ratios: equilibrium **7.32** (frozen rule ≥ 8), rising
10.26, draining 17.00.

**v1.2 disposition (user decision, 2026-10-05):** CLOSED as an
implementation-stage failure.
* No v1.2 validity gate or pilot ran.
* The ≥ 8 threshold is not lowered or reinterpreted.
* Residual grid diffusion was about 70% of σ_w² at equilibrium
  (2.78e-6 against 4e-6).
* The grid is not refined further. The representation class changes
  instead.

## Decisions (user, 2026-10-06)

* **D1, √h closure:** 20-point Gauss–Hermite (§1.2). It handles √h and the
  boundary clipping directly, with no derivative cutoff near h = 0. Its
  approximation error is tested by T6. The EKF-style alternative from r2 is
  not adopted and does not appear in this spec.
* **D2:** P1–P7 (§0.3) stay unchanged. In particular, P1 and P4 are **not**
  fixed in v1.3. They remain explicit limitations. If gate 18 fails after
  the representation change, they may be addressed by a later, separately
  frozen amendment.
* **D3:** dt = 1, one predictor step per world step, no substepping
  (matches the §0.1 Euler step).
* **Clipping is not a choice.** It matches the world: process noise is
  added first, then the result is clipped to [0, H_max] (§0.1, §1.3).

## §0 — Existing semantics, extracted from code (the target v1.3 must reproduce)

`world.py`, `sensors.py` and `channel.py` are unchanged since `5b8f965`.
Agent-side references are at `4a8767f`. Time t is the step index; Z_t is the
state at the start of step t.

### 0.1 World (evaluator)

| Item | Semantics | Code |
|---|---|---|
| Valve | Incremental. `open` +0.25, `close` −0.25, clipped to [0, 1]; `hold`/`inspect` unchanged. Applied before the flow computation: u_{t+1} drives the t → t+1 flow | `world.py:82-84` |
| Level | h_raw = h_t + (dt/A)(q_t − Cv·u_{t+1}·√max(h_t,0) − k(ℓ_t)·√max(h_t,0)) + σ_w·w_t; h_{t+1} = clip(h_raw, 0, H_max). **Noise first, then clip** | `world.py:83-87` |
| Spill / shortfall | A·max(h_raw − H_max, 0)/dt and A·max(−h_raw, 0)/dt. Recorded; spill enters cost J. They do not feed back into the state | `world.py:88-89` |
| Leak flow | k(ℓ)·√max(h,0) with k = 0 / 0.01 / 0.03 (none / slow / fast). Affects outflow only. **No sensor observes leak flow** (F measures valve flow only) | `world.py:85`, `sensors.py:15-16` |
| Leak onset | In transition t → t+1, if ℓ_t = none and no repair fires this step: with probability λ = 0.002, ℓ_{t+1} = slow (p 0.7) or fast (p 0.3). The new leak first drains in transition t+1 → t+2 | `world.py:103-107` |
| Inspection / repair | `inspect` at t: if ℓ_t ≠ none, the report is LEAK_FOUND with p 0.9, and a found leak with no pending repair sets repair_at = t + 5. If ℓ_t = none, the report is LEAK_FOUND with p 0.05, which schedules nothing. The leak is cleared in transition t+4 → t+5 (ℓ_{t+5} = none). Leak flow still acts in transitions t … t+4. No onset is drawn in the step where a repair fires | `world.py:94-105` |
| Inflow | Continuous AR(1), updated every step: q_{t+1} = max(0, Q̄ + φ(q_t − Q̄) + σ_η·η_t). The level step uses q_t (pre-update). Each episode starts at q_0 = Q̄ exactly | `world.py:50, 58, 86, 90` |
| Process noise | Two sources only: w (level, added before the clip) and η (inflow, before its clip at 0). The valve, sensors' true quantities and inspection have no process noise. One draw per source per step, regardless of action (CRN) | `world.py:77-80` |
| Initial level | h_0 = 1 + 0.05·N(0, 1) | `world.py:56-57` |

### 0.2 Observation and prediction timing

| Item | Semantics | Code |
|---|---|---|
| Observation | Readings of Z_t are taken at the start of step t, before the action at t. L* read h_t; P reads 9.81·h_t; F reads Cv·u_t·√h_t. Plus the fault overlay and channel | `harness.py:46-49`, `sensors.py:22-47` |
| Inspection record | About ℓ_t, `measured_at` = t, delivered at t+1 | `channel.py:54-56` |
| Prediction target | Receipt keyed (episode, t+1). It is committed after the action at t is final and before `world.step`. For each sensor it holds the distribution of that sensor's reading of Z_{t+1} under the arm's (b, σ). F uses u_{t+1} | `core.py:118-134`, `harness.py:64-72` |
| Gate 18 | PIT of the first-delivered VALUE for (sensor, `measured_at`) against the receipt for `measured_at`, including late values. Run under C0, μ behaviour, θ0, no updater | `gates.py` `g18_calibration` |

### 0.3 Agent-side v1.1 §7 semantics (kept unchanged by D2)

These are preserved in v1.3, including where they knowingly differ from the
world.

| # | Predictor semantics (v1.1) | Code |
|---|---|---|
| P1 | The prior on inflow is the stationary distribution over the 11-point grid. The world starts each episode at q_0 = Q̄ | `predictor.py` `initial_belief` |
| P2 | Inflow is an 11-point Markov-chain approximation of the AR(1). This is the remaining discretization, outside this amendment's scope | `predictor.py` `q_matrix` |
| P3 | An inspection report (about ℓ_t) multiplies the belief already predicted to t+1 | `core.py:52-56` |
| P4 | Every LEAK_FOUND schedules a modelled repair at `measured_at` + 5, including false alarms and reports during a pending repair, which the world ignores | `core.py:54-55` |
| P5 | Predictions at t′ with t′+1 a scheduled repair: the level step uses the pre-repair leak, then all leak mass moves to none, with no onset. This matches world timing | `core.py:120`, `predictor.py` `predict` |
| P6 | Only fresh records (`measured_at` = t) are assimilated. Late records are scored only | `core.py:61-64` |
| P7 | C3's relay L4 is assimilated as an independent sensor. This is by design: the alias confound is a B1 object | `core.py:57-62` |

## Amendment 1 — Level-state representation (replaces v1.1 §7 grid; replaces v1.2 Amendment 1)

### 1.1 Belief

The hypotheses are c = (j, ℓ):
* j ∈ {0..10} indexes the v1.1 inflow grid `QG`, unchanged (P1, P2);
* ℓ ∈ {none, slow, fast}.

The belief is B = {(π_c, m_c, v_c)}:
* π_c ≥ 0 with Σ π_c = 1;
* the level given c is approximated as N(m_c, v_c), with v_c ≥ 0.

Components with π_c = 0 carry placeholder moments (m = 0, v = 0), and
every expectation weights by π_c.

**Initial belief.** π_(j,none) = q_stationary[j], and every other π = 0.
Every component has m = 1.0, v = 0.05². This is the v1.1 distribution
without a grid.

### 1.2 The √h closure: 20-point Gauss–Hermite (D1)

`numpy.polynomial.hermite.hermgauss(20)` supplies the physicists'
Gauss–Hermite rule (x_k, w_k) for the weight e^{−x²}. Transforming it with
h_k = m + √(2v)·x_k and ω_k = w_k/√π gives the normal expectation used
throughout:

E_N(m,v)[φ(h)] ≈ Σ_k ω_k φ(h_k),  k = 1..20.

* √ is always evaluated as √max(h, 0). No derivative is used anywhere.
* When v = 0, every node equals m and the rule returns φ(m).
* This is the only approximation of √h in v1.3.

### 1.3 Prediction (§0.1 dynamics; same order as v1.1; dt = 1, no substepping)

Given the committed next valve position u′ and the flag repair_now (P5):

**(a) Level step per component.** As in the world: noise first, then clip.
Let c_ℓ = Cv·u′ + k(ℓ) and μ(h) = h + (dt/A)(q_j − c_ℓ·√max(h, 0)), the
unclipped deterministic part. Then h′ = clip(μ(h) + σ_w·w, 0, H_max).

For each node h_k, Y_k = clip(N(μ(h_k), σ_w²), 0, H_max) is a censored
normal. Its moments (E_k, V_k) come from §1.3(d). Combine them by the law
of total variance:
* m′ = Σ ω_k E_k;
* v′ = Σ ω_k [V_k + (E_k − m′)²];
* π is unchanged by this step.

**(b) Inflow transition.** Use the v1.1 `q_matrix` Q. For each (r, ℓ),
moment-match the mixture with weights α_j = π_(j,ℓ)·Q[j, r]:
* π′ = Σ α_j;
* m′ = Σ α_j m_j / π′;
* v′ = Σ α_j [v_j + (m_j − m′)²] / π′.

This nonnegative form is used. The algebraically equal subtractive form
Σα(v + m²)/π′ − m′² cancels catastrophically and is not used. The collapse
keeps each (r, ℓ) mixture's mean and variance and discards higher-order
shape.

**(c) Leak transition** (v1.1 semantics).
* No repair: none ← none·(1 − λ); slow ← collapse(slow, none·λ·0.7);
  fast ← collapse(fast, none·λ·0.3).
* Repair: none ← collapse(none, slow, fast); slow = fast = 0.
* "collapse" is the §1.3(b) formula. Then renormalize π.

**(d) Censored-normal moments.** Y = clip(X, a, b) with X ~ N(μ, s²),
a = 0, b = H_max.
* z_a = (a − μ)/s, z_b = (b − μ)/s, using the frozen `ncdf` Φ (A&S 7.1.26,
  as in v1.1) and the exact φ.
* E = μ + (a − μ)Φ(z_a) + (b − μ)(1 − Φ(z_b)) + s(φ(z_a) − φ(z_b)).
* M2 = (a − μ)²Φ(z_a) + (b − μ)²(1 − Φ(z_b)) + s²(Φ(z_b) − Φ(z_a))
  + s[(a − μ)φ(z_a) − (b − μ)φ(z_b)].
* V = max(M2 − (E − μ)², 0). The max only absorbs rounding on a quantity
  that is centred about μ.

Interior shortcut: if Φ(z_a) = 0 and Φ(z_b) = 1 in floating point, then
E = μ and V = s² exactly. Under the frozen Φ this holds beyond about 8.5 s,
roughly 0.017 m, from both bounds.

If s = 0 (tests only), Y = clip(μ) and V = 0.

### 1.4 Assimilation (agent-visible fresh records only; P6)

Fresh values at t are processed **sequentially in the fixed order
L1, L2, L3, L4, F, P.** This is the v1.1 G0–G2 conditional-independence
assumption. Each sensor s uses its arm-supplied (b, σ), applied per
component.

**Level sensors.** y = h + b + ε. Use the closed-form Kalman update for this
component's Gaussian prior (exact given that prior; the belief overall
remains an approximation):
* S = v + σ²; K = v/S;
* log π += log N(y; m + b, S), using the prior m;
* m ← m + K(y − m − b); v ← (1 − K)v.

**P.** The same update with gain G = P_gain:
* S = G²v + σ²; K = Gv/S;
* m ← m + K(y − Gm − b); v ← (1 − KG)v.

**F.** y = Cv·u·√max(h, 0) + b + ε, where u is the current u_t. Reweight the
§1.2 nodes:
* λ_k = ω_k·N(y; Cv·u·√max(h_k, 0) + b, σ²);
* log π += log Σλ;
* m ← Σλ_k h_k / Σλ;
* v ← Σλ_k (h_k − m)² / Σλ.

**Normalization.**
* π is renormalized with log-sum-exp.
* If every component likelihood underflows, the belief is left unchanged
  and the skip is logged (the v1.1 `assimilate` rule).
* No variance floor and no inflation.

**Inspection.** Unchanged (P3): the v1.1 likelihood on ℓ multiplies π.

**REF-S.** It uses the same machinery with its true fault parameters. When
L1 and L2 are both fresh, they get a joint 2-D Kalman update with
covariance [[σ_A² + σ_12², σ_A²], [σ_A², σ_A² + σ_12²]]. The v1.1 W²/12
terms disappear because there are no bins. Stuck sensors are skipped and
L4 is ignored, as in v1.1.

### 1.5 Outputs that read the belief

**PredictionReceipt** (target as in §0.2). `BIN_EDGES` are unchanged.
* Level / P: the categorical is the closed-form integral of the
  Gaussian-mixture predictive over the bins,
  Σ_c π_c Φ((e − G·m_c − b)/√(G²v_c + σ²)), with G = 1 or P_gain and
  under/overflow bins.
* F: Σ_c π_c Σ_k ω_k Φ((e − Cv·u′·√max(h_ck, 0) − b)/σ), using the §1.2
  nodes.
* `latent_mean` / `latent_var` are the mixture mean and variance of the
  measured quantity, with §1.2 quadrature for F.

**Controller** (v1.1 §8; the definition is unchanged).
* E[c_D(h′ − h*)²] = c_D Σ π_c [(m_c − h*)² + v_c].
* P(h′ ∈ U) = Σ π_c [Φ((0.2 − m_c)/√v_c) + 1 − Φ((1.8 − m_c)/√v_c)].
  When v_c = 0 this is an indicator of m_c.

**Belief summary.** `mean_h`, `sd_h` and `p_leak` are mixture moments. The
digest is the SHA-256 of the (π, m, v) arrays.

### 1.6 Unchanged, explicitly

* Everything in §0.1–§0.3.
* The sensor models and fault fixtures, the channel, the information
  boundary and AST rule.
* Terminal authority and the authority layer, the logging policy and all
  records.
* Nominal θ0 and the G2 update primitive.
* Every gate's test and threshold. **Gate 18:** cov90 ∈ [0.85, 0.95] and
  cov50 ∈ [0.40, 0.60].

Gate 13's fixture beliefs become π = q_stationary on ℓ = none, m = h0 and
v = 0.05². That is the same distribution as before; the test and threshold
are unchanged.

### 1.7 Approximations introduced by v1.3 (the representation is a moment closure, not exact)

* **A1.** Within each (j, ℓ), the level belief is Gaussian.
* **A2.** The inflow and leak collapses keep two moments per hypothesis.
* **A3.** √h expectations use the 20-point Gauss–Hermite rule of §1.2.
* **A4.** For F, the update re-Gaussianizes each component after a
  non-Gaussian update.
* **A5.** The prediction re-Gaussianizes each component after the clip
  (censored moments, §1.3(d)).

## Amendment 2 — Seed roots

| Purpose | v1.1 | v1.2 | **v1.3** |
|---|---|---|---|
| B0 validity gates | 20261005 | 2026100512000 (never used for gates) | **2026100515000** (offsets +0 … +999) |
| pilot (gate 17) | 20261006 | 2026100513000 (never used) | **2026100513000** (unchanged; never consumed) |
| B1 | 20261007 | 2026100514000 (never used) | **2026100514000** (unchanged; never consumed) |

* The v1.3 B0 offset range is disjoint from every earlier root and offset
  range, and from the pilot and B1 roots. The gates assert this at import.
* Implementation-only tests use only the fixture RNG seed **130515**. It is
  evaluator-side, and none of the B0, pilot or B1 roots.

## Amendment 3 — Implementation-only tests (before any validity gate)

These live in `tests/test_lineage_b0_v13_impl.py`, with a receipt from
`tools/run_lineage_b0_v13_impl.py`. They verify the implementation only and
are **not used to tune anything**. Any failure means stop and report.
Tolerances derive from floating-point accuracy or the frozen noise model.
No tolerance comes from any B0 calibration quantity.

Q̄ is exactly `QG[5]`. Single-component tests pass q directly.

| # | Test | Pass criterion | Tolerance derivation |
|---|---|---|---|
| T1 | **Zero-noise propagation = nominal transition**, σ_w = 0, v0 = 0. (i) Against `World.step(noise=False)`, q_0 = Q̄, 200 steps: (u 0.5, h0 1.0); (u 0.25, h0 0.5), which rises into the H_max clip; (u 0.75, h0 1.5), draining. (ii) Against the §0.1 map with q = 0, u = 1, fast leak, h0 = 0.004 (the gate-1 underflow fixture), 5 steps | \|m_n − h_n\| ≤ 1e-11 | Per step: Σω = 1 ± 20ε, \|h\| ≤ 2, and ~10 rounded ops give ≤ ~1e-14. Over 200 steps ≤ ~2e-12. Tolerance ×5 |
| T2 | **Process variance = analytic process noise at equilibrium.** u = 0.5, h* = 1, ℓ = none. a = 1 − (dt/A)·Cv·u/(2√h*) = 0.975, so v* = σ_w²/(1 − a²) = 8.1013e-5. (i) From v0 = 0, 200 steps against v_n^ref = σ_w²(1 − a^{2n})/(1 − a²). (ii) From v0 = v*, 200 steps against v* | \|v_n/v_n^ref − 1\| ≤ 1e-4 and \|m_n − 1\| ≤ 1e-4 m | GH20 keeps curvature, which shifts the mean by ≈ (dt/A)c·v/(8(1 − a)) ≈ 2.0e-5 m. That changes a by ≈ 2.5e-7, so δv/v ≈ 2aδa/(1 − a²) ≈ 1.0e-5. The direct curvature term is ≈ 6e-9 relative. Clipping is inactive: 1 m from the bounds is ≈ 110 sd. Tolerance ≈ 10× / 5× the bounds |
| T3 | **No artificial variance growth at zero noise.** σ_w = 0, Q = identity, λ = 0. (i) Full `predict` from point masses in all 33 components, 200 steps. (ii) Single component, v0 = 0.05², T1(i) fixtures | (i) max v_c ≤ 1e-26. (ii) v_{n+1} ≤ v_n for all n | (i) Zero node spread plus the stable collapse leaves rounding² ≈ 2e-29. (ii) f′(h) = 1 − c/(2√h) ∈ (0, 1) on the fixtures, so the exact map contracts |
| T4 | **Update normalization and validity.** 1000 random beliefs (fixture seed), random fresh subsets of {L1, L2, L3, F, P}, random u ∈ U_LEVELS. Values are drawn from the predictive, plus extremes y ∈ {−100, 100} and F at u = 0 | \|Σπ − 1\| ≤ 1e-12. Every m and v finite, v ≥ 0. Level/P: v_post ≤ v_prior(1 + 1e-12). Total underflow leaves the belief unchanged and is logged | 33 terms, one division: ≤ ~1e-14. Kalman (1 − K) ∈ [0, 1] exactly; 1e-12 covers rounding |
| T5 | **Action sensitivity.** Gate-13 fixture beliefs (h0 ∈ {0.5, 1.0, 1.5}) | mean(open) − mean(close) equals −(dt/A)·Cv·0.5·Σπ_c Ê[√h] within 1e-12 relative, where Ê is the §1.2 GH20 expectation. It is ≠ 0. Predicted L3 and F categoricals differ | Single-step arithmetic, as in T1 |
| T6 | **Closure adequacy.** E[√h] and Var[√h] by GH20 against GH100, for m ∈ [0.3, 1.9] and sd ∈ [1e-4, 0.05] | \|Δ\| ≤ 1e-10 | The integrand is analytic where weight > 1e-12. 1e-10 is ≈ 5 orders below σ_w². The reference is GH100 because NumPy documents `hermgauss` as tested only up to degree 100; a higher-degree reference could fail on its own (pre-execution reference correction, r3) |
| T7 | **Collapse preserves moments.** Random 2- and 11-component mixtures | Mixture mean and variance unchanged within 1e-12 relative | An identity; rounding only |
| T8 | **Censored-normal moments.** μ ∈ {−0.004, 0, 0.001, 1.0, 1.999, 2.0, 2.003}, s = σ_w. The implementation (frozen Φ) against a reference using `math.erf` | \|ΔE\| ≤ 1e-9 m, \|ΔV\| ≤ 1e-11 m². μ = 1.0 gives exactly (μ, s²) through the interior shortcut | Frozen Φ error ≤ 7.5e-8. In the near-bound fixtures \|bound − μ\| ≤ 0.004 m: E error ≲ 2·0.004·7.5e-8 ≈ 6e-10; M2 error ≲ (0.004)²·7.5e-8 + s·0.004·7.5e-8 ≈ 2e-12 |

## Amendment 4 — Procedure

1. The user freezes this document.
2. Implement and run T1–T8. If any test fails, stop and report.
3. If all pass: commit the implementation **and** the T1–T8 receipt before
   any validity gate runs.
4. Run **all** validity gates (1–16, 18, 19) **once** on the v1.3 B0 root.
   Any failure means stop. No threshold is relaxed; this includes gate 5
   near its 3/√N bound.
5. Only if every gate passes, run the gate-17 pilot on the pilot root.
6. **Stop** after the B0 result. Do not freeze or implement B1.

**Contingency.** If v1.3 fails a gate, nothing further is pre-authorized.
P1 and P4 are then candidate subjects for a separately frozen amendment
(D2).
