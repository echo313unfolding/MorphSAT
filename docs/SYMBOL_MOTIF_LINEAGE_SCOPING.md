# Expanded-Symbol / Causal-Motif Lineage — Scoping Note (SCOPING ONLY)

Status: **scoping note only.** This is not a preregistration, an
implementation, an experiment runner or an active lineage. Nothing here is
frozen. B1 remains the active work. Scope: public GitHub lineage of
`14689b7`.

Current sequence (unchanged by this note):

```
B0 PASSED → B1 sizing/design → B2 evidence-path reliability → symbol/motif lineage
```

B0 record:
* prereg v1.3 `701c4c2` and T6 amendment v1.3.1 `ebdb0f1`;
* implementation `94f4f11` and its implementation-only receipt `944db55`;
* results `06d5d24`: all 19 validity gates pass under the unchanged gate-18
  criterion.

This note does not reopen B0.

## 1. Idea in one paragraph

Immutable receipts form typed causal graphs. Recurring subgraphs are
abstracted, canonicalized and content-hashed. A validated motif may receive
a compact symbol, a handle the agent can reason with instead of reloading
the underlying receipts. The symbol stays expandable to its evidence and
versioned, and it may be executable: MATCH, PREDICT, confidence, EXPAND,
ABSTAIN. The scientific question is how much evidential or causal structure
can be compressed before behaviourally important information, calibration
or safe abstention degrades.

## 2. Invariants (carried into any future preregistration)

1. **Hash identity is not meaning or truth.** A hash establishes identity
   and integrity only. Lineage A: provenance shows where an interpretation
   came from, not that it is true.
2. **Two kinds of compression, tested separately.**
   * *Reference compression* is an exact pointer to an immutable graph.
     Nothing is lost.
   * *Semantic compression* is a lossy abstraction across multiple
     histories. Information is deliberately discarded to extract an
     invariant.
3. **Evidence substrate is immutable.** Receipts are never rewritten.
   Symbols and interpretations sit *above* the evidence. They are versioned
   and supersedable (`⟦X:v1⟧ → superseded by ⟦X:v2⟧`), and both versions
   stay traceable.
4. **Independent-origin support.** Support is counted by independent
   origin or deployment, never by raw receipt count. One origin may not gain
   weight by appearing in several receipts, several motifs or several
   hierarchy levels (Lineage A alias inflation).
5. **Disjoint discovery and validation.** Motifs are mined on one set of
   deployments and validated on a disjoint set. A motif mined and validated
   on the same data establishes nothing (A4V B-corr lesson).
6. **Terminology.**
   * Recurring observational structure without intervention support is a
     **predictive motif**.
   * **Causal** language requires intervention/action data and the
     necessary causal assumptions, e.g. B1's randomized logging policy with
     recorded propensities.
7. **Abstraction before hashing.** Motif identity requires an explicit
   abstraction and canonicalization layer, consisting of:
   * typing;
   * discretization;
   * temporal tolerance;
   * ignored fields;
   * edge semantics;
   * graph canonicalization.

   This layer is the learned, lossy operation and is the object under test.
   Hashing afterwards is bookkeeping. Exact-isomorphism hashing of raw
   operational graphs is expected to match almost nothing.
8. **An executable symbol is a model.** At minimum it exposes:
   * `MATCH` (context of validity);
   * `PREDICT`;
   * confidence/uncertainty;
   * `EVIDENCE_ROOT`;
   * `EXPAND`;
   * `ABSTAIN` / request expansion when applicability is marginal or
     contradicted.

   Any `RECOMMEND` output is only a proposal and goes through the existing
   authority layer (`morphsat.terminal_authority`). **Symbols never obtain
   terminal authority**: the P2 lesson against post-hoc override paths.
9. **Composition.**
   * Higher-level symbols retain ancestry to their component evidence.
   * Confidences are not multiplied or otherwise combined as if components
     were independent, unless independence is established.
   * Shared evidence ancestry between components must be detectable.

## 3. Candidate falsification design (for a future preregistration)

**Arms:**

| Arm | Representation available to the agent |
|---|---|
| A | full evidence graph (upper reference) |
| B | expanded-symbol representation |
| C | ordinary text summary with B's token budget |
| D | sham-grouped symbols: same compression ratio, causally wrong grouping. This sham must pass a structural validity check before outcomes (it must actually destroy the grouping; A4V sham lesson) |
| E | no memory (lower bound) |

**Strata, evaluated separately:**
* ordinary cases;
* cases where memory changes the full-graph decision versus E;
* contradictions;
* edge cases;
* novel symbol compositions;
* out-of-scope cases, where the correct behaviour is to abstain or expand.

**Measures:**
* agreement with A;
* correctness against evaluator ground truth (agreeing with a wrong A is
  not success);
* selective risk;
* abstention/expansion precision and recall;
* compression ratio;
* provenance recovery (whether EXPAND reaches the correct receipts);
* independent-support count;
* calibration of symbol predictions.

**Key falsifiers (proposed):**
* B does not beat C on ground-truth correctness: symbols add nothing over
  ordinary summarization.
* B does not beat D: the grouping carries no information.

## 4. Compression frontier

The question is not only `decision(symbol) ≈ decision(full graph)`. That is
trivially satisfied if the "symbol" quietly carries almost as much
information as the graph. Define

```
CR = size(full evidence representation) / size(symbol representation)
```

* Size is measured in tokens under a fixed tokenizer and in bytes under a
  fixed canonical serialization.
* Everything placed in the agent's context counts toward the symbol's
  size: the name, parameters, MATCH conditions and any interface outputs.
* Expansion is not free. Material retrieved through `EXPAND` is counted as
  expansion cost per decision. Otherwise a symbol that always expands
  preserves performance trivially.

Report, as semantic compression increases, a **frontier** of compression
against decision fidelity (agreement with A), ground-truth correctness,
calibration and safe-abstention behaviour. The scientific result is where
behaviourally important information, calibration or safe abstention starts
to degrade. It is a curve, not a single verdict.

## 5. Dependencies and sequence

* **B1:** does action-conditioned temporal feedback beat same-time
  observational consistency? If not, motifs built on its records would be
  compressing noise.
* **B2:** held-out reliability of evidence-path types. This is the first,
  narrow form of semantic compression, where "path type" is the motif.
* **Symbol lineage:** compress only path types and FeedbackRecord
  structures that **survived held-out validation** in B2. The symbol system
  is not asked to discover meaning from raw chronology.

## 6. Literature-adjacent areas (scan before any novelty claim)

* case-based reasoning;
* chunking in cognitive architectures;
* hierarchical-RL options and macro-actions;
* program/library learning;
* graph canonical labeling and graph compression;
* provenance-aware knowledge graphs;
* episodic abstraction and schema learning.

No specific works are cited here; none have been verified. Run the
established two-scan protocol (scholarly + artifact scan,
`docs/ADJACENT_WORK_PROTOCOL.md`) before any novelty claim.

## 7. Analogy disclaimer

The biological, DNA and organic-chemistry analogies (receipt = atom, typed
edge = bond, motif = functional group, symbol = group name) are
**architectural heuristics only**. They are not evidence of biological or
chemical equivalence and carry no evidential weight.

## 8. Explicitly out of scope now

* No preregistration.
* No implementation of symbol, motif, canonicalization or compression
  machinery.
* No runner.
* No modification of B0.
* No execution of B1.
