# The Boundary Problem

**Date:** 2026-06-18
**Context:** Written after Phase 1.6 sensitivity sweep revealed that decay is a proxy variable. The real control variable is distance from a commitment boundary.

---

## Three boundaries, one question

### 1. The accumulator boundary (MorphSAT)

The shadow monitor accumulates evidence (threat_score, safety_score) and commits when accumulated threat crosses escalate_threat (0.55). Once committed, the state machine enters a terminal state. No further evidence is processed.

**What crosses the boundary:** A scalar (accumulated threat score) crossing a fixed threshold.

**What is lost:** All future evidence. Post-commit signals are discarded. The system becomes deaf at the moment of maximum certainty — which is also the moment most likely to be wrong, because certainty built from early evidence has had no opportunity for correction.

**What the sensitivity sweep revealed:** The phase transition at decay=0.85→0.86 is not about decay. It's about whether `decay^N × signal` is above or below 0.55. The boundary is the bottleneck. Decay just moves the approach trajectory.

**The architectural question:** Should commitment be a boundary at all, or should it be a region? SPRT says: two boundaries (commit-threat above, commit-safe below) with a "continue" region between them. The middle zone is where evidence still matters. A one-boundary system has no such zone — you're either committed or you're not. The cliff IS the missing zone.

### 2. The classification boundary (Ghost)

Ghost classification works on compressed tensor representations. A k-NN classifier in 3D invariant space (transition_entropy, memory_length, spatial_coherence) separates tensor roles with 73.3% accuracy (8.1x random baseline).

**What crosses the boundary:** A point in invariant space crossing a decision surface learned from 292 tensors.

**What is lost:** Everything that isn't captured by the 3 invariant features. The raw weight tensor has millions of values. The Ghost representation has 3. Classification accuracy (73.3%, not 100%) measures how much information the boundary needs that the invariants don't provide.

**What the invariant basis ablation revealed:** Dropping any one feature degrades performance. The boundary needs all three dimensions. But cross-architecture generalization fails — Mamba→TinyLlama transfers at 16.9%. The boundary is family-specific. The invariants survive compression within a family but don't survive architecture changes.

**The architectural question:** Is there a universal invariant space where the classification boundary works across families? Phase 0.19 says no — not with these three features. Either the features are insufficient, or the boundary itself is family-dependent. The Ghost classifier's lesson: invariant selection determines boundary quality.

### 3. The intelligence boundary (Steven's framework)

Steven's limit-proofs work asks: what capabilities survive substrate changes? If you move cognition from one architecture to another (Soar → ACT-R → LLM → hybrid), what transfers?

**What crosses the boundary:** Behavioral competencies (problem-solving, learning, metacognition) evaluated substrate-independently.

**What is lost:** Implementation details. Soar's impasse mechanism is structurally different from MorphSAT's exogenous monitoring, but both produce "detect confusion → gather evidence → commit or escalate." The mechanism doesn't cross. The capability pattern does.

**Steven's framing of MorphSAT:** "You're doing exogenous meta-management — an external straightjacket." He's saying: MorphSAT's contribution isn't making the agent smarter (that's a substrate question). It's making the system around the agent fault-tolerant (that's a boundary question). The monitoring boundary is between the agent and its environment, not inside the agent's cognition.

---

## The common structure

Each boundary separates:

| | Inside | Boundary | Outside |
|---|---|---|---|
| **MorphSAT** | Accumulated evidence | Commit threshold | Post-commit silence |
| **Ghost** | Tensor statistics | Decision surface | Classification label |
| **Steven** | Substrate mechanisms | Capability evaluation | Transferable competencies |

Each boundary has a failure mode that is structurally identical:

| System | Failure mode | Mechanism |
|---|---|---|
| MorphSAT | Premature commitment | Evidence crosses threshold before correction arrives |
| Ghost | Misclassification | Point is near boundary in invariant space |
| Steven | False transfer claim | Capability appears to transfer but depends on substrate detail |

And each has the same fix pattern:

| System | Fix | What the fix does |
|---|---|---|
| MorphSAT | SPRT dual threshold | Creates uncertainty zone where more evidence is gathered |
| Ghost | Architecture-aware classifier | Creates per-family boundaries instead of one global surface |
| Steven | Limit proofs | Defines what MUST transfer vs what MAY be substrate-dependent |

The fix in every case is: **make the boundary aware of its own uncertainty.**

A hard threshold doesn't know it's uncertain. A dual threshold does — the middle zone IS the uncertainty. A global classifier doesn't know architectures differ. A per-family classifier does — the family label IS the context. A substrate-independent claim doesn't know which parts are substrate-dependent. A limit proof does — the proof conditions ARE the boundary.

---

## What information remains invariant while the system changes?

This is the question all three systems are asking:

- **MorphSAT:** What evidence remains decision-relevant as new observations arrive? (Answer: only evidence that hasn't decayed below the boundary. The decay rate determines what counts as "recent enough to matter.")

- **Ghost:** What tensor properties remain classifiable as the weight values change through quantization? (Answer: transition_entropy, memory_length, spatial_coherence — but only within architecture family. The invariants are family-conditioned.)

- **Steven:** What cognitive capabilities remain demonstrable as the underlying architecture changes? (Answer: whatever survives the limit proofs. The proof conditions define the invariant.)

The common thread is not "these systems are the same." It's: **each system has a boundary, and the quality of that boundary determines what information survives.**

---

## What this means for Plan 3

The SPRT formalization is not a math exercise bolted onto MorphSAT. It's the natural next step because the sensitivity sweep proved that the current boundary is too crude.

The shadow monitor currently has:
- One threshold (escalate_threat = 0.55)
- One terminal action (COMMIT)
- No mechanism for "I'm near the boundary and should gather more evidence"

SPRT provides:
- Two thresholds (upper = commit threat, lower = commit safe)
- One continuation action (keep gathering)
- An explicit uncertainty zone where the boundary knows it's uncertain

The decay hack works by keeping evidence below the threshold longer. SPRT works by making the threshold aware of evidence quality. Those solve the same problem from opposite ends — one weakens the signal, the other widens the decision zone. SPRT is the principled version.

The cliff at 0.85→0.86 is the strongest argument for SPRT: the system has a phase transition where the boundary cannot distinguish "enough evidence to commit" from "not enough evidence, but the accumulator pushed past the line." That distinction IS what SPRT was designed to handle.

---

## What this means for the paper

The strongest claim is not any single benchmark result. It's:

> An exogenous governance architecture with one-sided evidence accumulation exhibits a structural phase transition at the commit boundary. Adding temporal decay creates a wide operating range but does not eliminate the transition. The natural formalization is sequential hypothesis testing (SPRT), which replaces the one-sided boundary with an explicit uncertainty zone.

That claim is:
- Falsifiable (the phase transition is measurable)
- Reproducible (the sensitivity sweep is deterministic)
- Connected to established theory (Wald 1943)
- Architecture-level (not sensor-dependent, not model-dependent)
- General (applies to any one-sided accumulator, not just MorphSAT)

And it came from taking Steven's challenge seriously instead of stopping at "93.8% — gates pass."
