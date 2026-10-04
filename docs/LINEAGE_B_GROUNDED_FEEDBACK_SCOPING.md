# Lineage B — Grounded Causal Feedback: Scoping and Architecture (DRAFT)

Status: **scoping document only.** No implementation, no simulator, no
preregistered outcome experiment. Scope: public GitHub lineage of `14689b7`.
Biology is design inspiration only, never evidence.

## 1. Goal

Define the **minimum simulator** needed to test whether external,
action-conditioned observations can provide an independent empirical
constraint on future lawful routing/arbitration — something internal memory
cannot provide (an external referee).

## 2. Why the current harness cannot do this

* Tool outputs are scripted text; nothing observed after a decision depends on
  the decision. "Outcomes" fed back today would be ground-truth labels, i.e.
  supervised learning from an oracle, not grounding.
* Only taken actions produce outcomes (counterfactuals unobserved), and in
  triage the feedback is asymmetric (escalations get reviewed; wrong benign
  verdicts surface late or never). Learning from that is biased.

## 3. Conceptual loop

```
hidden state Z_t  (evaluation-only)
  → agent observation  X_t = sensors(Z_t)
  → DecisionEvent / action A_t          (existing MorphSAT path, terminal authority intact)
  → frozen prediction Ô_{t+1}           (hashed BEFORE the transition runs)
  → world transition Z_{t+1} = T(Z_t, A_t, noise)
  → sensors O^i_{t+1} (possibly delayed / missing / corrupted / duplicated)
  → PredictionReceipt (Ô vs O, per sensor, with provenance)
  → credibility / state update (pathway- and sensor-level)
  → FUTURE lawful routing/arbitration only
```

## 4. Minimum simulator specification

| Component | Minimum requirement |
|---|---|
| Hidden state `Z_t` | Small discrete state (e.g. host ∈ {clean, compromised} × activity ∈ {idle, active}); never agent-visible; evaluation-only |
| Actions `A_t` | Includes the existing outcomes (COMMIT benign / suspicious / escalate, ABSTAIN) mapped to world actions (e.g. allow, monitor, isolate, defer to human) |
| Transition `T(Z_t, A_t)` | Action changes future state probabilities (e.g. isolate stops spread; allow on compromised host raises later anomaly rates) — consequences must depend on the action |
| Sensors `O^i` | ≥ 4 named sensors, each with identity, reliability `r_i`, and an **upstream dependency graph** (some sensors share an upstream feed) |
| Duplication | Some observations are copies of one upstream reading (shared noise) |
| Corruption | Some sensors are noisy or adversarially biased (unknown to the agent) |
| Delay / censoring | Outcomes can arrive after `d` steps or never; **missing is an explicit state, not success** |
| Episode structure | Multi-step episodes, so actions have downstream consequences and predictions can be scored later |
| Determinism | Seeded; every run reproducible from (seed, config hash) |

## 5. Hard invariants (to be enforced by schema and tests)

1. Evaluation ground truth (`Z_t`, true reliabilities) never enters
   agent-visible state.
2. The decision/action being evaluated cannot write or rewrite its own
   receipt; receipts are written by the simulator/evaluator layer.
3. Learned credibility influences only FUTURE lawful routing/arbitration.
4. Historical canonical DecisionEvents are never altered.
5. COMMIT/ABSTAIN terminal authority remains intact; learning may only
   reweight among lawful routes (e.g. inside DEFER arbitration).
6. Observations sharing an upstream source are not automatically independent
   corroboration.
7. `Ô_{t+1}` is frozen (hashed and recorded) before `O_{t+1}` exists.
8. Missing/censored outcomes are represented explicitly, never as success.
9. The experimental design must address selective-feedback (bandit) bias.

## 6. Receipt schema (proposed)

```
PredictionReceipt
  decision_event_ref     outcome_ref of the canonical DecisionEvent
  pathway                routing/arbitration pathway that produced the decision
  prediction_hash        hash of Ô (committed before transition)
  predicted              Ô: per-sensor predictive distributions
  observed               per sensor: value | MISSING | DELAYED(d)
  sensor_provenance      sensor_id, upstream_id, reliability prior (no true value)
  constraints            safety/task bounds checked
  score                  proper scoring rule per observed sensor (§7)
  written_by             evaluator layer id (never the evaluated pathway)
```

## 7. Candidate evaluation machinery (established, not novel)

* **Proper scoring rules** (log score, Brier score) for frozen probabilistic
  predictions; calibration diagnostics — Gneiting & Raftery (2007), JASA
  102(477), 359–378.
* **Source/sensor reliability without ground truth** — Dawid & Skene (1979),
  JRSS-C 28(1), 20–28 (EM over observer error rates); a natural baseline for
  sensor credibility.
* **Off-policy evaluation under selective feedback** — logged action
  propensities with inverse-propensity or doubly robust estimators: Dudík,
  Langford & Li (2011), *Doubly Robust Policy Evaluation and Learning*, ICML.

MorphSAT's plausible contribution is not new learning theory; it is
(a) pre-action prediction receipts, (b) independence accounting over a sensor
dependency graph, and (c) authority invariants that learning cannot override.

## 8. Candidate update rules for a later preregistration

* U0: no update (control).
* U1: outcome reward ±1 per pathway (expected to be vulnerable to reward
  hacking and selective feedback; included as a foil).
* U2: proper-score update per pathway, counting all sensors equally.
* U3: proper-score update weighted by sensor independence (deduplicated by
  upstream id) and estimated reliability.

## 9. Selective-feedback options (choose before preregistration)

* Full-information simulator mode (all counterfactual outcomes logged) as an
  upper-bound control.
* Logged randomized exploration with recorded propensities, enabling IPS or
  doubly robust evaluation.
* Explicitly censored mode (realistic): asymmetric observation of outcomes.

## 10. Open design choices

* **B-U1** Domain of the toy world (host-security vs physical valve/tank).
* **B-U2** What a "pathway" is in MorphSAT terms (threshold vs QUBO backend,
  arbitration baselines, or new arbitration candidates).
* **B-U3** Prediction format (per-sensor categorical distributions proposed).
* **B-U4** Delay/censoring distributions.
* **B-U5** Which selective-feedback mode is primary.
* **B-U6** Whether the adversary can corrupt sensors adaptively.
* **B-U7** Scale (steps, episodes, seeds) — to be set by a power argument in
  the eventual preregistration.

## 11. Related work (verification level stated)

Verified via search (bibliographic details): Gneiting & Raftery 2007;
Dawid & Skene 1979; Dudík, Langford & Li 2011. 2026 agent-memory provenance
preprints (arXiv:2606.24322, arXiv:2607.29167, arXiv:2606.04990) were located
via search index only; full text not accessed (arXiv blocked by this
environment's egress proxy); not relied upon.

---

## Appendix — Overlap and dependency map (Lineage A → Lineage B)

| Lineage A artifact | Reuse in Lineage B | Dependency |
|---|---|---|
| `ObservationRecord.source_id` / `upstream_id` | Sensor identity and upstream feed in `PredictionReceipt.sensor_provenance` | **B depends on A's schema review** |
| Repeat-correlation model (`ρ`: copies vs re-measurements) | Duplicated-sensor semantics in the simulator | Reuse directly |
| Independence counting (distinct upstream ids, excluding the claimant's own) | Independence weighting in update rule U3 | Reuse; generalize from "same id" to a dependency graph |
| Adversarial-source model (`α`) | Corrupted/adversarial sensors | Reuse; B adds adaptive adversary (B-U6) |
| Exact-posterior evaluator | Reference for sensor-credibility estimates in the toy world | Optional |
| Shams (direction-blind count; upstream shuffle) | Shams for B's independence weighting | Reuse pattern |
| Integrity controls (no-oracle AST checks, hash-before-evaluate) | Same discipline for simulator and receipts | Reuse |
| A's result | If A finds no benefit from independence-aware corroboration, B's U3 hypothesis should be revisited before preregistration | **Gate**: B preregistration waits for A's result |

Sequencing: A preregistration review → A implementation and run → B
preregistration (informed by A's provenance machinery and result) → B
simulator. B's simulator code should not start before A's schema is frozen.
