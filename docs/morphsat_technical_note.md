# MorphSAT: Structured Commit Control for LLM Agent Loops

**Technical Note v1 — May 2026**
**echo313unfolding**

---

## 1. The Problem

An LLM agent with tool access can loop indefinitely — calling tools, reading
results, reasoning, calling more tools — without ever committing to a decision.
Alternatively, it can commit prematurely on insufficient evidence. Both failure
modes are well-documented: overthinking (Wang et al. 2025, arXiv:2508.17627),
tool overuse (Chen et al. 2025, ACL Findings), and the general question of
when to abstain (Wen et al. 2025, TACL).

The standard approach is prompt engineering: instruct the model to "be
decisive" or "stop after N tools." This treats the model as the decision
procedure. MorphSAT takes the opposite position: **the model is not the
decision procedure. It is embedded inside a structured cognitive control loop
that holds decision authority.**

## 2. Architecture

MorphSAT wraps an LLM's tool-use loop in a five-layer control stack:

| Layer | Component | Role |
|-------|-----------|------|
| 1 | FSA lifecycle gate | Legal state transitions only. Blocks impossible sequences. |
| 2 | Evidence sensors | Bidirectional classification: each tool result produces (threat_delta, safety_delta). Coincidence detection boosts on multi-signal convergence. |
| 3 | Shadow monitor | Hidden posture state machine. Controls what happens *around* the model. The model never sees these states. |
| 4 | Split memory | Separate threat and tolerance pattern stores. Familiarity modulates future posture. |
| 5 | Receipts | Turn-by-turn audit trace: every state transition, evidence classification, and posture change is logged in a JSON receipt. |

The shadow monitor (Layer 3) is the key contribution. It maintains eight
posture states — NORMAL, ORIENTING, SAFE_DISTANCE, INVESTIGATING,
COMMIT_READY, ESCALATE_READY, ABSTAIN_READY, SWARM_CALL — and transitions
between them based on accumulated evidence, not scalar thresholds. When the
monitor commits to a direction (escalate, suspicious, benign, or abstain), it
communicates that direction to the model via a structured prompt. The model can
comply or, rarely, override with specific justification. In the benchmarked
`gate_assists` condition, the model complied with the monitor's direction in
100% of cases.

**Novelty is a posture problem, not a threshold problem.** MorphSAT v6
treated novelty as a scalar penalty (raise the commit threshold for unfamiliar
inputs). This failed: the agent over-investigated benign scenarios and never
learned tolerance. v7 replaced novelty-as-penalty with novelty-as-reflex:
unfamiliar input triggers an ORIENTING state with a bounded investigation
budget. Safe evidence decays the orienting pressure (a tolerance response).
This single change improved benign accuracy from 35.7% to 78.6%.

## 3. Experimental Setup

**Task domain:** Security alert triage. 20 scenarios across three categories
(7 benign, 4 suspicious, 9 escalate). Each scenario presents an alert and
provides 5 simulated security tools (check_hash, check_process, scan_file,
check_network, check_cve). Tool responses are deterministic per scenario.

**Model:** Qwen2.5-Coder-7B (Q4_K_M quantization) via llama-server.
Temperature 0 (greedy decoding). The model is a 7B coding-focused model, not
a security specialist. This is deliberate: we test the control structure's
ability to compensate for a model operating outside its primary domain.

**Three conditions:**
- `model_decides` — The model receives neutral prompts and makes its own verdict. The shadow monitor runs but does not influence the model's output.
- `gate_overrides` — The model outputs a verdict, but the gate replaces it with the monitor's direction. The model's verdict is recorded but discarded.
- `gate_assists` — The monitor communicates its direction to the model via a strong directional prompt ("The investigation controller has concluded this is a THREAT requiring ESCALATION"). The model makes the final call.

**v8.3 early-verdict guard:** An additional structural control that blocks the
model from issuing a verdict before gathering at least 2 tool results. This
was added after diagnosing a specific failure (supply_01) where the model
issued a premature "suspicious" verdict after a single tool call, before the
monitor had accumulated enough evidence to commit.

## 4. Results

**v8.3 receipt:** `morphsat_v83_gate_authority_20260508T125045Z.json`
(SHA256-stamped, 60 scenario runs).

| Condition | Accuracy | Benign | Suspicious | Escalate | Tool loops |
|-----------|----------|--------|------------|----------|------------|
| model_decides | 85.0% | 100% | 75.0% | 77.8% | 0% |
| gate_overrides | **100%** | 100% | 100% | 100% | 0% |
| gate_assists | **100%** | 100% | 100% | 100% | 0% |

**Key findings:**
- The monitor's evidence accumulation produces the correct direction in 20/20 scenarios. The model is the bottleneck, not the monitor.
- `gate_overrides` corrected 6 model errors (6 helped, 0 hurt).
- `gate_assists` achieved 100% model agreement — the model followed the monitor's direction in every case when given a structured directional prompt.
- Escalation accuracy improved +22.2pp from model_decides to gate_assists.

**Progression across versions** (same 20 scenarios, varying control structures):

| Version | Mechanism | Accuracy |
|---------|-----------|----------|
| v4 | Evidence-pressure threshold | 62.5% |
| v7 | Shadow posture control | 70.0% |
| v8.0 | + gate_assists prompting | 90.0% |
| v8.2 | + classifier and threshold fixes | 97.5% |
| **v8.3** | **+ early-verdict guard** | **100%** |

## 5. What This Demonstrates

**The control structure, not the model, is the decision authority.** The same
7B model achieves 85% accuracy when deciding alone and 100% when embedded in
the MorphSAT control loop. The gap is not prompt engineering — it is
structural: an external state machine accumulates evidence, tracks posture,
and communicates direction through a typed interface.

**Mapping to cognitive architecture concepts** (Laird 2012; Jones & Laird 2019):

| Soar concept | MorphSAT equivalent |
|---|---|
| Working memory | Evidence state (threat/safety scores, evidence vector, shadow state) |
| Operator proposal | Model proposes tool call |
| Operator evaluation | Shadow monitor scores evidence (bidirectional + coincidence) |
| Operator selection | Gate direction (escalate / suspicious / benign / abstain) |
| Impasse detection | Contradiction gate (both scores high) or swarm trigger (multi-axis) |
| Chunking / episodic memory | Split memory store: receipt closes the loop for future posture |
| Metacognition | Shadow states: NORMAL, ORIENTING, SAFE_DISTANCE, etc. (hidden from model) |

The key structural difference: Soar's metacognition monitors the agent's own
reasoning from the inside. MorphSAT's shadow monitor controls the agent from
the outside. This is a deliberate design choice: LLM internals are opaque, so
metacognitive control must be extrinsic and structural rather than
introspective.

## 6. Caveats

- **N=20 scenario benchmark, single model (7B), single domain (security triage).** The control structure's generality is demonstrated by design (domain-configurable FSA, JSON-loadable specs) but not yet by multi-domain experiments.
- **Simulated tools, not live environment.** Tool responses are deterministic per scenario. Real-world tool outputs are noisy and variable.
- **gate_assists 100% is an upper bound on this benchmark**, not a claim about arbitrary inputs. The 20 scenarios were designed for discriminability; adversarial or ambiguous scenarios may reveal weaker performance.
- **The evidence classifier is keyword-based**, not learned. Deploying to a real domain would require a domain-specific classifier or a learned evidence encoder.

## 7. Availability

MorphSAT is open source (MIT license).

- **PyPI:** `pip install morphsat` (v0.4.0)
- **Source:** `github.com/echo313unfolding/MorphSAT`
- **Receipt:** Full JSON trace at `receipts/morphsat_v83_early_verdict_guard/`

## References

- Chen et al. (2025). *SMART: Self-Aware Agent for Tool Overuse Mitigation.* ACL Findings.
- Jones & Laird (2019). *Anticipatory Thinking via Event Cognition.* CEUR-WS.
- Kozak et al. (2015). *Fear and the Defense Cascade.* PMC4495877.
- Laird (2012). *The Soar Cognitive Architecture.* MIT Press.
- Wang et al. (2025). *Stop Spinning Wheels: Mitigating LLM Overthinking.* arXiv:2508.17627.
- Wen et al. (2025). *Know Your Limits: Abstention in LLMs.* TACL.
- Wray, Jones, & Laird (2023). *Constraint Compliance.* arXiv:2303.04352.
