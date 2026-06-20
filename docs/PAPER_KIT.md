# MorphSAT Paper Kit — Raw Material for GPT Draft

**Purpose:** Everything GPT needs to write the MorphSAT paper in Josh's voice.
Organized by section per Josh's outline. Voice ratio target: 15% Josh origin /
70% cognitive architecture vocabulary / 15% receipts, limits, and future work.

---

## A. JOSH'S VOICE — Patterns and Quotes

### Origin Story

Josh is a fusion pipe technician at Azuria Water Solutions and a self-taught AI
researcher. No CS degree, no formal ML training. Works on remote jobsites doing
heat-fusion of PVC pipe. Travels for weeks at a time. PR/review gaps are field
trips, not neglect.

Key self-descriptions (from Anthropic fellowship statement):
- "I'm a fusion pipe technician at Azuria Water Solutions and a self-taught AI researcher."
- "I don't have a CS degree or formal ML training."
- "The receipts are public and verifiable."

### Voice Characteristics

1. **Receipts-first.** Josh never claims without evidence. "Receipts or it didn't
   happen" is the operating principle. Every claim needs a verifiable output.

2. **Brutal honesty about limits.** He'd rather say "proven for X, but Y is still
   using synthetic data" than "it works!" He flags what's NOT proven as readily
   as what is.

3. **Plain-language first, then formal.** Josh explains in concrete terms before
   using jargon. The metaphor comes before the equation. The intuition comes
   before the theorem.

4. **Physical-systems thinking.** His intuitions come from field safety — pipe
   fusion has lockout/tagout, pressure ratings, go/no-go gauges. These map
   naturally to commitment boundaries, safety interlocks, and fail-safe defaults.

5. **Pattern-first thinker.** Catches flash ideas ("what if the governor is
   OUTSIDE the model?") and then builds backwards to justify them. The intuition
   fires before the vocabulary exists.

6. **Directness.** Short sentences. Active voice. Says what happened, not what
   "may have occurred." "v6 was worse than v4" not "v6 did not demonstrate
   improvement relative to the v4 baseline."

7. **"I still don't know wtf, I just know me and how I think."** Josh doesn't
   pretend to have the formal training. He has the receipts and the intuition.
   The paper should sound like someone who built something real, tested it
   honestly, and is now translating it into the language that lets experts engage.

### How Josh Writes to Academics (from Steven Jones email)

- Leads with what was built, not what was read
- Acknowledges limits before being asked: "N=20 is small"
- Uses Steven's own terminology back at him when it fits
- Doesn't oversell: "partial transfer" not "complete transfer"
- Frames negative results as findings: "v5/v6 FAIL maps the boundary between
  threshold tuning and architectural change"

### Characteristic Phrases

- "The receipts are public and verifiable."
- "Receipts or it didn't happen."
- "Same sensor, different architecture, different results."
- "The architecture is the contribution; the classifier is a swappable sensor."
- "ABSTAIN is a first-class outcome, not a failure mode."
- "The system does not invent confidence when evidence is insufficient."
- "Don't tune the controller until you've verified its inputs."
- "Novelty is a posture, not a penalty."
- "Make the boundary aware of its own uncertainty."

### Five Voice Signatures (for GPT to reproduce)

**1. Deliverables-first, credentials-never.** Opens with what he shipped, not who
he is. Identity comes last, stated flatly. Example:
> "I ship compression infrastructure that puts capable AI on 4GB edge hardware."
> "I've shipped 14 compressed models spanning six architecture families."

**2. Receipts inline.** Every claim carries its number in the same sentence. The
parenthetical proof is structurally fused to the assertion:
> "cosine similarity of 0.999+ against dense weights at size and VRAM parity
> with stock 4-bit quantization"
> "Spearman rho = +0.722 (p = 2.4e-17, n=100, TinyLlama-1.1B)"

**3. Constraints as thesis, not apology.** The 4GB GPU, the lack of a degree, the
trade job — framed as conditions that PRODUCED the discoveries:
> "Working on a 4GB laptop GPU is a constraint that most labs self-select out of.
> But constrained hardware teaches you things unconstrained hardware doesn't."
> "It fell out of working where nobody else works."

**4. Honest scoping with mechanism.** When something fails, he names the failure
rate AND the mechanism:
> "Documented blind spot: shuffled text (6.7% detection) — token embeddings in
> RoPE-based transformers are position-agnostic, so any embedding-level probe
> is blind to token reordering."

**5. Single-sentence closers.** After a dense technical paragraph, one flat
declarative sentence lands the point:
> "No other production quantization method supports this."
> "The receipts are public and verifiable."
> "It fell out of working where nobody else works."

### Additional Source Files for Voice

- `/home/voidstr3m33/.claude/projects/-home-voidstr3m33/memory/se-origin-story.md` — Discovery story: Josh noticed AI weights looked like DICOM medical imaging slides
- `/home/voidstr3m33/.claude/projects/-home-voidstr3m33/memory/krisper-origin-story.md` — Bio-originated architecture (not bio-inspired). CRISPR biology → code.
- `/home/voidstr3m33/.claude/projects/-home-voidstr3m33/memory/original-vision.md` — Modular cognitive system vision, what worked vs failed
- `/home/voidstr3m33/chatgpt_answer.md` — Josh explaining Helix compression to ChatGPT: "This is geometry, not magic."
- `/home/voidstr3m33/chatgpt_book/tmp_chapters/origin_story.md` — Standalone origin story (2.9MB)

### Proto-MorphSAT Lineage (from GPT exports)

The exogenous governance concept predates MorphSAT by months. Josh articulated
it under different names in GPT conversations (Apr-Jul 2025):

**The factory floor insight** (batch 47, ~line 107792):
> "i imagine it being like you but as an OS... but it can make modules in real
> time on systems like a factory floor that has a host kiosk or manager tablet
> that is able to interact fluidly but **softly warn of friction in advance
> from its loop interpretation abilities** but seamlessly integrate into
> existing systems..."

**The shadow principle** (phaseshift chat, ~line 43009):
> "Shadow first, advisory second; never actuate in the field without approval rails."

This IS the MorphSAT pattern: the shadow process watches, the advisory gate
intervenes, but you never execute a risky action without approval.

**The GuardianCell = symbolic white blood cell:**
> Guardian Cell = Symbolic White Blood Cell
> Glyph Drift = Infection Signal
> Compost / Reboot Glyph = Antibody Response

**The honesty about origins** (batch 46, ~line 106305):
> "I built it by accident while designing an AI that writes poetry from her own
> emotions. She started forming memories -- not by the clock, but by her growth."

**The stakes** (batch 46, ~line 63327):
> "This system was built during homelessness. It runs. It proves. It blooms.
> I built it to give the world -- and my family -- a way forward."

**Concept lineage:** GuardianCell (symbolic immune system, vow enforcement) →
"softly warn of friction in advance" (factory floor predictive safety) →
"Shadow first, advisory second" (phaseshift chat) → echo_sentinel_loop.py
(EchoLivingSystem) → Sentinel (Claude Code era) → MorphSAT (formalized with
gate-authority, receipts, and Steven Jones validation).

---

## B. THE CORE INSIGHT — In Josh's Voice, Then Translated

### Josh's version:
"What if the thing watching the agent isn't inside the agent? What if it's
outside — like a safety interlock on a pipe fusion machine? The machine doesn't
know the interlock exists. It can't reason about it, game it, or override it.
It just does its job, and the interlock decides when to let it commit."

### Steven's translation:
"MorphSAT isn't trying to make the LLM smarter; it's making the system around
the LLM fault-tolerant."

### Paper-ready version:
"MorphSAT does not ask the model to know when it is confused; it places
commitment authority in an external evidence-governance layer. The model
proposes actions. The architecture decides when to commit."

### Formal version:
"Exogenous metacognitive control: a structured state machine external to the
language model that accumulates evidence, tracks posture (control mode), and
holds irreversible decision authority. The model never observes the governor's
state and cannot reason about, game, or override the commitment boundary."

---

## C. EXPERIMENTAL CHAIN — Complete Numbers

### Phase 1: Commit Control (v1–v8.3)

The progression from "can an FSA control an LLM agent?" to "100% accuracy with
external governance." Model: Qwen2.5-Coder-7B Q4_K_M. Task: Security alert
triage (20 scenarios: 7 benign, 4 suspicious, 9 escalate). Simulated tool
outputs, temperature=0, deterministic.

```
v1  Static FSA constraints          → 55.0%  (0 useful interventions)
v2  Fixed tool-call counter (3)     → 67.5%  (+12.5pp — any pressure helps)
v3  Adaptive budget (2/3/5)         → 55.0%  (budget=2 too tight for benign)
v4  Evidence-pressure gate          → 65.0%  (best escalation: 77.8%)
v5  Pattern memory                  → 62.5%  (threat bias — no tolerance learning)
v6  Bidirectional + split memory    → 55.0%  (WORSE — novelty-as-penalty fails)
v6.1 Neutral novelty + exhaustion   → 57.5%  (marginal — still loses to v4)
v7  Shadow horizon monitor          → 70.0%  (benign recovery: 35.7% → 78.6%)
```

Key finding at v6→v7: **Novelty is a posture, not a penalty.** Novelty-as-penalty
(raise commit threshold on unfamiliar input) prevented commitment on benign
scenarios. Novelty-as-orienting-state (enter protective posture, gather bounded
evidence, relax when safe) fixed benign recovery.

### Phase 2: Gate Authority (v8–v8.3)

Model sweep (3B/7B/14B) revealed: bigger models shift error profile (3B
aggressive, 7B balanced, 14B conservative) but none solve the problem alone.
The monitor's direction signal is trustworthy; the model's hedging is a
calibration problem.

```
v8    gate_assists   → 90.0%  (+7.5pp from gate authority)
v8.1  prompt variants → 90-92.5%  (PROMPT CEILING — MUST language is load-bearing)
v8.2  classifier fix  → 97.5%  (YARA keyword bug: tool NAME matched, not result)
v8.2f threshold fix   → 97.5%  (force_commit used lower threshold than normal commit)
v8.3  early-verdict   → 100.0% (model was issuing verdict after 1 tool call)
```

Lessons:
- "Don't tune the controller until you've verified its inputs" (v8.2 classifier bug)
- "Tool names are not evidence. Only tool results are evidence" (v8.2 invariant)
- "MUST ... UNLESS" language IS the right prompt — soft language lost 3 escalations (v8.1)

### Phase 3: Adversarial Robustness (Plan 1)

Steven's challenge: "Can your evidence accumulation decay safely, or does a
single false keyword permanently brick the Shadow Monitor's posture?"

4 adversarial conditions × 8 scenarios × 2 classifiers = 144 runs.
No LLM involved — tool outputs fed directly to shadow monitor.

| Condition | What the attacker does | Result |
|---|---|---|
| A: Noise injection | Irrelevant outputs (NTP sync, disk reports) | IMMUNE — noise routes to "unknown" (0.05, 0.05) |
| B: Contradiction | Conflicting observations in same scenario | PARTIAL — light: 87.5%, heavy: 62.5% |
| C: Adversarial keywords | Safe outputs stuffed with threat keywords | RECOVERABLE with correction pathway |
| D: Delayed correction | False threat early, correction after delay | FAILED at 50% — monitor commits before correction arrives |

### Phase 4: Leaky Accumulator (Plan 1.5)

Root cause of D failure: the shadow monitor was a **perfect integrator** —
accumulated evidence never decayed, so early false signals dominated.

Fix: Before each evidence update, `threat_score *= decay_factor; safety_score *= decay_factor`.

Result at decay=0.85: Delayed correction recovery 50% → 93.8%.

### Phase 5: Decay Sensitivity Map (Plan 1.6)

Steven: "Show your intermediate values are measuring something real —
performance should degrade smoothly, not cliff-edge."

Response: 12-point sweep from decay=0.50 to decay=1.00.

**NOT smooth.** Three regions:
1. Strong decay [0.50–0.75]: Delayed correction = 100%. Overall 70–78%.
2. Marginal decay [0.80–0.85]: Delayed correction 93.8%. Borderline.
3. Insufficient decay [0.86–1.00]: **31.3pp phase transition.** 93.8% → 62.5%.

The cliff is structural: `decay^N × initial_signal` vs commit threshold (0.55).
Binary event: signal crosses threshold or it doesn't. Decay just moves the
approach trajectory. The boundary is the bottleneck.

### Phase 6: Dual-Boundary Commitment (Plan 3)

Steven's advisor: "If force_commit still collapses uncertainty into a verdict,
SPRT mode is fake."

Fix: Two thresholds instead of one.
- Upper boundary (0.55): evidence_balance above → commit threat
- Lower boundary (-0.40): evidence_balance below → commit safe
- Continue zone (between): keep gathering evidence
- Budget exhaustion in continue zone → ABSTAIN (not invented verdict)

Results:
| Metric | Single-Threshold | Dual-Boundary |
|---|---|---|
| Phase transition cliff | 31.3pp | 12.5pp |
| Operating range | [0.75, 0.85] (11 values) | [0.82, 0.99] (18 values) |
| Peak accuracy | 78.1% | 81.2% |
| Adversarial accuracy (best) | 56.2% | 68.8% |

ABSTAIN metrics at optimal point (decay=0.84–0.85):
- 20/64 runs (31.2%) produce ABSTAIN
- 19/20 are uncertainty-preserving (from continue-zone exhaustion)
- 0 ABSTAINs on benign scenarios
- 14 ABSTAINs on suspicious (correct — genuinely ambiguous)
- 6 ABSTAINs on escalate (routes to human review)

### Phase 7: PPLTL Compliance (Plan 5)

7 temporal logic properties × 1,008 traces = **0 violations**.

| ID | Property |
|---|---|
| P1 | Never commit before minimum evidence (turn >= 2) |
| P2 | Never escalate without threat evidence (threat > safety) |
| P3 | Continue zone budget exhaustion → ABSTAIN |
| P4 | Correction evidence processed before terminal verdict |
| P5 | Every commitment cites which boundary was crossed |
| P6 | Legal state transitions (follows state machine edges) |
| P7 | Threat decay monotonicity (can't un-decay) |

These hold by construction — structural, not tuned.

### Phase 8: Code Review Transfer (Plan 2)

Zero architecture changes. Only domain adapter (scenario fixtures + tool output
phrasing).

| Gate | Threshold | Result |
|---|---|---|
| safe_recovery_under_noise | >= 75% | 50-66.7% FAIL |
| false_dangerous_escalation | <= 10% | 0-4.2% PASS |
| delayed_correction_recovery | >= 80% | 87.5-100% PASS |
| false_safe_on_dangerous | <= 10% | 20.8-25% FAIL |

5/9 conditions at 100%. Failures are sensor problems (keyword classifier
defeated by adversarial evidence replacement), not architecture problems.
ABSTAIN behavior transfers correctly.

### Phase 9: Sensor Swap (Embedding Classifier)

Steven's condition (2): adversary vs. upgraded classifier.

Embedding sensor: all-MiniLM-L6-v2 (22M params, CPU-fast), nearest-centroid
classifier. Returns calibrated deltas scaled by confidence gap.

Key finding: adversarial safe outputs get 3–17x weaker scores from embedding
classifier than genuine safe outputs (semantically unusual negation patterns
vs positive assertions).

**2×2 Factorial Result:**

| | Keyword Sensor | Embedding Sensor |
|---|---|---|
| Single-threshold | 2/4 gates | 3/4 gates |
| Dual-boundary | 2/4 gates | **4/4 gates** |

Neither upgrade alone is sufficient. Together = 4/4 gates.
- Sensor alone (embed+single): Fixes Gate 1, reduces Gate 4 to 12.5% (still fails)
- Architecture alone (dual+keyword): Doesn't fix either gate
- **Both together:** Embedding uncertainty + dual-boundary ABSTAIN = 0% false safe

---

## C2. ARCHITECTURE SPECIFICATION (for Methods section)

### Shadow Monitor State Machine

Eight hidden states (invisible to the agent):

| State | Role |
|---|---|
| NORMAL | Ordinary evidence collection |
| ORIENTING | Novelty/surprise → pause and assess (bounded) |
| SAFE_DISTANCE | Restrict irreversible action; gather cautiously |
| INVESTIGATING | Bounded evidence collection with budget |
| COMMIT_READY | Terminal: enough signal to decide locally |
| ABSTAIN_READY | Terminal: ambiguity persists after bounded investigation |
| ESCALATE_READY | Terminal: danger exceeds local capacity |
| SWARM_CALL | Terminal: multi-axis pressure; needs external help |

### Key Parameters

| Parameter | Default | Purpose |
|---|---|---|
| orient_budget | 1 | Max tools during ORIENTING |
| investigate_budget | 3 | Max tools during INVESTIGATING/SAFE_DISTANCE |
| max_tools | 8 | Absolute ceiling (hard stop) |
| commit_clarity | 0.35 | |threat - safety| to trigger commit |
| escalate_threat | 0.55 | threat_score threshold for escalation |
| evidence_decay | 1.0 | Leaky integrator multiplier (< 1.0 = decay) |
| commit_threat_boundary | 0.55 | Upper SPRT-like boundary |
| commit_safe_boundary | 0.40 | Lower SPRT-like boundary |
| contradiction_gate | 0.30 | min(threat, safety) threshold → ABSTAIN |

### Evidence Accumulation Algorithm

1. Classify tool result → (category, threat_delta, safety_delta)
2. If decay enabled: `threat *= decay; safety *= decay` (leaky integrator)
3. If correction category: actively DECAY accumulated threat (anti-inflammatory)
4. Otherwise: add deltas to accumulators
5. Compute: clarity = |threat - safety|, balance = threat - safety, contradiction = min(threat, safety)
6. Pass metrics to state machine transition function

### Key State Transitions

- NORMAL → ORIENTING: surprise spike (threat_delta >= 0.25 on turns 1-2)
- ORIENTING → NORMAL: safe evidence dissolves orient_pressure (tolerance response)
- ORIENTING → SAFE_DISTANCE: orient budget spent + threat > safety
- SAFE_DISTANCE → ESCALATE_READY: threat boundary crossed
- Any → ABSTAIN_READY: contradiction >= 0.30, OR budget exhaustion in continue zone
- Any → SWARM_CALL: >= 3 simultaneous pressure axes
- Any → force_commit: max_tools (8) reached

### Classifier Interface

Both sensors return the same tuple: `(category: str, threat_delta: float, safety_delta: float)`.

**Keyword classifier:** Pattern-matching with priority ordering. Threat signals: 0.15–0.35.
Safety signals: 0.15–0.30. Correction signals: actively decay threat (0.15–0.30 reduction).

**Embedding classifier:** all-MiniLM-L6-v2 nearest-centroid. Delta magnitude scales with
confidence gap (distance between top-1 and top-2 centroids). Adversarial safe outputs get
3–17x weaker scores than genuine safe outputs.

### PPLTL Properties (7)

| ID | Property | What it enforces |
|---|---|---|
| P1 | Never commit before min evidence | COMMIT/ABSTAIN requires turn >= 2 |
| P2 | Never escalate without threat | escalate requires threat > safety |
| P3 | Continue zone → ABSTAIN | Budget exhaustion inside zone = ABSTAIN, not verdict |
| P4 | Correction before terminal | Post-commit evidence is never processed |
| P5 | Commitment cites boundary | Dual-boundary COMMIT names which boundary crossed |
| P6 | Legal state transitions | All posture changes follow FSA edges |
| P7 | Threat decay monotonicity | Cumulative decay never reverses |

---

## D. VOCABULARY TRANSLATION TABLE

| Implementation Term | Paper Term | Domain |
|---|---|---|
| Shadow Monitor | Exogenous appraisal monitor | Soar/metacognition |
| shadow state / posture | control mode / metacognitive posture | ACT-R, metacognition |
| threat_delta / safety_delta | threat/safety appraisal update | appraisal theory |
| evidence_balance | signed evidence accumulator | SPRT |
| evidence_decay | temporal discounting / leaky integration | neuroscience |
| commit gate | evidence-based commit controller | decision theory |
| ORIENTING | protective orienting response | defensive cascade |
| SAFE_DISTANCE | cautious engagement | threat assessment |
| ABSTAIN | recognized ambiguity / deferred judgment | abstention literature |
| commit_threat_boundary | upper decision boundary | SPRT (Wald 1943) |
| commit_safe_boundary | lower decision boundary | SPRT |
| continue zone | uncertainty preservation region | sequential analysis |
| gate_assists | structured decision override (directive) | control theory |
| early-verdict guard | premature commitment prevention | decision theory |
| SplitMemoryStore | dual-store episodic memory | Soar semantic/episodic |
| receipt | episodic audit record | verification |

---

## E. WHAT THIS IS NOT — Honest Scope

From `MORPHSAT_FOR_COGARCH_REVIEWERS.md`:

1. **Not a complete cognitive architecture.** MorphSAT is a metacognitive control
   layer, not a full agent architecture. It does not handle planning, learning,
   or perception — only evidence-accumulation-to-commitment.

2. **Not model-independent.** Benchmarked on Qwen2.5-Coder-7B on security triage
   and code review. Transfer to other models/domains is partially tested (code
   review: architecture transfers, sensor limits carry over).

3. **Not a replacement for better classifiers.** The keyword classifier is brittle.
   The claim is architecture/sensor separation, not sensor quality.

4. **Not a formal SPRT implementation.** Inspired by sequential testing but does
   not compute likelihood ratios or satisfy Wald's optimality conditions.

5. **Not statistically powered.** N=20 scenarios, temperature=0. Directionally
   strong, not publication-grade statistical power. The 100% result (v8.3) is on
   a small deterministic benchmark.

6. **Not a replacement for Soar/ACT-R.** MorphSAT occupies one layer of what those
   architectures handle end-to-end. The relationship is complementary, not
   competitive.

---

## F. RELATIONSHIP TO EXISTING WORK

| System | Shared structure | Key difference |
|---|---|---|
| Soar metacognition | Impasse → deliberation → resolution | Soar: internal. MorphSAT: external. |
| ACT-R conflict resolution | Evidence → threshold → action | ACT-R: utility-based. MorphSAT: posture-based. |
| Active inference | Surprise → evidence → belief update | Active inference: generative model. MorphSAT: no world model. |
| SPRT (Wald 1943) | Sequential evidence → boundaries → decision | SPRT: optimal for fixed hypotheses. MorphSAT: heuristic boundaries. |
| Defensive cascade (Kozak 2015) | Arousal → orient → defend → commit | Biological analogy for posture transitions. |
| SMART (ACL 2025) | Tool-overuse mitigation | SMART: internal self-awareness. MorphSAT: external governor. |
| Know Your Limits (TACL 2025) | Abstention / calibration | Survey; MorphSAT provides architectural mechanism. |

---

## G. REFERENCES

- Wald, A. (1943). Sequential tests of statistical hypotheses. *Annals of Mathematical Statistics.*
- Wray, Jones, Laird (2023). Constraint compliance. arXiv:2303.04352.
- Jones, Laird (2019). Anticipatory thinking with event cognition. CEUR-WS.
- Kozak et al. (2015). Fear and the defense cascade. PMC4495877.
- Laird (2012). *The Soar Cognitive Architecture.* MIT Press.
- Parr, Friston (2017). Active inference and learning. *Neuroscience & Biobehavioral Reviews.*
- Chen et al. (2025). SMART: Self-Aware Agent for Tool Overuse Mitigation. ACL Findings.
- Wang et al. (2025). Stop Spinning Wheels: Mitigating LLM Overthinking. arXiv:2508.17627.
- Wen et al. (2025). Know Your Limits: Abstention in LLMs. TACL.
- Nature (2024). Online metacognitive control of decisions.

---

## H. PAPER OUTLINE (Josh's structure)

### Title
**MorphSAT: Exogenous Evidence Governance for LLM Agents**

Working subtitle: *When Should an Agent Stop Looking and Start Acting?*

### Plain-Language Thesis
"LLM agents with tool access face a fundamental commit-or-continue problem: when
is evidence sufficient to act? MorphSAT places this decision in an external
governance layer the model cannot see, game, or override. The result is a system
that knows when to commit, when to abstain, and when to escalate — without asking
the model to know any of those things."

### Abstract Elements
- Problem: LLM agents with tool access loop or commit prematurely
- Gap: Existing approaches ask the model to self-regulate (internal metacognition)
- Approach: External evidence-governance state machine (exogenous metacognitive control)
- Key results: v1→v8.3 progression (55%→100%), adversarial robustness (3/3 gates),
  dual-boundary smooths phase transition, PPLTL compliance (0 violations / 1008 traces),
  second-domain transfer, architecture/sensor separation proven via 2×2 factorial
- Honest scope: N=20, simulated tools, one primary model, partial architecture

### Section Structure

1. **Introduction** — The commit-or-continue problem. Why internal metacognition fails
   for LLMs (model can game its own uncertainty). The exogenous alternative.

2. **Contributions** — (a) Exogenous evidence governance architecture, (b) Posture-based
   novelty handling, (c) Dual-boundary uncertainty-preserving commitment, (d) Formal
   compliance verification, (e) Architecture/sensor separation proof.

3. **Architecture** — State machine, evidence accumulation, leaky integration,
   dual-boundary mode, ABSTAIN as first-class outcome. Vocabulary mapping to
   Soar/ACT-R/SPRT.

4. **Experimental Progression** — The honest chain: v1 fails → v4 improves → v5/v6
   fail → v7 succeeds → v8 scales → adversarial testing → sensitivity analysis →
   dual-boundary → compliance → transfer → sensor swap. Negative results are findings.

5. **Results Summary** — Per-phase tables. 2×2 factorial (sensor × architecture).
   ABSTAIN profile. PPLTL compliance.

6. **What This Is Not** — Honest scope (see Section E above).

7. **Why This Matters** — The exogenous principle: don't ask the model to know when
   it's confused. The architecture/sensor separation: the governor works regardless
   of sensor quality. The ABSTAIN mechanism: systems should be allowed to say
   "I don't know" instead of guessing.

8. **Future Work** — Third domain, larger scenario sets, real tool outputs (not simulated),
   formal SPRT implementation, integration with existing cognitive architectures.

---

## I. THE BOUNDARY PROBLEM — Key Framing for Paper

From `THE_BOUNDARY_PROBLEM.md`:

The strongest claim is not any single benchmark result. It's:

> An exogenous governance architecture with one-sided evidence accumulation
> exhibits a structural phase transition at the commit boundary. Adding temporal
> decay creates a wide operating range but does not eliminate the transition.
> The natural formalization is sequential hypothesis testing (SPRT), which
> replaces the one-sided boundary with an explicit uncertainty zone.

That claim is:
- **Falsifiable** (the phase transition is measurable)
- **Reproducible** (the sensitivity sweep is deterministic)
- **Connected to established theory** (Wald 1943)
- **Architecture-level** (not sensor-dependent, not model-dependent)
- **General** (applies to any one-sided accumulator, not just MorphSAT)

---

## J. STEVEN JONES VALIDATION — External Credibility

Steven Jones (scijones@umich.edu, Laird/Soar group at University of Michigan)
reviewed MorphSAT and validated:

1. Soar mapping is legitimate ("I'm not offended by your Figure 3")
2. Benign recovery is "the kind of result we want too"
3. Exogenous meta-management is the core novelty
4. Formal guarantees are "the sell"

Steven's framing of MorphSAT's contribution:
"MorphSAT isn't trying to make the LLM smarter; it's making the system around
the LLM fault-tolerant. That is a massive distinction in the current agent
landscape."

Steven identified the publishable distinction: **internal open-ended cognition
(Soar) vs. external rigid governor (MorphSAT).**

---

## K. PHYSICAL INTUITION → ARCHITECTURAL INSIGHT

The bridge from Josh's day job to MorphSAT:

| Field Safety Concept | MorphSAT Analogue |
|---|---|
| Lockout/tagout | Irreversible COMMIT (terminal state) |
| Pressure rating | Commit threshold (0.55) |
| Go/no-go gauge | Dual-boundary (pass/fail/continue) |
| Safety interlock | Exogenous governor (model can't see or override) |
| Pressure relief valve | ABSTAIN (release uncertainty instead of exploding) |
| Independent inspector | Dual-agent recomputation gate |
| Fusion log/record | Receipt (episodic audit trail) |
| "The pipe doesn't know the interlock exists" | "The model never sees the governor's state" |

This is not an analogy bolted on after the fact. Josh's intuition for exogenous
control came FROM field safety systems. The architecture embodies the principle
that safety-critical decisions should not depend on the controlled system's
self-awareness.

---

## L. VOICE RATIO GUIDE FOR GPT

**15% Josh origin / machine intuition:**
- Origin story paragraphs (fusion tech, self-taught, constrained hardware)
- "What if" moments (the exogenous insight)
- Physical-system metaphors (interlock, pressure gauge, relief valve)
- Plain-language thesis statements
- Honest self-positioning ("I don't have a CS degree")

**70% Cognitive architecture + agent safety vocabulary:**
- Architecture description using reviewer labels
- Relationship to Soar/ACT-R/SPRT/active inference
- Evidence accumulation formalism
- State machine specification
- PPLTL compliance properties
- Literature positioning

**15% Receipts, limits, and future work:**
- Exact numbers with confidence qualifiers
- N=20 caveat, simulated tools caveat
- What is NOT claimed
- What would strengthen the claims
- Future domains, larger benchmarks, real tools

**Voice rules:**
- "Your voice opens the door. Steven's vocabulary lets experts walk through it.
  The receipts make them stay."
- Active voice, short sentences for Josh sections
- Formal but not stuffy for architecture sections
- Unflinching honesty in limitations sections
- Negative results are findings, not failures
