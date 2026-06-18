# Steven Jones Recommendations — MorphSAT Next Steps

**Source:** Steven Jones email, June 2026 (scijones@umich.edu, Laird/Soar group)
**Context:** Steven reviewed MorphSAT cogarch translation + technical note + repo

---

## What Steven Validated

1. **Soar mapping is legitimate.** "I'm not offended by your Figure 3: Soar mapping." Novelty/threat/safety map to Soar appraisals. Orient state maps to impasse behavior.

2. **Benign recovery result is the kind of result they want too.** "Much of why we're doing some of this research is to try to show a result like this... but in a generic sense." The 35.7% -> 78.6% benign recovery is a shared research target.

3. **MorphSAT as partial architecture.** "You're right to consider this a partial architecture." Not dismissive — he's saying the scope is honest.

---

## What Steven Identified as Novel

### Exogenous Meta-Management (the "secret weapon")

Steven (via LLM + his own agreement) identified the core architectural distinction:

| | Soar | MorphSAT |
|---|---|---|
| **Where metacognition lives** | Inside the agent (impasse -> substate -> self-reasoning) | Outside the model (Shadow Monitor -> environment manipulation) |
| **Model awareness** | Agent sees its own impasses | Model never sees governor states |
| **Design philosophy** | Make the agent self-aware | Make the deployment fault-tolerant |

Steven's framing: "MorphSAT isn't trying to make the LLM smarter; it's making the system around the LLM fault-tolerant."

**Action:** Lean into "internal open-ended cognition vs. external rigid governor" split in all future writing. This is the publishable distinction.

---

## What Steven Challenged

### 1. Intermediate Variable Robustness

> "The convincing thing to me would be more a proof about the generality of these intermediate values you accumulate over time, that they are sensitive to the right info, span the space in a decision theoretic sense."

**Translation:** `threat_delta`, `safety_delta`, `evidence_clarity` — are these measuring reality, or are they implementation details that happen to work on 20 scenarios?

**Steven's stance:** This proof is NOT NECESSARY to publish, but it would be the next-level convincing thing.

### 2. Formal Guarantees as the Sell

> "The sell is 'hey look, I can get formal guarantees out of this', and then architectures would feel a bit more pressure to think of what they do with working memory."

**Translation:** The MorphSAT paper should say: here is a structured control system with auditable guarantees (receipts, deterministic state machine, PPLTL-style compliance). Architectures like Soar should adopt this formalism.

### 3. Decision Theory / Active Sensing Literature

> "I know that there are decent proofs in the decision theory literature about this kind of thing re: 'active sensing'. I can rustle them up."

**Translation:** The evidence accumulation pattern (gather -> threshold -> commit) has formal theory behind it. Likely connection: Wald's Sequential Probability Ratio Test (SPRT, 1943). The shadow monitor's state machine may approximate SPRT: evidence accumulates until hitting an upper bound (COMMIT) or lower bound (ABSTAIN).

---

## Steven's Recommended Next Steps (in his words, then translated)

### Step 1: Adversarial Stress-Test

Steven's LLM suggested, Steven partially agreed:

> "What happens if you introduce 'noisy' or contradictory tool outputs? Can your evidence accumulation decay safely, or does a single false keyword permanently brick the Shadow Monitor's posture?"

**What this means concretely:**

Design an adversarial benchmark with 4 injection types:
- **False positives:** Benign tool output contains threat keywords
- **False negatives:** Malicious tool output lacks expected threat keywords
- **Contradictory evidence:** One tool says threat, another says safe, in the same scenario
- **Delayed signal:** Critical evidence only appears on the 3rd or 4th tool call

**Measure:** Does `threat_delta` accumulation recover from noise, or does it brick?

**Important distinction (from Claude analysis):** This tests the CLASSIFIER (keyword matching), not the ARCHITECTURE (exogenous monitoring). Design TWO conditions:
1. Adversary vs. current keyword classifier
2. Adversary vs. upgraded classifier (embeddings or LLM-as-judge)

If architecture wins with better sensor, the contribution is architectural, not classifier-dependent.

### Step 2: Formalize Evidence Accumulation

Steven's challenge: prove intermediate values "span the space in a decision theoretic sense."

**Practical version (Steven's own translation):** Don't write a math paper. Do a parameter sweep:
- Vary `threat_delta` contribution weights
- Vary `evidence_clarity` thresholds
- Vary posture transition boundaries
- Show that performance degrades smoothly (not cliff-edge) as parameters shift

This demonstrates the variables are measuring something real, not overfitted to 20 scenarios.

### Step 3: Multi-Domain Generalization

Steven's implicit challenge (from "but in a generic sense"):

Run MorphSAT on a second domain. Security triage is one task type. Try:
- Code review triage (approve / request changes / escalate to senior)
- Medical triage (treat / observe / refer)
- Financial alert triage (clear / flag / freeze)

Same architecture, different FSA config + evidence keywords. If benign recovery transfers, the architecture claim generalizes.

### Step 4: PPLTL/Formal Compliance Framing

> "You'd want something more like [formal compliance] for industrial usage."

Steven is saying: frame MorphSAT's FSA gate as PPLTL (Past-time Linear Temporal Logic) compliance. The receipts already capture state transitions — prove they satisfy temporal logic properties:
- "COMMIT never fires before INVESTIGATE"
- "ESCALATE requires evidence_clarity < threshold"
- "No state transition is irreversible except COMMIT/ESCALATE/ABSTAIN"

This is doable with existing receipt data. It's a verification section in the paper.

---

## Priorities (Ranked)

| Priority | Action | Effort | Impact |
|----------|--------|--------|--------|
| **1** | Adversarial stress-test (noisy/contradictory tools) | **DONE** | 2/3 gates PASS. Post-commit correction OPEN. v9 correction pathway shipped. See `ADVERSARIAL_ROBUSTNESS_RESULTS.md` |
| **1.5** | Leaky evidence accumulator (temporal decay) | **DONE** | **3/3 gates PASS.** Delayed correction 50%→93.8–100%. See `ADVERSARIAL_ROBUSTNESS_RESULTS.md` |
| **1.6** | Decay sensitivity map | **DONE** | Operating range [0.50, 0.85]. 31.3pp cliff at boundary. NOT smooth — three regions + phase transition. Cliff is structural (commit threshold interaction). See `ADVERSARIAL_ROBUSTNESS_RESULTS.md` |
| **3** | Dual-boundary / uncertainty-preserving commitment | **DONE** | Cliff smoothed: 31.3pp → 12.5pp. Operating range widened [0.75,0.85] → [0.82,0.99]. ABSTAIN on budget exhaustion inside continue zone. See `ADVERSARIAL_ROBUSTNESS_RESULTS.md` Plan 3 section. |
| **4** | Parameter sensitivity sweep | **DONE (merged into 1.6)** | Response surface characterized. Cliff explained. Competing objectives documented. |
| **5** | PPLTL compliance proof from receipts | **DONE** | 7/7 properties × 1008 traces = 0 violations. Properties: never-commit-before-min-evidence, never-escalate-without-threat, continue-zone-budget-exhaustion-abstains, correction-before-terminal, commitment-cites-boundary, legal-state-transitions, threat-decay-monotonicity. See `tools/check_compliance.py`. Receipts: `~/receipts/morphsat_compliance/` |
| **2** | Second domain (code review or financial triage) | 3-5 days | Proves generality beyond security |

---

## What NOT to Do

1. **Don't send Ghost/Crystal Vault connections to Steven.** The parallel ("what invariant survives degradation") is a poetic analogy, not a structural relationship. Ghost invariants are topological features of weight tensors. MorphSAT's threat_delta is a keyword-derived scalar. Mentioning this to Steven weakens credibility of the strong parts.

2. **Don't try to write a decision theory math paper.** Steven explicitly said the parameter sweep / adversarial test is the coder's superpower. Play to strength.

3. **Don't oversell the 100% result.** Steven knows N=20 is small. Lead with the architecture, not the number.

---

## Draft Reply Modifications

Josh's draft reply (from ChatGPT analysis) is structurally sound but needs 3 edits:

1. **Drop or soften the Ghost parallel.** One sentence max, not a structural claim.

2. **Sharpen architecture vs. classifier distinction** when responding to robustness challenge: "You're right that the sensor (keyword classifier) is brittle — here's our plan to test that. But the architectural commitment (exogenous monitoring boundary) is the contribution, and we believe it survives sensor upgrades."

3. **Engage with the decision theory thread.** Steven handed a gift — formal theory that makes reviewers take the work seriously. Mention SPRT / sequential analysis by name. Ask Steven to send the active sensing references he mentioned.

---

## Key Quotes to Remember

Steven:
- "I'm not offended by your Figure 3: Soar mapping."
- "Much of why we're doing some of this research is to try to show a result like [benign recovery]."
- "The sell is 'hey look, I can get formal guarantees out of this'."
- "The convincing thing to me would be... proof about the generality of these intermediate values."
- "MorphSAT is doing exogenous meta-management — it's an external straightjacket."

Steven's LLM (Steven-endorsed):
- "MorphSAT isn't trying to make the LLM smarter; it's making the system around the LLM fault-tolerant."
- "They can now say: MorphSAT isn't trying to make the LLM smarter; it's making the system around the LLM fault-tolerant. That is a massive distinction in the current agent landscape."
