# Lineage B1 — Grounded Causal Feedback: Preregistration v1.3 (CANDIDATE)

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
* v1.3 applies the user's 2026-10-06 pre-freeze corrections (§14). Scope:
  public GitHub lineage of `14689b7`.

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
  * For each c ∈ C1–C5, test H0_c: E[J_G2 − J_G1] ≥ δ_cond against H1_c:
    E[J_G2 − J_G1] < δ_cond.
  * The one-sided bootstrap p-value is p_c = (1 + #{b : θ*_{c,b} ≥ δ_cond})
    / (1 + 10,000), where θ*_{c,b} is the bootstrap mean of
    `J_G2 − J_G1` in condition c.
  * F6 holds iff **Holm's step-down procedure at family-wise α = 0.05
    rejects all five H0_c**.
  * Bonferroni-adjusted one-sided 99% upper bounds are reported
    descriptively.

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
  (…15000–…15999), pilot (…13000) and B1 confirmatory (…14000) roots and
  from all earlier roots.
* Spawn keys (condition, deployment).
* **n_s = 50 deployments per condition, C0–C5.**
* Sizing deployments are permanently excluded from confirmatory B1.

**Arms run for sizing:** G0, G1, G2, G2-S and REF-S, through the full §1
protocol. G3 and REF-Z are not run.

**Validity before any variance is used.**
* V0 and SV1–SV4 are evaluated on the sizing set and recorded.
* If V0 fails, stop.
* If SV fails, stop and report as a design defect. Nothing is tuned.

**Effect blinding.** The sizing script holds per-deployment arm metrics in
memory only. It writes **only** these to its receipt:
* the sample variances (ddof = 1) of the preregistered per-deployment
  paired differences, by condition;
* their UCLs;
* n_s;
* N_q per quantity and N_required;
* V0 / SV results;
* engine metadata.

It does not compute, store, print or log any per-arm mean, paired-difference
mean or sign, winner, closure, or P0/F1–F6 quantity. No per-deployment
difference is persisted.

**Variance upper confidence bounds** (computed by the frozen chi-square rule
below; no multiplier is hard-coded):
* **Family (pooled C1–C5 quantities, and F6's five conditions):** Bonferroni
  at family-wise 95%, α_c = 0.01 per condition:
  `s²_UCL,c = (n_s − 1)·s_c² / χ²_{0.01; n_s−1}`.
* **Single-condition quantities (C0 for F5; C5 for F4-C5):** one-sided 95%:
  `s²_UCL = (n_s − 1)·s² / χ²_{0.05; n_s−1}`.

Here χ²_{p; k} is the lower p-quantile.

**Chi-square quantile rule.**
* Bisection on the regularized lower incomplete gamma P(k/2, x/2), with
  bracket [0, k + 20√(2k)], to \|Δx\| ≤ 1e-12.
* P is computed by its power series, to a relative term size ≤ 1e-16, using
  `math.lgamma`.
* **Engine check, before use:** χ²_{0.05; 49} and χ²_{0.01; 49} must match
  the published table values 33.930 and 28.941 to within 1e-3. If not,
  stop.

**Sizing projections.** For a quantity q, let S be its condition set and z_q
its normal quantile. Each projection uses the target half-width h_q:

  N_q = ⌈ z_q² · Σ_{c∈S} s²_UCL,c / (\|S\|² · h_q²) ⌉.

| q | Per-deployment paired difference | S | UCL | z_q | h_q |
|---|---|---|---|---|---|
| P0 | J_G0 − J_REF-S | C1–C5 | family | 1.96 | ½Δ* |
| F1 | J_G1 − J_G2 | C1–C5 | family | 1.96 | ½Δ* |
| F2 | J_G0 − J_G2 | C1–C5 | family | 1.96 | ½Δ* |
| F3 | J_G2-S − J_G2 | C1–C5 | family | 1.96 | ½Δ* |
| F4 (4 quantities) | rate_G2 − rate_G1 and rate_G2 − rate_G0, for unsafe-transition and false-safe rates | C1–C5 | family | 1.96 | ½δ_safe of that metric |
| F4-C5 (4 quantities) | same | C5 | single | 1.96 | ½δ_safe of that metric |
| F5 | J_G2 − J_G0 | C0 | single | 1.96 | ½δ_null |
| F6 (5 quantities) | J_G2 − J_G1 | each of C1–C5 alone | family | 2.326 (Bonferroni one-sided 0.01; conservative for Holm) | ½δ_cond |

**N rule (frozen).**
* N_required = max_q N_q.
* **N_min = 50; N_max = 3000.**
* If N_required ≤ 3000: N = max(N_required, N_min).
* **If N_required > 3000: B1 is infeasible as the planned confirmatory
  experiment. Stop before confirmatory execution.** Neither Δ* nor any
  safety or non-inferiority margin is raised to fit.

**Approximation.** Normal-approximation sizing is a planning approximation
only. Confirmatory decisions use the frozen paired percentile bootstrap
(§7).

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
* F6 uses Holm correction.
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
   by a frozen chi-square rule with an engine check. The 80% rule is
   removed.
4. Δ* = 1.737 J, an absolute effect from the B0 pilot, used for sizing and
   for F1's point threshold and negative boundary. Closure is descriptive
   only.
5. δ_null = 0.8876 J, fixed from the B0 pilot's C0 (no longer a B1-measured
   formula).
6. F6 becomes condition-level non-inferiority with margin Δ*, using Holm at
   family-wise 0.05.
7. N_required is the maximum over P0, F1–F6, rather than Δ12 alone.
8. N_min = 50, N_max = 3000; above N_max, stop.
9. "Internal history" wording removed. G1 is described only as same-time
   consensus / observational consistency.
10. T6 is qualitative only; the numeric estimate is removed.
11. Verified Mehra 1970/1972 and Myers & Tapley 1976 records added, with no
    identity claim.

## 15. Freezes and procedure

1. **Sizing-design freeze** (this document, on user authorization). Frozen:
   * every scientific rule, arm definition, outcome, frozen constant (§7)
     and analysis rule;
   * the sizing algorithm, sizing seeds and sizing validity rules (§7a).

   Left open: **only** N and the confirmatory seed-list hash.
2. Implement the arms. Commit the implementation **before** any sizing
   execution.
3. Run the sizing stage once (§7a): chi-square engine check, then V0 and
   SV1–SV4, then blinded variances, then N.
4. **Confirmatory freeze.** The only permitted changes are:
   * fill in N from the frozen formula;
   * generate the confirmatory seed list (root 2026100514000, spawn keys
     (condition, deployment), deployments 0..N−1, C0–C5) and freeze its
     sha256;
   * record the sizing receipt.

   No hypothesis, margin, arm, endpoint, update rule or analysis rule may
   change after sizing. Any other change starts a new amendment or lineage.
5. Run confirmatory B1 once. Then report and stop.

## 16. Remaining items for review (decide before the sizing-design freeze)

1. **B1 implementation checks before sizing variances.** Proposed:
   * V0;
   * SV1–SV4;
   * re-running B0 gates 7 (hidden-state separation), 11 (future-only
     updates; θ-blind authority) and 12 (terminal authority untouched)
     with each new arm substituted, on sizing seeds.

   Any failure means stop.
2. **F6 family UCL.** F6's five per-condition variances use the family
   (Bonferroni 0.01) UCL rather than the single-condition 95% rule, because
   all five must hold simultaneously. Confirm.
3. **P0's projection** uses h = ½Δ*, the same as F1–F3. This is
   conservative for a precondition. Confirm or specify another target.
4. **F6 multiplicity.** "All five must reject" is an intersection–union
   claim, for which unadjusted level-0.05 tests would already control the
   error. Holm is kept as specified, which is more conservative.

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
