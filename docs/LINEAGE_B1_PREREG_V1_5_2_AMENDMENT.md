# Lineage B1 — v1.5.2 PRE-VALIDATION IMPLEMENTATION-VALIDATION AMENDMENT

**Status: binding amendment.** Preserved unchanged:
* sizing-design freeze `2473c2a`;
* first implementation `2206373`;
* v1.5.1 amendment `f4f5990`;
* corrective implementation `ac7ecf7`.

**No validation, sizing or confirmatory root has been touched**
(2026100517000, 2026100516000, 2026100514000), and no B1 receipt exists.

This amendment makes only the validation and run-integrity corrections
below. It changes no hypothesis, arm, margin, endpoint, sham criterion,
sizing formula, analysis rule or B0 artifact.

## 1. Behavior-provenance validation (extends adapted §7b gate 12)

v1.5.1 §5 made the learning-phase provenance binding. Gate 12 now verifies
it independently, on the validation logs it already generates.

**For every learning-phase step:**
* the behavior `ControlDecisionEvent.arm` is `G0-logging`;
* exactly one `BehaviorDecisionRecord` exists for (deployment, episode, t);
* the record's `behavior_arm` is `G0-logging`;
* the record's (episode, t) equals the event's;
* the record's `behavior_event_hash` equals the event's canonical hash;
* the record's own canonical hash verifies;
* the record's propensity, randomized flag, authority path and final action
  each equal the event's;
* on arbitration steps, `logged_action` equals both the event's final action
  and its proposal;
* on non-arbitration steps, the propensity is 1, not randomized;
* `controller_proposal` differs from `logged_action` exactly when μ
  randomized away from the proposal (propensity ε/3), and equals it
  otherwise (propensity 1 − ε on arbitration steps).

**For every learner FeedbackRecord produced in pass 2:**
* its `decision_ref` equals the canonical hash of the shared `G0-logging`
  behavior event identified by its receipt's `decision_key`;
* that event exists;
* the learning-phase event set contains only `G0-logging` events, one per
  step, so no learner-specific behavior event exists.

**`behavior_records()` itself now rejects** any event/call disagreement in
arm, (episode, t) ordering, propensity, randomized flag, proposal, or
authority/final-action semantics. Previously it checked only the list length
and the arbitration action. Synthetic tests cover malformed and misaligned
inputs.

**The validation receipt records** the prereg references `2473c2a` and
`f4f5990` and this amendment's commit.

## 2. Final G3 group flush before θ is frozen

v1.5.1 §10 closes a pending G3 (group, step) slot at the next episode
boundary. After the **last** learning episode there is no next boundary
before stage A freezes the model.

Every learner therefore receives one explicit end-of-learning finalization
after pass 2, before its final θ is recorded:
* For G3, every remaining slot is closed with the same frozen group-update
  rule. It runs once and is logged as an end-of-learning boundary flush.
* A second finalization is rejected.
* No pending group state survives stage A.
* For G1, G2 and G2-S, finalization changes nothing.

This applies the same boundary semantics already frozen. It is not an
additional learning opportunity, and it happens before any evaluation
decision.

## 3. Confirmatory record-directory integrity

* Before `b1_confirmatory_STARTED` is written, `--outdir` must either not
  exist or be completely empty.
* After stage A, the directory must hold exactly the 6·N files
  `A_<condition>_<deployment>.pkl`.
* After stage B, it must additionally hold exactly the 6·N files
  `B_<condition>_<deployment>.pkl`, and nothing else.
* Rejected: missing files, extra or unrelated files, duplicate logical
  (condition, deployment) records, and records whose embedded condition or
  deployment does not match their file name.
* `build_table()` runs only after these checks pass.
