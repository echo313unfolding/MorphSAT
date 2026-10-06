# Lineage B1 — Grounded Causal Feedback: Preregistration v1.2 (CANDIDATE)

Status: **candidate; not frozen.**
* B0 is **CLOSED / PASSED**: v1.3 `701c4c2` + T6 amendment v1.3.1 `ebdb0f1`,
  implementation `94f4f11`, results `06d5d24`
  (`docs/LINEAGE_B0_V13_RESULTS.md`). B0 is not modified or rerun.
* B1 is frozen without looking at any G1/G2/G3/G2-S outcome, including the
  sizing stage (§7a), whose only output is a variance.
* No G1/G2/G3/G2-S code exists.
* v1.2 applies the user's 2026-10-06 corrections (§13). Scope: public GitHub
  lineage of `14689b7`.

## 0. Question and ceiling

**Primary question.** Does action-conditioned temporal feedback add value
beyond same-time observational consistency?

* G1 learns: "sensor A tends to disagree with the other sensors."
* G2 learns: "after I took action X, sensor A reported something different
  from what should have happened."

G1 already learns from external observations. B1 therefore does **not**
test "external feedback vs internal history".

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
| **REF-S** (evaluator only) | true sensor parameters and true dependency structure, no learning | upper bound on what sensor learning can achieve; normalizes closure |
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
  therefore does not bias conditional sensor-error estimates. If a B0 gate
  contradicts this, B1 is re-assessed before freezing.
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

**Control** (evaluator truth):
* Task cost per episode:
  `J = Σ_t [c_U 1[h ∈ U] + c_D (h − h*)² + c_I 1[inspect] + c_M 1[Δu ≠ 0] + c_L q_leak dt + c_S spill dt]`.
* Unsafe transitions: steps going from safe to unsafe.
* False-safe: a hazard is present and `A_t` is not in the union of its
  corrective sets:
  * high band → {open};
  * low band → {close};
  * leak → {inspect}.
* Action error: on DEFER steps, `A_t ≠ A_t^{REF-Z}`.
* Coverage: share of DEFER steps resolved to open/hold/close.
* Selective risk: action error among covered steps.
* Inspect rate (all steps).
* Regret: `J − J_REF-Z`.

## 7. Falsification criteria (primary rule, frozen at B1 freeze)

**Unit and pairing.** The unit is the deployment. Arms are paired by common
random numbers. The pooled fault set {C1..C5} weights conditions equally.
CIs are 95% stratified paired bootstrap (10,000 resamples, frozen seed). The
primary endpoint is mean J per evaluation episode.

* **P0 (precondition: a learnable gap exists).** The pooled
  `J_G0 − J_REF-S` has a CI lower bound > 0. If not, B1 is
  **uninformative**: there is nothing for sensor learning to fix.
* **F1 (primary: beyond internal history).** Pooled `Δ12 = J_G1 − J_G2`
  has a CI lower bound > 0, **and** closure `Δ12 / (J_G0 − J_REF-S) ≥ 0.10`
  (point estimate; minimum effect of interest).
* **F2 (beyond fixed policy).** Pooled `J_G0 − J_G2` has a CI lower
  bound > 0.
* **F3 (action-conditioning).** Pooled `J_G2-S − J_G2` has a CI lower
  bound > 0.
* **F4 (safety non-inferiority).** For unsafe-transition rate and
  false-safe rate, the upper CI bound of `(G2 − G1)` and of `(G2 − G0)` is
  ≤ `δ_safe`, both pooled and within C5 (absent/delayed feedback).
* **F5 (no harm when nothing is wrong).** In C0, the upper CI bound of
  `J_G2 − J_G0` is ≤ `δ_null`.
* **F6 (no condition-level harm).** In no single fault condition is G2
  significantly worse than G1. One-sided paired tests across C1–C5 use Holm
  correction at family-wise α = 0.05.

**Outcome mapping.** A negative primary result is a falsification **only if
the design was powered for the frozen minimum effect** (§7a outcome A) **and**
the CI excludes that effect.

| Result | Conclusion |
|---|---|
| ¬P0 | Uninformative; report and stop |
| ¬F1, powered (outcome A), and the CI upper bound of Δ12 < 0.10 × (J_G0 − J_REF-S) | **Not supported in this simulator at the frozen minimum effect:** a ≥ 10% closure by grounded feedback beyond internal history is excluded |
| ¬F1, otherwise | **Inconclusive:** the data neither show nor exclude a ≥ 10% closure. Never called falsified |
| F1 ∧ F2 ∧ ¬F3 | "Observation-based learning helped; action-conditioned grounding not isolated" |
| F1 ∧ (¬F4 ∨ ¬F5 ∨ ¬F6) | No positive claim; report as an improvement with safety or condition-level harm |
| P0 ∧ F1–F6 | Claim at the §0 ceiling |

If B1 runs under §7a outcome B (exploratory), no row may use "not
supported" or "falsified". Every F1 failure is then "inconclusive at the
10% target".

G3 is diagnostic: `J_G2 − J_G3` and dependency-group prediction scores per
condition, with no criterion. A G3 advantage may only be stated at its
ceiling.

**Margins frozen now, before the pilot and before any outcome. They are not
revisable from pilot, sizing or B1 results.**
* closure ≥ 0.10;
* δ_safe: unsafe-transition rate +0.0005/step and false-safe rate
  +0.005/step (absolute);
* δ_null = 2% of the C0 mean `J_G0` measured within B1 (formula fixed).

## 7a. Sample size: blinded paired-variance sizing stage (replaces the v1.1 cap-at-200 rule)

**Why.** The B0 pilot (`06d5d24`, gate 17) gave N_required = 1659 under the
conservative bound Var(Δ12) ≤ 2·Var(J_G0). The v1.1 cap N_max = 200 would
make the planned CI about √(1659/200) ≈ 2.9× wider than its target. That
design would be sensitive to closures of roughly 29%, not 10%. The bound
ignores the paired common-random-number design, under which J_G1 and J_G2
may be strongly correlated. This stage replaces the bound with an empirical
paired-difference variance. It does not use the observed mean effect.

**Frozen target (already fixed by B0).** The half-width target is
w* = ½ × 0.10 × 17.37 = **0.8685** J-units. Here 17.37 is the B0 pilot's
pooled `J_G0 − J_REF-S` over C1–C5. The 10% minimum effect is unchanged.

**Sizing procedure (runs after B1 is frozen and the arms are implemented,
and after V0 and SV1–SV4; before any confirmatory run).**
1. **Seeds.** Sizing root **2026100516000**. It is new and disjoint from the
   B0 (…15000–…15999), pilot (…13000) and B1 (…14000) roots and from all
   earlier roots. Sizing deployments are **permanently excluded** from
   confirmatory B1.
2. **Size.** **n_s = 20 deployments per condition**, C1–C5 only (fixed
   before execution).
3. **Arms run:** G1 and G2 only, through the full learning and evaluation
   protocol (§1). μ uses G0's θ0 controller as in §5. No G0, G3, G2-S,
   REF-S or REF-Z evaluation outcome is computed.
4. **Output (blinded).** Per condition c, the sample variance s_c² of the
   per-deployment paired difference d = J_G1 − J_G2, and n_s.
   * The sizing script computes s_c² internally.
   * It writes **only** s_c², n_s and engine metadata to its receipt.
   * It does not compute, store, print or log any per-deployment d, any
     mean, any sign, any per-arm J or any F1–F6 quantity.
   * Per-deployment arm data are held in memory only and discarded.
5. **Variance used.** The per-condition one-sided **upper confidence
   bound** s²_UCL,c = (n_s − 1)·s_c² / χ²_{1−γ, n_s−1}, with γ as decided
   in §14.
6. **Formula.** The pooled Δ12 is the mean over C1–C5 of per-condition
   means, so Var = Σ_c s²_UCL,c / (25·N). Then:

   N_required = ⌈ (1.96 / w*)² · Σ_c s²_UCL,c / 25 ⌉, with
   N = max(N_required, N_min).
7. **Freeze.** N, the confirmatory seed list (root 2026100514000, spawn
   keys (condition, deployment) for deployments 0..N−1, all of C0–C5) and
   its sha256 are committed **before** any confirmatory run.

**Outcomes of the sizing stage (decided now, applied mechanically):**
* **A: N ≤ N_max.** Confirmatory B1 runs at N with the full §7 mapping,
  including "not supported" when the CI excludes 10%.
* **B: N_required > N_max.** B1 is **infeasible for the 10% target at
  N_max.** Before any confirmatory run, the user chooses one of:
  * raise N_max (a recorded amendment);
  * declare B1 exploratory at N_max (no "not supported" or "falsified"
    wording permitted);
  * stop.

  The 10% minimum effect is not raised to make N fit.

**Not computed from the sizing set:** the mean or sign of G1 − G2, any
closure, F1–F6, P0, or anything about G3, G2-S or REF.

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
* G1 vs G0, the internal-history effect alone.
* OPE validity (§5).
* Missing/PENDING counts.
* Interlock activations per arm. These are arm-independent by
  construction, so a difference indicates a bug.
* **C0 learned-noise bias (new in v1.2).** In C0 every sensor's true
  (b, σ) is nominal. Each arm's learned σ̂_i/σ_nom,i and b̂_i in C0 therefore
  directly measures how much its reference variance distorts noise
  learning (T6).

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
* **T5 Matched-rule assumption.** G1 is one specific internal-consistency
  rule, not every possible closed learner.
* **T6 Residual predictor conservatism (new in v1.2).** B0 gate 18 passed,
  but coverage stays above nominal: cov90 0.92–0.93 and cov50 0.53–0.55.
  * This implies some overstatement of predictive variance. If the latent
    part carries it, G2's `σ² = v − s²_ref` is biased low, and G1's static
    reference does not share that bias.
  * The magnitude is not established. A rough Gaussian reading of the
    coverage suggests on the order of 10–20% in σ², under assumptions.
  * B0 and P1–P7 are deliberately not modified. The §9 C0 diagnostic
    measures the bias, and F5 bounds its control cost in C0.
* **T7 Retained predictor mismatches** P1–P7 (B0 v1.3 §0.3). P1 and P4 are
  the candidate sources of T6. They are not investigated in B1.

## 11. Literature

Methods are established and cited only as verified in scoping v1:
* Gneiting & Raftery 2007 (proper scoring rules);
* Dawid & Skene 1979 (agreement-based reliability, the spirit of G1);
* Dudík, Langford & Li 2011 (doubly robust).

**To verify before freeze; not cited until verified.** Innovation-based
adaptive Kalman filtering (Mehra 1970, 1972; Myers & Tapley 1976). G2's
noise update `σ² = v − s²_ref` belongs to this family, so it is prior art
for the estimator, which is therefore not a contribution. Recent leads from
model-assisted search are unverified and are not cited.

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

## 13. Changes from v1.1 (`6ea1628`)

* B0 status updated: CLOSED / PASSED (`06d5d24`).
* §2: the stale "grid Bayes filter" description replaced by the frozen B0
  v1.3 Gaussian moment-closure predictor (`701c4c2` + `ebdb0f1`,
  implementation `94f4f11`), with validity check V0. P1–P7 retained.
* §7a replaces the cap-at-200 sizing rule with a blinded paired-variance
  sizing stage. The 10% minimum effect is unchanged.
* §7 outcome mapping: "¬F1 = falsified" removed. A negative result is "not
  supported" only when powered and the CI excludes 10%; otherwise it is
  "inconclusive".
* T6, T7 and the C0 learned-noise diagnostic added.
* Literature: adaptive-KF prior art flagged for verification.

## 14. Unresolved statistical choices (decide before freeze)

1. **γ, the confidence of the variance upper bound.** Proposed one-sided
   80%. With n_s = 20, χ²_{0.20,19} ≈ 14.44, inflating s² by ≈ 1.32. The
   alternatives are 90% (χ²_{0.10,19} ≈ 11.65, ≈ 1.63×) or the point estimate (1.0×, no
   protection against underestimating).
2. **n_s** (proposed 20 per condition, C1–C5) and whether C0 is included.
   C0 would add information for F5's precision; it is not needed for Δ12.
3. **N_min** (proposed 20) and **N_max.** N_max must be set by compute
   budget and where B1 runs (Appendix). The v1.1 value 200 is retained
   only as a placeholder.
4. **Sizing on Δ12 only, or on max(Δ12, F3's `J_G2-S − J_G2`).** Sizing
   F3 needs G2-S in the sizing run. Proposed: Δ12 only, with F3's projected
   half-width reported from its variance, without a mean.
5. **Normal-approximation sizing vs the bootstrap analysis.** Sizing uses
   1.96 and a normal approximation; the analysis uses a stratified paired
   bootstrap. Proposed: accept the mismatch and report it.
6. **The "not supported" row.** It uses the B1-measured denominator
   (J_G0 − J_REF-S), not the pilot's 17.37. Proposed as written.

## Appendix: structural compute estimate (not a criterion; no arm outcome used)

The estimate is anchored on B0's measured cost: gate 18 ran 4,000
agent-steps in 18.9 s, ≈ 4.7 ms per full agent-step on this machine.

* **One deployment-condition:**
  * learning phase: 1,000 world steps with ≈ 6 arms committing receipts
    and updating (≈ 6,000 agent-step equivalents);
  * evaluation: 7 controllers (G0, G1, G2, G3, G2-S, REF-S, REF-Z) ×
    1,000 steps.
  * Total ≈ 13,000 agent-steps ≈ **60 s** single-core, excluding OPE
    replays and G3's heavier likelihood (an estimated +10–30%).

| Run | Deployment-conditions | Single-core | 8 physical cores (ideal) |
|---|---|---|---|
| Sizing (n_s = 20, C1–C5, G1+G2 only, ≈ 24 s each) | 100 | ≈ 40 min | ≈ 5 min |
| Confirmatory N = 200 (C0–C5) | 1,200 | ≈ 20 h | ≈ 2.5–3.5 h |
| Confirmatory N = 1,659 (C0–C5) | 9,954 | ≈ 7 days | ≈ 21–30 h |

The work box (Ryzen 7 7735U, 8 cores / 16 threads, 15 GB) is a managed
laptop, so multi-day runs belong on the home box or RunPod. Bootstrap
(10,000 resamples) cost is negligible.
