# Lineage B1 — v1.5.1 PRE-EXECUTION IMPLEMENTATION AMENDMENT

**Status: binding amendment to the B1 preregistration.**
* The sizing-design freeze remains `2473c2a`
  (`docs/LINEAGE_B1_GROUNDED_FEEDBACK_PREREG_V1.md`, preserved
  byte-identical).
* Implementation commit `2206373` exposed details the frozen text did not
  determine. User review of `2206373` found further defects (§1, §2, §6–§9).
* **No validation, sizing or confirmatory seed root had been touched**
  (2026100517000, 2026100516000, 2026100514000). No B1 receipt existed. No
  scientific outcome had been observed.
* This amendment binds those details **after implementation inspection but
  before any seeded execution**.
* Nothing here changes B1's question, arms' roles, primary contrast,
  margins (Δ*, δ_null, δ_cond, δ_safe), endpoints, the sizing formula, the
  χ² constants, N_min/N_max, seed roots or B0.

Where this amendment and `2206373`'s implementation notes differ, this
amendment governs.

## 1. G2-S sham construction (replaces the §3 cyclic shift)

**Defect.** Under the frozen hash-rank cyclic shift, the expected fraction
of mismatched DEFER steps is
`1 − Σ_a n_a(n_a − 1) / [n(n − 1)]`. With four balanced labels this is
`3n / [4(n − 1)] → 0.75`. So for n > 16, even perfectly balanced actions
fall short of the frozen SV3 threshold of 0.80 in expectation. The shift was
structurally misaligned with SV3. **SV3 = 0.80 is kept.**

**Binding rule: a deterministic maximum-mismatch multiset permutation over
the learning-phase DEFER steps of one deployment.**

1. Partition the DEFER positions by logged action, in the frozen order
   `ACTIONS = (open, hold, close, inspect)`.
2. Within each action group, sort positions by
   `sha256("<deployment id>|<g>")`, where g = episode·200 + t is the
   deployment-global step and the deployment id is
   `"<purpose>:<condition>:<deployment>"`.
3. Concatenate the groups in `ACTIONS` order. This gives the positions P and
   their labels L.
4. Let m = the largest action count. Rotate L left by m positions.
5. Assign the rotated labels back to P.
6. At non-DEFER steps (interlock, terminal ABSTAIN), and when n ≤ 1, the
   sham action equals the logged action.

**Invariant (frozen; unit-tested exhaustively on small count vectors).**
* Exact marginal action counts are preserved.
* The number of mismatched positions equals the maximum possible,
  `min(n, 2·(n − n_max))`.

Proof sketch:
* A position outside the largest group gets a label from another block,
  because a block of size k ≤ m shifted by m mod n cannot land on itself
  unless k + m > n. That gives n − m mismatches.
* The largest block overlaps its own image in max(0, 2m − n) positions.
* Total: n − max(0, 2m − n) = min(n, 2(n − m)).
* This is the upper bound, because each largest-group position can only
  mismatch by receiving one of the n − m labels from other groups.

**Consequence.** SV3 ≥ 0.80 is attainable iff the realized action marginal
permits it. Given the construction this is p_max ≤ 0.60, or the pooled
equivalent (§3). If the maximum-mismatch sham still gives < 0.80, the frozen
sizing-stage sham gate fails legitimately, for insufficient action
diversity. It is not tuned or lowered.

## 2. G1 same-time consensus (binds and corrects §3's G1 row)

* **Available records.** For a record of sensor i measured at τ, the
  "other sensors" are every VALUE record the agent has received, including
  the current delivered batch, with `measured_at = τ`, excluding sensor i and
  inspection reports. L4 is an ordinary sensor for G1, which has no
  dependency knowledge.
* **Static mappings to a level estimate (ĥ, var).**
  * level: `(y − b, σ²)`;
  * pressure: `((y − b)/9.81, (σ/9.81)²)`;
  * flow: `ĥ = ((y − b)/(Cv·u_τ))²` with first-order variance
    `(2(y − b)/(Cv·u_τ)²·σ)²`. Flow is omitted when u_τ = 0 or `y − b ≤ 0`.
  * u_τ is the commanded valve position at τ, from the agent's own action
    history.
* **Fusion.** Precision-weighted mean ĥ = Σ(ĥ_j/var_j)/Σ(1/var_j), with
  variance 1/Σ(1/var_j). It is mapped back to sensor i's units: level
  `(ĥ, var)`; pressure `(9.81ĥ, 9.81²var)`; flow
  `(Cv·u_τ·√ĥ, (Cv·u_τ/(2√ĥ))²·var)`.
* **No update** (logged as a skip) when no other sensor is usable.
* **Pre-batch θ snapshot (correction).** Every G1 reference computed for a
  delivered batch uses the (b, σ) values as they stood **before any record
  of that batch updated θ**. Updates are then applied with those
  references.
* **Canonical processing order (all learning arms).** Within a delivered
  batch, records are processed in the order (measured_at, sensor_id, seq).
  This is needed because the same sensor can appear twice in one batch (a
  late plus a fresh record), and two EWMA updates do not commute.
* **Order invariance (frozen; unit-tested).** For G1, permuting an
  otherwise identical delivered batch leaves the references, final θ and θ
  hash identical. The same holds for G2 and G3.

## 3. Sham validity aggregation (binds §3 SV1–SV4)

Computed from logs and predictions only (§6 barrier):
* **SV1:** exact marginal action frequencies are preserved in **every**
  deployment.
* **SV2:** the pairing changed (≥ 1 mismatch) in **every** deployment.
* **SV3:** the pooled fraction of DEFER steps whose sham differs from the
  logged action, over the whole set, is ≥ 0.80. The per-deployment minimum
  is reported.
* **SV4:** the mean of KL(genuine ‖ sham) over (step, sensor) pairs is
  ≥ 0.05 nats. Sensors: L3 and F, the ones gate 13 tested. Steps: DEFER
  steps whose sham action differs from the logged action. Both predictions
  come from G2-S's own receipt.

## 4. Two-pass learning phase

> The stochastic behavior log is generated once. Pass 2 is a deterministic
> replay of that already-fixed log for learner receipt/update computation
> and must reproduce the logged world/stream exactly. It is not a second
> stochastic sample.

* Pass 1: G0's controller at θ0, with the logging policy μ.
* Pass 2: all learning arms, in lockstep. Each commits its receipt for
  t + 1 before the shared transition, enforced by a barrier that requires
  every arm's commitment.
* Divergence from the log aborts the run.

## 5. Learning-phase event provenance

Only the logging policy executes an action during learning. No separate
"executed" decisions are fabricated for G1/G2/G3/G2-S.
* **Behavior event.** One immutable `ControlDecisionEvent` per step with
  arm label **`G0-logging`**, recording the actually executed action and its
  propensity.
* **BehaviorDecisionRecord (B1-side, immutable).** One per step. It carries
  `controller_proposal` (G0's own proposal at θ0) and `logged_action` (μ's
  randomized choice) as separate fields, together with the propensity, a
  randomized flag, the authority path, the final action and the canonical
  hash of the behavior event.
* **Learner side.** Each learner's own immutable pre-action
  PredictionReceipt. Each learner FeedbackRecord's `decision_ref` links to
  the shared behavior event.

B0 history and B0 event types are not modified.

## 6. Sham validity before control outcomes (execution barrier)

Sizing and confirmatory executions run in two stages:
* **Stage A** covers learning and logging only: G2-S genuine and sham
  predictions, and SV1–SV4 inputs. No evaluation, no control outcome, no
  cost or safety quantity, no OPE outcome.
* **Pooled SV** is then decided and receipted.
* **Sizing:** if SV fails, a failure receipt is written and execution
  stops. No evaluation outcome is ever generated for that set.
* **Stage B** (only after SV is decided) runs the frozen-θ evaluation and
  the allowed analysis.
  * Sizing evaluates the learned models carried over from stage A.
  * Confirmatory stage B deterministically re-runs the learning phase from
    the same seeds to obtain the OPE log and world snapshots. It must
    reproduce every stage-A θ hash exactly, or the run aborts. This replay
    is disclosed here.
* **Confirmatory SV failure.** Per frozen §3, F3 is then reported invalid
  and the confirmatory analysis continues. The stage-A SV receipt is
  written before any evaluation outcome exists.

## 7. One-shot start receipts

* **Sizing.** Before the first sizing seed is opened, a
  `b1_sizing_STARTED` receipt is written. It records:
  * the prereg and amendment references;
  * the per-file protected-source hashes;
  * the root, n_s, a timestamp and the status.

  The existence of **any** `b1_sizing_*` receipt (STARTED, STOPPED,
  CRASHED, COMPLETED) blocks a fresh sizing invocation. If execution crashes
  after STARTED, the attempt is preserved (a CRASHED receipt with the
  exception, where catchable; otherwise the STARTED receipt alone). Any
  recovery needs an explicit, disclosed amendment.
* **Confirmatory.** The same rule applies to `b1_confirmatory_*`
  receipts.

## 8. Post-sizing code freeze

* The sizing receipt records the per-file sha256 of every protected
  executable source:
  * `lineage_b/**/*.py`;
  * `tools/run_lineage_b1_*.py`;
  * `morphsat/terminal_authority.py`.
* At confirmatory start-up, every protected file is compared with the
  sizing receipt.
  * The file set must be identical.
  * Every hash must be equal, **except `lineage_b/b1_frozen.py`**.
* `b1_frozen.py` is verified independently. It must contain only a
  docstring and exactly three assignments:
  * `N`, equal to the sizing receipt's N;
  * `CONFIRMATORY_SEED_LIST_SHA256`, equal to
    `seed_list_sha256("confirmatory", N)`;
  * `SIZING_RECEIPT`, the receipt's path, whose file hash is recorded.
* Any other difference is rejected. The confirmatory receipt records the
  frozen prereg and amendment references.

## 9. Outcome-mapping precedence (binds §7's table)

Checked in this order:
1. ¬P0 → uninformative; stop.
2. ¬F1 → "not supported" if the CI upper bound of Δ12 < Δ*, otherwise
   inconclusive.
3. Any of F4, F5, F6 fails → no positive claim; report harm or
   condition-level non-inferiority failure.
4. F3 invalid (SV failed) → no ceiling claim; report F1/F2 with the sham
   invalid.
5. F2 passes and F3 fails → "observation-based learning helped;
   action-conditioned grounding not isolated".
6. P0 ∧ F1–F6 all pass → claim at the §0 ceiling.
7. Otherwise (F1 holds, F2 fails) → no ceiling claim; report.

## 10. Other implementation details bound here

* **G3** ("as G2, plus"):
  * Group = sensors sharing a non-relay `declared_upstream` with ≥ 2
    members (ADC_A: L1, L2).
  * Effective bias = b_g + d_i: b_g ← b_g + η_b(r̄ − b_g),
    d_i ← d_i + η_b((r_i − r̄) − d_i). With both members present this
    equals G2's per-sensor bias rule.
  * Shared variance: c ← (1 − η_σ)c + η_σ·e₁e₂, τ² = max(0, c − s²_ref),
    where e_i = r_i − (b_g + d_i) and c is initialized to s²_ref.
  * Individual variance: v_i ← (1 − η_σ)v_i + η_σ·e_i², with
    σ_i² = max(σ²_min,i, v_i − s²_ref − τ²) and v_i initialized to
    σ²_nom,i + s²_ref.
  * Initial τ² = 0, so G3 starts identical to G2.
  * A (group, step) slot updates once all members are present, or once it
    is older than D_MAX, or at the next episode's start, before any
    decision.
  * Relay copies (`relay:X`) are dropped when X is present for that step,
    and used as X otherwise.
  * Joint likelihood via the frozen `predictor.assimilate(joint_l12=R)`,
    with R = [[τ²+σ₁², τ²], [τ², τ²+σ₂²]].
  * G3 stays diagnostic only.
* **REF-Z.** Evaluator-only. It takes the myopic action minimizing expected
  one-step cost on the true Z_t over the process noise (20-point
  Gauss–Hermite), tie order hold, open, close, inspect. It runs through the
  same frozen authority layer as the arms.
* **One-step cost** (REF-Z objective and OPE reward = −cost):
  `c_U·1[h_{t+1}∈U] + c_D(h_{t+1} − h*)² + c_I·1[inspect] + c_M·1[Δu ≠ 0] + c_L·q_leak·dt + c_S·spill·dt`.
* **Action error, coverage, selective risk.**
  * Evaluated on each arm's own evaluation DEFER steps.
  * Action error = the arm's final action ≠ REF-Z's myopic action at that
    arm's Z_t.
  * Coverage = the share of DEFER steps resolved to open/hold/close.
  * Selective risk = action error among the covered steps.
* **Bootstrap.**
  * Frozen seed: `SeedSequence(entropy = 2026100514000, spawn_key = (6, 0))`.
  * One (10,000 × n_c) index draw per condition, in order C0..C5.
  * The same draws are reused for every quantity.
* **OPE.**
  * Features: posterior mean and variance of h, P(ℓ ≠ none), u, and fresh
    flags for L1, L2, L3, F, P (from the behavior event).
  * Per-action ridge with intercept, λ = 1.0, on raw features.
  * 2 folds by deployment-index parity within each condition; IPS, DM and
    DR.
  * Truth = the exact CRN counterfactual one-step reward from a world
    snapshot.
  * Per-deployment DR CI by normal approximation.
* **Evaluation agents.**
  * G0 and REF-S: the frozen `core.Agent`.
  * Learners: `B1Agent` with no updater and a deep-copied learned model; θ
    is asserted unchanged.
  * Confirmatory per-deployment records are stored outside the repository.
* **Removed diagnostic.** §9's "time to detection after t_f" is
  **removed**. No detection rule was frozen, and none is invented after
  implementation. θ trajectories are still reported, as end-of-episode θ
  hashes and final θ values.
