# Lineage B1 — Grounded Causal Feedback: Preregistration v1.5 (CANDIDATE)

Status: **candidate; not frozen.**
* B0 is **CLOSED / PASSED**: v1.3 `701c4c2` + T6 amendment v1.3.1 `ebdb0f1`,
  implementation `94f4f11`, results `06d5d24`
  (`docs/LINEAGE_B0_V13_RESULTS.md`). B0 is not modified or rerun.
* B1 uses **two freezes** (§15):
  1. a **sizing-design freeze**, which fixes everything except the
     confirmatory N and the confirmatory seed-list hash;
  2. a **confirmatory freeze**, which may only fill those two in and record
     the sizing receipt.
* No G1/G2/G3/G2-S code exists.
* v1.3 applies the user's 2026-10-06 pre-freeze corrections (§14). v1.4
  applies the user's final pre-freeze corrections (§17). v1.5 applies the
  user's procedural resolutions after design approval (§18). Scope: public
  GitHub lineage of `14689b7`.

## 0. Question and ceiling

**Primary question.** Does action-conditioned temporal feedback add value
beyond same-time observational consistency?

* G1 learns: "sensor A tends to disagree with the other sensors at the same
  time step" (same-time consensus).
* G2 learns: "after I took action X, sensor A reported something different
  from what should have happened."

Both G1 and G2 learn from external observations. B1 therefore does not
compare learning with external observations against learning without them.

**Primary contrast:** G2 vs G1. Required secondary contrasts: G2 vs G0, and
G2 vs the action-scrambled sham G2-S.

**Ceiling.** A positive result may support only:

> "In a controlled simulated physical system, remembering an action, the
> prediction made before it, the later observations and their provenance
> allowed an agent to make better future control decisions than relying on
> contemporaneous sensor agreement alone."

It does not establish embodiment, consciousness, a self-model, or
real-world sensor grounding. A G3 advantage may support only:

> "Representing known sensor dependencies improved use of simulated sensor
> feedback."

It does not establish that upstream identifiers are reliable authority
signals in real deployments. `upstream_id` / `declared_upstream` is
provenance metadata (standing interpretation, `1fe9b0a`).

## 1. Design overview (one deployment)

A deployment is one seeded world with one frozen fault condition (B0 §6).
It runs `E_L` learning episodes followed by `E_E` evaluation episodes. The
fault onset `t_f` falls in learning episode 1 and the fault persists.

1. **Learning phase (common log).** The world is run **once** with actions
   from the randomized logging policy μ (§5). All arms process the
   **identical** logged stream in lockstep. At every step t, each arm
   commits its own prediction receipt before the shared transition runs,
   then updates its own θ from its own rule. Arms therefore differ only by
   update rule, never by the data they saw.
2. **Evaluation phase (frozen θ, on-policy, common random numbers).** Each
   arm's θ is frozen. Each arm controls its own world instance from the same
   seeds (B0 RNG substreams), so exogenous noise is identical across arms.
   There is no learning in this phase. Predictions are still committed and
   scored.

## 2. Agent (identical across arms except θ updates)

* **Belief and predictor: the frozen B0 v1.3 predictor, unchanged.** This is
  B0 prereg v1.3 `701c4c2` §1 with v1.3.1 `ebdb0f1`, implemented in
  `lineage_b/agent/predictor.py` at `94f4f11`.
  * A Gaussian level belief per (inflow, leak) hypothesis over the 11-point
    inflow grid and 3 leak states.
  * 20-point Gauss–Hermite moments for √h; noise first, then clip, via
    censored moments.
  * Moment-matched inflow and leak transitions.
  * Closed-form Kalman updates for level and pressure; Gauss–Hermite
    reweighting for flow.

  It is a **moment-closure approximation** (B0 v1.3 §1.7), not an exact
  filter. Its known model mismatches P1–P7 (B0 v1.3 §0.3) are retained
  unchanged. Validity check V0 (§3) requires `predictor.py` to be
  byte-identical to `94f4f11`.
* **Sensor model** per sensor i: `y_i = g_i(state) + b_i + e_i`,
  `e_i ~ N(0, σ_i²)`, with `θ_i = (b_i, σ_i)` and `θ0` = nominal (b = 0,
  nominal σ). G0–G2 assume sensors are conditionally independent given
  state, which means sequential updates in the frozen order (B0 v1.3 §1.4).
* **Prediction protocol** (B-U3, B0 gate 8). After `A_t` is chosen and
  before `T` runs, the agent commits a receipt `R_{t+1}`.
  * It contains a per-sensor categorical predictive distribution over the
    frozen bins, `P(O^i_{t+1} | agent-visible history, A_t)`, plus the
    latent predictive mean and variance of each measured quantity, all
    under one hash.
  * Receipts are append-only and never rewritten.
  * Delayed observations are scored against the receipt for their
    `measured_at` step.
* **Absence ≠ success.** PENDING/MISSING produce no score and no θ update,
  and are counted. Transport redeliveries count once.

## 3. Arms

All arms use the same matched update rule form. Only the **reference**
(mean m, variance s²) against which sensor i's reading is compared differs.

```
r_i  = y_i − m_ref,i                                   (sensor units)
b_i ← b_i + η_b · (r_i − b_i)
v_i ← (1 − η_σ) · v_i + η_σ · (r_i − b_i)²
σ_i² ← max(σ_min,i², v_i − s²_ref,i)
```

| Arm | Reference `(m_ref, s²_ref)` | Role |
|---|---|---|
| **G0** | none (θ fixed at θ0) | fixed policy, no adaptive outcome feedback |
| **G1** | same-time leave-one-out consensus: precision-weighted static fusion of the *other* sensors' readings at the same step, mapped through the static measurement equations (no dynamics, no action) | same-time observational consistency; never uses a post-action prediction |
| **G2** | latent mean/variance from the frozen pre-action receipt `R_{t+1}` | externally grounded, action-conditioned |
| **G3** (diagnostic) | as G2, plus a dependency-aware likelihood: sensors with the same `declared_upstream` share a variance component (learned τ²) and a group bias; relay copies are collapsed onto their declared source | sensor-dependency representation |
| **G2-S** (sham) | as G2, but against a receipt computed for a sham action `Ã_t` committed in the same receipt (derangement defined below) | must pass the sham validity checks SV1–SV4 below before any outcome |
| **REF-S** (evaluator only) | true sensor parameters and true dependency structure, no learning | upper bound on what sensor learning can achieve; normalizes descriptive closure |
| **REF-Z** (evaluator only) | full hidden state Z_t, myopic optimal action under the cost | reference action and regret |

**G2-S derangement.** `Ã` is a **deterministic derangement** of the logged
DEFER-step actions within each deployment's learning phase:
1. Order the DEFER steps by sha256(deployment\|t).
2. The step at rank k gets the logged action at rank k+1, cyclically.

Exact action counts are preserved and the action→outcome pairing is broken.

**Sham validity (preregistered; computed from the logs and predictions
only, before any control outcome):**
* SV1: exact marginal action frequencies preserved;
* SV2: the pairing changed;
* SV3: at least 80% of sham actions differ from the logged action;
* SV4: mean KL between the genuine and sham predictions ≥ 0.05 nats on the
  steps where B0 gate 13 shows actions matter.

If any check fails, F3 is not evaluated and is reported as invalid.

**Predictor invariant.** All arms use the frozen B0 v1.3 predictor (§2)
unchanged. Only `(b, σ)` differ. **V0 (validity check, before any
outcome):** `lineage_b/agent/predictor.py` is byte-identical to `94f4f11`,
and every arm's receipts are produced by its `categorical` / `predict`.

**REF-S** (B0 §10): the same observations, timing, action space, authority
layer and controller, plus true sensor-fault parameters. It never sees
hidden h. REF-S and REF-Z live in `lineage_b/ref.py`. They share no state
with G0–G3 or G2-S and never affect agent behaviour (B0 gate 7).

## 4. Authority layer (frozen, arm-independent)

Each step:

1. **Interlock (terminal COMMIT).** Uses raw fresh L1–L3 values, never θ:
   at least 2 of 3 at or above `h_IL^hi` → COMMIT(open); at least 2 of 3 at
   or below `h_IL^lo` → COMMIT(close).
2. **Terminal ABSTAIN.** At least 2 of L1–L3 are MISSING → ABSTAIN, mapped
   to `inspect`.
3. **Otherwise DEFER → arbitration.** The shared controller, using the
   arm's belief, proposes COMMIT(open|hold|close) or ABSTAIN(inspect):
   * if `P(ℓ ≠ none) ≥ τ_I` and there was no inspection in the last
     `R_cool` steps → ABSTAIN;
   * else `argmin_a E_b[c_D (h_{t+1} − h*)² + c_U 1[h_{t+1} ∈ U]] + c_M 1[a ≠ hold]`.

All final actions pass through
`morphsat.terminal_authority.resolve_terminal_authority`, which is
unchanged. θ can only change step 3 (lawful routing/arbitration). Each step
writes an immutable `ControlDecisionEvent`: arm, t, monitor_action,
proposal, final, resolved_by, theta_hash, receipt_hash, propensity,
visible_digest and canonical_hash.

## 5. Logging policy μ and off-policy estimator

* **μ (learning phase only).** At DEFER steps, take the G0 controller's
  action (θ0) with probability 1 − ε. Otherwise take one of the other three
  lawful actions in {open, hold, close, inspect}, uniformly. Record the
  propensity. Interlock and terminal-ABSTAIN steps are non-randomized
  (propensity 1) and are excluded from OPE.
* **θ updates are unweighted.** Sensor errors are independent of action and
  history given state, and missingness is MCAR (B0). Selection on `A_t`
  therefore does not bias conditional sensor-error estimates.
* **OPE (secondary; established methodology, not a contribution).**
  * Setting: one-step contextual bandit on learning-phase DEFER steps, with
    reward `r_t = −c(Z_{t+1}, A_t)` (one-step cost, evaluator-computed).
  * Target: each arm's frozen deterministic policy π_g.
  * Estimators: IPS, DM, and doubly robust (Dudík, Langford & Li 2011):
    `V̂_DR = mean_t[ q̂(x_t, π_g(x_t)) + 1[a_t = π_g(x_t)] / μ(a_t|x_t) · (r_t − q̂(x_t, a_t)) ]`.
  * Model: `q̂` is per-action ridge regression (λ fixed) on visible features
    (posterior mean and variance of h, P(ℓ ≠ none), u, sensor status
    flags), 2-fold cross-fitted by deployment.
  * Truth: exact counterfactual one-step cost by CRN replay of step t with
    action π_g(x_t). Bias, RMSE and 95% CI coverage are reported.
  * OPE does not enter the falsification criteria. Multi-step OPE is out of
    scope.

## 6. Outcomes (evaluation phase unless stated; prediction and control kept separate)

**Prediction (secondary):**
* log score and Brier score per sensor over frozen bins (VALUE observations
  only; missing counts reported);
* calibration: 50% and 90% central-interval coverage;
* all of these by sensor and by dependency group (ADC_A pair, L3, P, F,
  alias L4).

**Control** (evaluator truth). Per deployment, each metric is the mean over
its `E_E` evaluation episodes.
* Task cost per episode:
  `J = Σ_t [c_U 1[h ∈ U] + c_D (h − h*)² + c_I 1[inspect] + c_M 1[Δu ≠ 0] + c_L q_leak dt + c_S spill dt]`.
* Unsafe-transition rate: steps going from safe to unsafe, per step.
* False-safe rate, per step: a hazard is present and `A_t` is not in the
  union of its corrective sets:
  * high band → {open};
  * low band → {close};
  * leak → {inspect}.
* Action error: on DEFER steps, `A_t ≠ A_t^{REF-Z}`.
* Coverage: share of DEFER steps resolved to open/hold/close.
* Selective risk: action error among covered steps.
* Inspect rate (all steps).
* Regret: `J − J_REF-Z`.

## 7. Falsification criteria (frozen at the sizing-design freeze)

### Frozen constants (the single definition of each)

All are derived from the independent B0 pilot (`06d5d24`, gate 17) or fixed
a priori. None is computed from B1 or from the sizing run.

| Name | Value | Source |
|---|---|---|
| Δ* (primary minimum effect) | **1.737 J** | 0.10 × 17.37, where 17.37 is the B0 pilot's pooled C1–C5 `J_G0 − J_REF-S` |
| δ_null (F5 margin) | **0.8876 J** | 0.02 × 44.38, where 44.38 is the B0 pilot's C0 mean `J_G0` |
| δ_cond (F6 margin) | **= Δ* = 1.737 J** | — |
| δ_safe,unsafe (F4) | **0.0005 per step** (absolute) | fixed a priori (v1.1) |
| δ_safe,fs (F4) | **0.005 per step** (absolute) | fixed a priori (v1.1) |

### Analysis rules

* The unit is the deployment. Arms are paired by common random numbers.
* "Pooled" means the equal-weight mean of per-condition means over C1–C5.
* The primary endpoint is mean J per evaluation episode.
* Every CI is a stratified paired **percentile bootstrap**: 10,000
  resamples with a frozen seed, resampling deployments within condition.
* "CI" means the 95% two-sided interval. Its lower/upper bound is the
  2.5% / 97.5% bootstrap percentile.

### Criteria

* **P0 (precondition: a learnable gap exists).** The pooled
  `J_G0 − J_REF-S` has a CI lower bound > 0. If not, B1 is
  **uninformative**.
* **F1 (primary: beyond same-time consensus).** For the pooled
  `Δ12 = J_G1 − J_G2`, both:
  * its CI lower bound > 0; **and**
  * its point estimate ≥ Δ*.
* **F2 (beyond fixed policy).** Pooled `J_G0 − J_G2` has a CI lower
  bound > 0.
* **F3 (action-conditioning).** Pooled `J_G2-S − J_G2` has a CI lower
  bound > 0. It is not evaluated if SV1–SV4 fail.
* **F4 (safety non-inferiority).** The CI upper bound is ≤ δ_safe,unsafe
  (unsafe-transition rate) and ≤ δ_safe,fs (false-safe rate). This holds
  for each of `(G2 − G1)` and `(G2 − G0)`, both pooled and within C5.
* **F5 (no harm when nothing is wrong).** In C0, the CI upper bound of
  `J_G2 − J_G0` is ≤ δ_null.
* **F6 (condition-level non-inferiority).**
  * For each c ∈ C1–C5, compute the frozen 95% two-sided stratified paired
    percentile-bootstrap CI (the same machinery as every other criterion)
    for `J_G2 − J_G1` within condition c.
  * Condition c passes iff that CI's upper bound is ≤ δ_cond = 1.737 J.
  * **F6 holds iff all five conditions pass.**
  * This is an intersection–union test: the claim is "all five conditions
    are non-inferior". Requiring every individual test to pass already
    controls the global Type-I error, conservatively. No multiplicity
    adjustment is applied.

**Descriptive only (no criterion):** the realized closure
`Δ12 / (J_G0 − J_REF-S)`, using the B1-measured denominator. It never
redefines Δ* or the negative decision boundary.

### Outcome mapping

A confirmatory run only happens at N ≥ N_required (§7a), so every
confirmatory result is planned to be powered for Δ*. Because sizing uses a
normal approximation, a negative is still stated only when the CI excludes
Δ*.

| Result | Conclusion |
|---|---|
| ¬P0 | Uninformative; report and stop |
| ¬F1 and the CI upper bound of Δ12 < Δ* | **"The preregistered pilot-derived minimum effect of 1.737 J was not supported"** (G2 vs same-time consensus, in this simulator) |
| ¬F1, otherwise | **Inconclusive:** the data neither show nor exclude an effect of Δ*. Never called falsified |
| F1 ∧ F2 ∧ ¬F3 (F3 valid) | "Observation-based learning helped; action-conditioned grounding not isolated" |
| F1 with F3 invalid (SV failed) | No ceiling claim; report the F1/F2 results with the sham invalid |
| F1 ∧ (¬F4 ∨ ¬F5 ∨ ¬F6) | No positive claim; report as an improvement with safety or condition-level harm |
| P0 ∧ F1–F6 | Claim at the §0 ceiling |

G3 is diagnostic: `J_G2 − J_G3` and dependency-group prediction scores per
condition, with no criterion. A G3 advantage may only be stated at its
ceiling.

## 7a. Sample size: blinded paired-variance sizing stage

**Why.** The B0 pilot's conservative bound, Var(Δ12) ≤ 2·Var(J_G0), gave
N_required = 1659. That bound ignores the CRN pairing. This stage replaces
it with empirical paired-difference variances for **every** quantity the
positive claim needs, without using any observed mean effect.

**Sizing set.**
* Root **2026100516000**. It is new, and disjoint from the B0
  (…15000–…15999), pilot (…13000), B1 confirmatory (…14000) and B1
  implementation-validation (…17000) roots and from all earlier roots.
* The sizing root is **first touched by the one official sizing
  execution**. No development, debugging or implementation-validation run
  may use it.
* Spawn keys (condition, deployment).
* **n_s = 50 deployments per condition, C0–C5.**
* Sizing deployments are permanently excluded from confirmatory B1.

**Arms run for sizing:** G0, G1, G2, G2-S and REF-S, through the full §1
protocol. G3 and REF-Z are not run.

**Validity before any variance is used** (within the one official sizing
execution):
* Re-assert V0's static part (`predictor.py` byte-identical to `94f4f11`).
  It uses no seeds. The full V0 already ran in implementation validation
  (§7b).
* **SV1–SV4 are evaluated on the sizing set** before its variances are
  accepted, because they depend on the actual frozen sham construction and
  the logged stream.
* If V0 fails, stop.
* If any SV fails, stop and report a sham-design failure. Do not tune, and
  do not reuse the sizing set.

**Effect blinding.** The sizing script holds per-deployment arm metrics in
memory only. It writes **only** these to its receipt:
* the sample variances (ddof = 1) of the preregistered per-deployment
  paired differences, by condition;
* their UCLs;
* n_s;
* N_q per quantity and N_required;
* V0 / SV results;
* engine metadata.

The sizing implementation may maintain a mean only as a transient numerical
intermediate required for variance computation. No per-arm mean,
paired-difference mean, sign, winner, effect estimate or per-deployment
difference may be emitted, printed, logged, persisted, exposed to the
experimenter, or used in any sizing or design decision. No closure or
P0/F1–F6 quantity is computed.

**Variance upper confidence bounds** (using the two frozen chi-square
constants below):
* **Family (pooled C1–C5 quantities, and F6's five conditions):** Bonferroni
  at family-wise 95%, α_c = 0.01 per condition:
  `s²_UCL,c = 49·s_c² / 28.940645973381493` (multiplier 1.6931204661).
* **Single-condition quantities (C0 for F5; C5 for F4-C5):** one-sided 95%:
  `s²_UCL = 49·s² / 33.93030561852784` (multiplier 1.4441367122).

**Frozen chi-square constants.** n_s = 50 is frozen, so the degrees of
freedom are fixed at 49 and only two lower-tail quantiles are ever needed:

| Constant | Value | Use |
|---|---|---|
| χ²_{0.01; 49} | **28.940645973381493** | family UCL |
| χ²_{0.05; 49} | **33.93030561852784** | single-condition UCL |

* **Provenance.** Supplied by the user (2026-10-06). Independently
  reproduced bit for bit with `scipy.stats.chi2.ppf(p, 49)`, scipy 1.17.1,
  installed outside the repository. Round-trip: `chi2.cdf` returns 0.01
  and 0.05. Consistent with the published table values 28.941 and 33.930.
  scipy is not a project dependency and is not used by B1 code.
* **No numerical special-function engine is implemented.** There is no
  incomplete-gamma function and no inverse chi-square solver.
* **Constant-integrity check, before use:**
  * the code's two constants equal the literals above exactly;
  * each rounds to its table value (28.941, 33.930) at 3 decimals;
  * `49/χ²` reproduces the multipliers 1.6931204661 and 1.4441367122 to
    1e-10.

  If any check fails, stop.

**Sizing projections.** For a quantity q, let S be its condition set and z_q
its normal quantile. Each projection uses the target half-width h_q:

  N_q = ⌈ z_q² · Σ_{c∈S} s²_UCL,c / (\|S\|² · h_q²) ⌉.

| q | Per-deployment paired difference | S | UCL | z_q | h_q |
|---|---|---|---|---|---|
| P0 | J_G0 − J_REF-S | C1–C5 | family | 1.96 | ½Δ* = 0.8685 J |
| F1 | J_G1 − J_G2 | C1–C5 | family | 1.96 | ½Δ* |
| F2 | J_G0 − J_G2 | C1–C5 | family | 1.96 | ½Δ* |
| F3 | J_G2-S − J_G2 | C1–C5 | family | 1.96 | ½Δ* |
| F4 (4 quantities) | rate_G2 − rate_G1 and rate_G2 − rate_G0, for unsafe-transition and false-safe rates (per-deployment paired difference in rates) | C1–C5 | family | 1.96 | ½δ_safe of that metric |
| F4-C5 (4 quantities) | same | C5 | single | 1.96 | ½δ_safe of that metric |
| F5 | J_G2 − J_G0 | C0 | single | 1.96 | ½δ_null |
| F6 (5 quantities) | J_G2 − J_G1 | each of C1–C5 alone | family (conservative) | 1.96 | ½δ_cond |

**P0's half-width is a precision target, not a power guarantee.**
h_P0 = ½Δ* = 0.8685 J is a deliberately conservative precision target for
the P0 contrast; the B0 pilot gap was 17.37 J. Because P0's true gap is not
assumed, variance-only sizing cannot guarantee that P0 will pass. The
0.8685-J target controls planned precision. If the confirmatory bootstrap
lower bound for G0 − REF-S is not > 0, P0 fails and B1 is uninformative
regardless of achieved precision. That outcome is reported as
"uninformative; stop", not as a sizing failure.

**N rule (frozen).**
* N_required = max_q N_q.
* **N_min = 50; N_max = 3000.**
* If N_required ≤ 3000: N = max(N_required, N_min).
* **If N_required > 3000: B1 is infeasible as the planned confirmatory
  experiment. Stop before confirmatory execution.** Neither Δ* nor any
  safety or non-inferiority margin is raised to fit.

**Approximation.**
* Normal-approximation sizing is a planning approximation only.
  Confirmatory decisions use the frozen paired percentile bootstrap (§7).
* The chi-square variance UCL is exact under normally distributed paired
  differences. In B1 it is used as a conservative planning approximation;
  confirmatory inference does not use the chi-square assumption and remains
  the frozen paired percentile bootstrap.
* **F4 sizing unit.** The sizing variable for F4 is the per-deployment
  paired difference in rates: a bounded, continuous deployment-level
  statistic. The same across-deployment variance and half-width framework
  applies. No step-level binomial formula is used.

## 7b. Pre-sizing implementation validation (dedicated root)

**Root 2026100517000** is reserved permanently and exclusively for
pre-sizing implementation checks. It is disjoint from the B0 roots, the B0
pilot root, and the B1 sizing and confirmatory roots (§7a, §15). Nothing
derived from it may enter any sizing or confirmatory analysis.

These checks run after the B1 implementation is committed and before the
sizing root is touched. They are **implementation-validity checks, not
scientific outcomes**.

| Check | Applied to | Semantics (adapted from B0) |
|---|---|---|
| V0 | all arms | `predictor.py` byte-identical to `94f4f11`; every arm's receipts produced by its `categorical` / `predict` |
| Gate 7 (hidden-state separation) | G1, G2, G3, G2-S | the AST import rule holds for each arm's modules; replaying a recorded stream while the harness holds a different hidden world, and under NaN-poisoned evaluator state, gives identical decisions, receipts and θ hashes for each arm |
| Gate 11 (future-only influence) | G1, G2, G3, G2-S | perturbing records delivered after t leaves every decision ≤ t identical; randomized θ leaves interlock and terminal-ABSTAIN outputs identical; the monitor stays θ-blind |
| Gate 12 (terminal authority) | G1, G2, G3, G2-S | `terminal_authority.py` unchanged versus `eb3f6d3`; every final action comes from `resolve_terminal_authority`; no learned or sham mechanism can rewrite or bypass a terminal decision; G2-S's sham action enters only its receipt reference, never the executed action |

G3 is checked even though it is not a sizing arm, because it exists in the
implementation and runs in confirmatory B1.

**Not done on this root:** no G1/G2/G3/G2-S outcome comparison, no cost or
safety metric contrast, and no variance.

**On failure:**
* stop;
* preserve the failing implementation and its receipt;
* do not touch the sizing or confirmatory seeds.

Any later code correction is a new implementation commit with its
validation lineage disclosed. Validation is then re-run on root
2026100517000.

## 8. Expectations stated before outcomes (design-induced; not evidence)

| Condition | Expected | Why |
|---|---|---|
| C0 | G0 ≈ G1 ≈ G2 | θ0 is already correct; C0 tests F5 only |
| C1 (L3 stuck) | G1 ≈ G2 | an honest majority lets consensus find the stuck sensor |
| C2 (ADC_A bias) | G2 > G1 likely; G3 ≥ G2 | consensus is 2 biased vs 2 honest; G2 has dynamics plus flow (`q_out ∝ √h`) as an absolute anchor |
| C3 (drift + alias) | G2 > G1; G3 > G2 | the alias reinforces the drifting sensor in consensus; drift shows as a residual trend against dynamics |
| C4 (P noise, F bias) | G1 ≈ G2 | both see the disagreement |
| C5 (missing/delayed) | G0 ≈ G1 ≈ G2 | no value faults; tests absence handling and F4 |

So any pooled F1 advantage is expected to come mainly from C2 and C3. Those
are conditions the designer chose (B0 T-B1). This table is fixed now so a
design property is not reported as a discovery.

## 9. Diagnostics (reported, no criteria)

* Per-condition tables of every metric and arm.
* θ trajectories during learning; time to detection after `t_f`.
* G1 vs G0: the effect of same-time consensus learning alone.
* OPE validity (§5).
* Missing/PENDING counts.
* Interlock activations per arm. These are arm-independent by
  construction, so a difference indicates a bug.
* **C0 learned-noise diagnostic.** In C0 every sensor's true (b, σ) is
  nominal. Each arm's learned b̂_i and σ̂_i/σ_nom,i in C0 measure how much
  its reference distorts noise learning (T6).

## 10. Threats

* **T1 Designer-determined identifiability** (§8; B0 T-B1).
* **T2 Truthful declared provenance.** Laundering is not modelled; G3's
  input is assumed correct.
* **T3 Learning persists only within a deployment.** Poisoning persistence
  and recovery across deployments, and adaptive adversaries, are out of
  scope (B-U6). Cross-episode trust dynamics beyond this remain a separate
  lineage.
* **T4 Frozen θ in evaluation** measures what was learned, not online
  adaptation.
* **T5 Matched-rule assumption.** G1 is one specific same-time consensus
  rule, not every possible consistency-based learner.
* **T6 Residual predictor conservatism.** B0 gate 18 passed with coverage
  above nominal: residual conservative calibration. Its source is not
  decomposed.
  * If predictive variance is overstated, G2's learned sensor variance
    (`σ² = v − s²_ref`) may be biased downward. G1's static reference does
    not share that bias.
  * No magnitude is assigned before B1 measures it.
  * B0 and P1–P7 are not modified.
  * The §9 C0 learned-(b, σ) diagnostic measures it, and F5 guards its
    control cost.
* **T7 Retained predictor mismatches** P1–P7 (B0 v1.3 §0.3). They are not
  investigated in B1.

## 11. Literature

Methods are established and cited only as verified:
* Gneiting & Raftery 2007 (proper scoring rules);
* Dawid & Skene 1979 (agreement-based reliability, the spirit of G1);
* Dudík, Langford & Li 2011 (doubly robust).

Adaptive estimation of noise statistics is prior art. Bibliographic records
verified 2026-10-06:
* R. K. Mehra, "On the Identification of Variances and Adaptive Kalman
  Filtering," IEEE TAC 15(2):175–184, 1970. doi:10.1109/TAC.1970.1099422.
* R. K. Mehra, "Approaches to Adaptive Filtering," IEEE TAC 17(5):693–698,
  1972. doi:10.1109/TAC.1972.1100100.
* K. A. Myers & B. D. Tapley, "Adaptive Sequential Estimation with Unknown
  Noise Statistics," IEEE TAC 21(4):520–523, 1976.
  doi:10.1109/TAC.1976.1101260.

G2's noise update belongs to the innovation/covariance-adaptation family
these works establish. No claim of exact algorithmic identity is made; the
papers' methods have not been inspected for that. Other recent leads are
unverified and not cited.

No novelty claim. Sequential OPE estimators are not used and not cited.

## 12. Changes from v1.0 (`c57185c`)

* Headline question: action-conditioned temporal feedback vs same-time
  observational consistency.
* Ceiling sentence updated.
* G2-S switched to a deterministic derangement, with SV1–SV4.
* Predictor invariant made explicit.
* REF-S constrained.
* F6 uses Holm correction (superseded in v1.4: per-condition CI,
  intersection–union, §17).
* Margins frozen before the pilot.
* Planned follow-on B2 (not part of B1): learning which reason + action +
  evidence-path types hold up, using FeedbackRecords, with a fixed path
  vocabulary and verdicts drawn from evidence outside each path.

## 13. Changes from v1.1 (`6ea1628`) to v1.2 (`909d8ae`)

* B0 status: CLOSED / PASSED (`06d5d24`).
* §2 uses the frozen B0 v1.3 predictor, with V0.
* A blinded sizing stage replaces the cap-at-200 rule.
* "¬F1 = falsified" removed.
* T6, T7 and the C0 diagnostic added.

## 14. Changes from v1.2 (`909d8ae`)

1. Two explicit freezes (§15).
2. Sizing: n_s = 50 per condition, C0–C5. Arms G0, G1, G2, G2-S, REF-S;
   no G3 or REF-Z.
3. Variance UCLs: Bonferroni family-wise 95% (α_c = 0.01) for pooled and
   F6 quantities, and one-sided 95% for single-condition quantities, both
   by a frozen chi-square rule with an engine check (engine replaced by two
   frozen constants in v1.4, §17). The 80% rule is removed.
4. Δ* = 1.737 J, an absolute effect from the B0 pilot, used for sizing and
   for F1's point threshold and negative boundary. Closure is descriptive
   only.
5. δ_null = 0.8876 J, fixed from the B0 pilot's C0 (no longer a B1-measured
   formula).
6. F6 becomes condition-level non-inferiority with margin Δ*, using Holm at
   family-wise 0.05 (superseded in v1.4, §17).
7. N_required is the maximum over P0, F1–F6, rather than Δ12 alone.
8. N_min = 50, N_max = 3000; above N_max, stop.
9. "Internal history" wording removed. G1 is described only as same-time
   consensus / observational consistency.
10. T6 is qualitative only; the numeric estimate is removed.
11. Verified Mehra 1970/1972 and Myers & Tapley 1976 records added, with no
    identity claim.

## 15. Freezes and procedure

a. **Sizing-design freeze** (this document, on user authorization). Frozen:
   * every scientific rule, arm definition, outcome, frozen constant (§7)
     and analysis rule;
   * the implementation-validation checks and root (§7b);
   * the sizing algorithm, sizing seeds and sizing validity rules (§7a).

   Left open: **only** N, the confirmatory seed-list hash and the sizing
   receipt.

b. Implement all B1 arms (G1, G2, G3, G2-S; G0, REF-S and REF-Z as
   specified).

c. Commit the implementation, with no execution of validation or sizing in
   the same commit.

d. Run the dedicated implementation-validation checks (§7b) on root
   2026100517000. If any fails, stop.

e. Only if they pass: run the sizing set **once** on root 2026100516000.
   In order: the chi-square constant-integrity check, V0 static
   re-assertion, SV1–SV4, then blinded variance sizing (§7a).

f. If N_required > 3000, stop: B1 is infeasible as planned.

g. Otherwise, the **confirmatory freeze**. The only permitted changes are:
   * fill in N from the frozen formula;
   * generate the confirmatory seed list (root 2026100514000, spawn keys
     (condition, deployment), deployments 0..N−1, C0–C5) and freeze its
     sha256;
   * record the sizing receipt.

   No hypothesis, margin, arm, endpoint, update rule or analysis rule may
   change after sizing. Any other change starts a new amendment or lineage.

h. Run confirmatory B1 once.

i. Report and stop.

## 16. Review items (all resolved; none open at the sizing-design freeze)

1. **Resolved (v1.5).** Implementation checks before sizing: V0 and
   adapted B0 gates 7, 11 and 12 for G1, G2, G3 and G2-S, on the dedicated
   validation root 2026100517000 (§7b), never on the sizing root. SV1–SV4
   stay in the official sizing execution (§7a).
2. **Resolved (v1.4).** F6 uses the conservative family UCL.
3. **Resolved (v1.5).** h_P0 = ½Δ* = 0.8685 J, a precision target and not a
   power guarantee (§7a).
4. **Resolved (v1.4).** F6 is an intersection–union test of five ordinary
   95% CIs; no Holm.

## 17. Changes from v1.3 (`de88044`) to v1.4

1. **Chi-square engine removed** (it existed only as specified text; no code
   had been written). Replaced by two frozen constants with provenance and a
   constant-integrity check (§7a). df = 49 is fixed by n_s = 50.
2. **F6 replaced.** The raw-replicate bootstrap p-value and Holm are
   removed. Each of C1–C5 needs the upper bound of the frozen 95% paired
   percentile-bootstrap CI for `J_G2 − J_G1` to be ≤ 1.737 J. F6 holds iff
   all five pass (intersection–union; no adjustment). F6 sizing uses
   z = 1.96 with h = ½δ_cond and keeps the conservative family UCL.
3. **Blinding wording.** Transient numerical means are allowed only inside
   the variance computation; nothing effect-revealing is ever emitted,
   persisted, exposed or used.
4. **Approximation disclosure** extended to the chi-square variance UCL.
5. **F4 sizing unit** made explicit: the per-deployment paired difference in
   rates; no step-level binomial formula.

Unchanged:
* n_s = 50 (C0–C5);
* the sizing arms G0/G1/G2/G2-S/REF-S;
* Δ* = 1.737 J;
* δ_null = 0.8876 J;
* the max-of-endpoints rule;
* N_min = 50 and N_max = 3000, with stop above 3000;
* T6 as a documented threat;
* the same-time consensus wording.

## 18. Changes from v1.4 (`36af9f9`) to v1.5 (procedural only)

1. Dedicated implementation-validation root 2026100517000 and §7b
   (V0 plus gates 7/11/12 adapted, for G1/G2/G3/G2-S). The sizing root is
   first touched by the official sizing execution.
2. SV1–SV4 explicitly remain sizing-stage checks. On failure: stop, with no
   tuning and no reuse of the sizing set.
3. h_P0 = 0.8685 J, worded as a precision target with the no-guarantee
   statement.
4. Every §16 item is resolved.
5. Procedure order a–i (§15).

No hypothesis, margin, arm, sizing formula or analysis rule changed.

## Appendix: structural compute estimate (not a criterion; no arm outcome used)

The estimate is anchored on B0's measured cost: gate 18 ran 4,000
agent-steps in 18.9 s, ≈ 4.7 ms per full agent-step on this machine. G3,
OPE replays and the G2-S sham receipt add an estimated 10–30%; the ranges
below include that.

**Sizing.** 6 conditions × 50 = 300 deployment-conditions.
* Learning ≈ 1,000 steps × 4 receipt-committing arms; evaluation ≈ 5
  controllers × 1,000 steps.
* ≈ 9,000–10,000 agent-steps ≈ 42–48 s each.
* Total ≈ **3.5–4 h single-core**, ≈ **30–50 min on 8 cores**.

**Confirmatory.** All 7 arms, ≈ 13,000 agent-steps ≈ 60–75 s per
deployment-condition, × 6 conditions × N.

| N | Deployment-conditions | Single-core | 8 physical cores (ideal–realistic) |
|---|---|---|---|
| 50 (N_min) | 300 | ≈ 5–6 h | ≈ 40 min–1 h |
| 200 | 1,200 | ≈ 20–25 h | ≈ 2.5–4 h |
| 1,659 | 9,954 | ≈ 7–8.5 days | ≈ 21–35 h |
| 3,000 (N_max) | 18,000 | ≈ 12.5–15.5 days | ≈ 1.6–3 days |

The work box is a Ryzen 7 7735U (8 cores / 16 threads, 15 GB), a managed
laptop. Runs beyond about a day belong on the home box or RunPod.
