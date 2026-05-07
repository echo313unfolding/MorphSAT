# Translation Layer: MorphSAT → Cognitive Architecture Terms

MorphSAT is a constraint-control testbed for local LLM agents. This document
maps its internal vocabulary to terms from cognitive architecture research
(Soar, ACT-R, active inference) so the contribution is legible without
learning project-specific names first.

## The research question

**When should a local LLM agent stop gathering evidence and commit to an action?**

This is an operator-selection and metacognitive-control problem. The agent has
tools, can call them in a loop, and must decide when enough evidence exists to
act — or when to abstain, escalate, or request help.

## Term mapping

| MorphSAT internal term | Cognitive-architecture analogue | What it does |
|---|---|---|
| Finite-state lifecycle gate | **Constraint compliance / legal operator ordering** | Prevents impossible task-state transitions (e.g., deploy before test). |
| Pressure gate (v4) | **Evidence-based commit controller** | Accumulates evidence quality, urgency decay, and sidecar confidence. Fires irreversibly when pressure crosses threshold — like an action potential. |
| Shadow monitor (v7) | **Anticipatory posture controller / metacognitive monitor** | Hidden state machine that tracks novelty, threat, safety, loops, and stagnation. Controls the agent's investigation loop without the model's awareness. |
| ORIENT state | **Protective orienting response** | Novel input triggers a bounded investigation posture rather than indefinite deliberation. Maps to the defensive cascade: arousal → orient → active defense → commit. |
| SAFE_DISTANCE state | **Cautious engagement** | Monitoring continues, but risky actions are suppressed until evidence clarifies. |
| Tolerance memory | **Benign-pattern familiarity** | Patterns the system has seen resolve safely. Prevents novelty from becoming permanent inflammation. Analogous to immune tolerance. |
| Threat memory | **Threat-pattern familiarity** | Patterns the system has seen escalate. Lowers the commit threshold for known dangers. |
| Abstain patterns | **Recognized ambiguity** | Patterns where local evidence was insufficient. Recorded to speed future escalation. |
| Swarm escalation | **Bounded specialist consultation** | When pressure is multi-axis (contradiction + novelty + loop + budget), the agent signals it cannot resolve locally. Currently resolves as abstention; designed for multi-agent handoff. |
| Receipts | **Episodic execution traces** | Turn-by-turn records of state, evidence, posture transitions, and outcomes. Every decision is auditable. |
| SplitMemoryStore | **Dual-store episodic memory** | Threat and tolerance traces stored separately, queried by pattern similarity. Allows bidirectional familiarity learning. |
| Evidence clarity | **Decision confidence / operator preference strength** | The gap between accumulated threat and safety scores. High clarity → ready to commit. |
| Cold-start novelty (v6, failed) | **Novelty-as-penalty (abandoned)** | Treated novelty as a scalar threshold increase. Failed because it prevented commitment on benign scenarios. Replaced by ORIENT posture in v7. |
| QUBO homeostasis | **Resource-aware homeostatic control** | System-level energy cost / action selection / route bias. Same control motif as v7 but at infrastructure scale rather than evidence scale. |

## How this maps to Soar concepts

For readers familiar with Soar (Laird 2012):

| Soar concept | MorphSAT analogue | Notes |
|---|---|---|
| Working memory | Current tool results + shadow monitor state | Evidence accumulates here during investigation. |
| Operator proposal / selection | Pressure gate + shadow monitor posture | Evidence pressure biases toward COMMIT; shadow state can suppress or redirect. |
| Impasses / substates | Swarm escalation | Multi-axis pressure that exceeds local capacity triggers escalation rather than looping. |
| Procedural memory (rules) | FSA transition table + guardian veto rules | Hard constraints on legal state transitions. |
| Semantic memory | Threat/tolerance pattern store | Long-term familiarity with known threat and benign configurations. |
| Episodic memory | Receipt trace | Chronological record of what happened, what was decided, and why. |
| Metacognition | Shadow monitor | Monitors the agent's own investigation for loops, stagnation, contradiction, and budget exhaustion. |
| SVS (Spatial Visual System) | *(not yet mapped)* | Token adjacency scoring has structural parallels but is not a spatial substrate. |

## What the v7 result shows

The proof chain across 7 versions:

```
v1  Static FSA constraints          → 0 useful interventions (too weak)
v2  Fixed tool-call counter (3)     → +12.5pp accuracy (any pressure helps)
v3  Adaptive budget (2/3/5)         → no improvement (ceiling irrelevant, floor matters)
v4  Evidence-pressure gate          → +10pp accuracy, best escalation detection
v5  Pattern memory                  → mechanics work, accuracy fails (threat bias)
v6  Bidirectional + split memory    → worse than v4 (novelty-as-penalty is wrong)
v7  Anticipatory posture controller → best accuracy, best benign recovery
```

The key finding: **novelty handling is a posture problem, not a threshold problem.**

When novelty was treated as a penalty (raise the commit threshold), the agent
over-investigated benign scenarios and never learned tolerance. When novelty
was treated as an orienting state (enter protective posture, gather bounded
evidence, relax when safe), benign recovery improved from 35.7% to 78.6%.

## Validated benchmark (deterministic, N=20)

|  | Evidence-pressure (v4) | Anticipatory posture (v7) |
|---|---|---|
| Overall accuracy | 62.5% | **70.0%** |
| Tool-loop rate | 35.0% | **25.0%** |
| Avg turns | 5.4 | **4.8** |
| Benign accuracy | 35.7% | **78.6%** |
| Suspicious accuracy | **75.0%** | 62.5% |
| Escalation accuracy | **77.8%** | 66.7% |

v7 trades suspicious/escalate accuracy for overall accuracy and benign recovery.
The tradeoff is real and not yet resolved.

## Caveats

- N=20 scenario benchmark with simulated tool responses
- Temperature=0 (deterministic) — no stochastic variance
- Qwen2.5-Coder-3B doing security triage — small model, not its strongest domain
- The shadow monitor is tested on one task type (alert triage)
- This is a testbed, not a production cognitive architecture

## References

- Wray, Jones, Laird — *Constraint Compliance* (arXiv:2303.04352, 2023)
- Jones, Laird — *Anticipatory Thinking with Event Cognition* (CEUR-WS, 2019)
- Kozak et al. — *Fear and the Defense Cascade* (PMC4495877, 2015)
- Parr, Friston — *Active Inference and Learning* (Neuroscience & Biobehavioral Reviews, 2017)
- Chen et al. — *SMART: Self-Aware Agent for Tool Overuse Mitigation* (ACL Findings, 2025)
- Wang et al. — *Stop Spinning Wheels: Mitigating LLM Overthinking* (arXiv:2508.17627, 2025)
- Wen et al. — *Know Your Limits: Abstention in LLMs* (TACL, 2025)
- Laird — *The Soar Cognitive Architecture* (MIT Press, 2012)
