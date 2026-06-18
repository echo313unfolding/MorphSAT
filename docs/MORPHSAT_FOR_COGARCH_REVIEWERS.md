# MorphSAT for Cognitive Architecture Reviewers

**Audience:** Researchers familiar with Soar, ACT-R, active inference, or sequential decision theory.
**Vocabulary:** See [`VOCABULARY_COGARCH_MAPPING.md`](VOCABULARY_COGARCH_MAPPING.md) for term-by-term translation.

---

## What this is

MorphSAT is an **exogenous metacognitive control architecture** for LLM-based agents. It wraps an LLM's tool-use loop in a structured state machine that accumulates evidence, tracks posture (control mode), and holds decision authority. The LLM proposes actions; the architecture decides when to commit, abstain, or escalate.

The key architectural distinction from Soar-style metacognition: MorphSAT's monitor is **outside** the model. The LLM never sees the governor's state. It cannot reason about its own posture, game the threshold, or override the commit boundary. In Soar terms, the impasse mechanism is replaced by an external straightjacket — the agent is not self-aware of its control mode.

Steven Jones (Laird/Soar group) identified this as the core contribution: *"MorphSAT isn't trying to make the LLM smarter; it's making the system around the LLM fault-tolerant."*

## The research question

**When should an agent stop gathering evidence and commit to an action?**

This is the evidence-accumulation / optimal-stopping problem applied to LLM tool-use loops. The agent can call tools indefinitely (over-investigation) or commit prematurely (under-investigation). MorphSAT provides structured boundaries for this decision.

## Architecture overview

```
Constraint compliance (FSA)
    ↓
Appraisal subsystem (bidirectional evidence classification)
    ↓
Metacognitive control layer (hidden posture state machine)
    ↓
Decision authority layer (structured override / assist)
    ↓
Independent verification (dual-agent recomputation gate)
    ↓
Experience-modulated familiarity (dual-store memory)
    ↓
Episodic audit records (receipts)
```

The metacognitive control layer implements a posture state machine with states mapping to the defensive cascade (Kozak et al., PMC4495877): baseline → orienting → cautious engagement → investigation → commitment. Novelty triggers a **protective orienting response** (bounded investigation), not a threshold penalty. This distinction — posture vs. penalty — is the v6→v7 finding: novelty-as-penalty failed; novelty-as-orienting-state succeeded, improving benign recovery from 35.7% to 78.6%.

## What is proven

| Claim | Evidence | Scope |
|---|---|---|
| Architecture improves accuracy over model alone | 85% (model) → 100% (architecture), N=20, Qwen-7B | One task domain, small N |
| Exogenous control is separable from sensor quality | Same keyword sensor, different architecture → different results (v8.3 vs v9) | Adversarial benchmark |
| Leaky integration recovers from delayed correction | 50% → 93.8-100% (operating range [0.50, 0.85]) | 8 adversarial scenarios |
| Phase transition at commit boundary is structural | 31.3pp cliff at decay=0.85→0.86, explained by `decay^N × signal vs threshold` | Sensitivity sweep |
| Dual-boundary commitment smooths phase transition | Cliff reduced from 31.3pp to 12.5pp, operating range widened 64% | Comparison sweep |
| Dual-agent recomputation catches overconfident errors | 100% disagreement precision, 20-30% disagreement rate | 10 adversarial scenarios |

## Connection to sequential analysis

The single-threshold commit boundary exhibits a phase transition: the system has one threshold (commit when accumulated threat exceeds 0.55) and no mechanism for "I'm near the boundary and should gather more evidence." This is structurally identical to the problem Wald's SPRT (1943) was designed to solve.

The dual-boundary mode adds an explicit uncertainty region between two thresholds:
- **Upper boundary** (commit threat): accumulated evidence strongly favors threat
- **Lower boundary** (commit safe): accumulated evidence strongly favors safe
- **Continue zone**: between boundaries, gather more evidence

Budget exhaustion inside the continue zone produces ABSTAIN (recognized ambiguity), not an invented verdict. This is the key design requirement: the architecture preserves uncertainty rather than manufacturing confidence.

Result: the 31.3pp cliff at the commit boundary drops to 12.5pp with dual-boundary mode. The operating range widens from [0.75, 0.85] to [0.82, 0.99]. The shape changes from plateau (flat then cliff) to gradual slope (smooth degradation).

## What is NOT claimed

- **Not a complete cognitive architecture.** MorphSAT is a metacognitive control layer, not a full agent architecture. It does not handle planning, learning, or perception — only the evidence-accumulation-to-commitment pathway.
- **Not model-independent.** The benchmark uses Qwen2.5-Coder-7B on security triage. Transfer to other models/domains is untested (Plan 2).
- **Not a replacement for better classifiers.** The keyword-based evidence classifier is brittle. The claim is that the architecture's contribution is separable from the sensor, not that the sensor is good.
- **Not a formal SPRT implementation.** The dual-boundary mode is inspired by sequential testing but does not compute likelihood ratios or satisfy Wald's optimality conditions.

## Relationship to existing work

| System | Shared structure | Key difference |
|---|---|---|
| Soar metacognition | Impasse detection → bounded deliberation → resolution | Soar: internal (agent reasons about itself). MorphSAT: external (monitor controls the loop). |
| ACT-R conflict resolution | Evidence accumulation → threshold → action selection | ACT-R: utility-based. MorphSAT: posture-based (state determines what's allowed). |
| Active inference | Surprise → evidence gathering → belief update → action | Active inference: generative model. MorphSAT: no world model, only evidence accumulation. |
| SPRT (Wald 1943) | Sequential evidence → upper/lower boundary → decision | SPRT: optimal for fixed hypotheses. MorphSAT: heuristic boundaries, open-ended evidence. |
| Defensive cascade (Kozak 2015) | Arousal → orient → active defense → commitment | Biological analogy for posture transitions. |

## How to read the code

- `morphsat/shadow_monitor.py` — the metacognitive control layer (posture state machine, evidence accumulation, dual-boundary logic)
- `morphsat/commit_gate.py` — the appraisal subsystem (keyword classifier, coincidence detection, memory)
- `morphsat/recomp_gate.py` — the dual-agent verification layer
- `morphsat/core.py` — the FSA constraint compliance layer
- `tools/bench_adversarial_robustness.py` — adversarial benchmark (noise, contradiction, keyword attack, delayed correction)
- `tools/bench_decay_sensitivity.py` — decay parameter sweep (response surface, cliff detection, dual-boundary comparison)

## References

- Wald, A. (1943). Sequential tests of statistical hypotheses. *Annals of Mathematical Statistics.*
- Wray, Jones, Laird (2023). Constraint compliance. arXiv:2303.04352.
- Jones, Laird (2019). Anticipatory thinking with event cognition. CEUR-WS.
- Kozak et al. (2015). Fear and the defense cascade. PMC4495877.
- Laird (2012). *The Soar Cognitive Architecture.* MIT Press.
- Parr, Friston (2017). Active inference and learning. *Neuroscience & Biobehavioral Reviews.*
