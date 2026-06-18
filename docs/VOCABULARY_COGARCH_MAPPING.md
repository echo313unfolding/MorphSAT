# Vocabulary: MorphSAT ↔ Cognitive Architecture

**Purpose:** Quick-reference translation between MorphSAT implementation names and reviewer-facing cognitive architecture terms. Implementation names are used in code and internal docs. Reviewer labels are used in papers, talks, and correspondence with researchers.

**Rule:** Do not rename code. Shadow Monitor stays Shadow Monitor in `shadow_monitor.py`. Use reviewer labels in papers and external communication. This file is the bridge.

---

## Core Components

| Implementation Name | Reviewer Label | Domain | Notes |
|---|---|---|---|
| Shadow Monitor | Exogenous appraisal monitor | Soar/metacognition | "Exogenous" = outside the model. Steven's term. |
| shadow state | control mode / posture | ACT-R, metacognition | The hidden state the model never sees. |
| posture | metacognitive control mode | metacognition | NORMAL, ORIENTING, SAFE_DISTANCE, etc. |
| gate authority | structured decision override | control theory | gate_assists = directive; gate_overrides = veto. |
| commit gate | evidence-based commit controller | decision theory | Fires irreversibly. Action potential analogy. |
| recomputation gate | dual-agent verification | fault tolerance | Independent second agent; disagreement = escalate. |

## Evidence System

| Implementation Name | Reviewer Label | Domain | Notes |
|---|---|---|---|
| threat_delta | threat appraisal update | appraisal theory | Per-turn contribution to accumulated threat. |
| safety_delta | safety appraisal update | appraisal theory | Per-turn contribution to accumulated safety. |
| threat_score | accumulated threat appraisal | appraisal theory | Running total after decay. |
| safety_score | accumulated safety appraisal | appraisal theory | Running total after decay. |
| evidence_clarity | decision confidence / preference strength | decision theory | `abs(threat_score - safety_score)`. |
| evidence_balance | signed evidence accumulator | SPRT | `threat_score - safety_score`. Positive = threat-leaning. |
| evidence_decay | temporal discounting / leaky integration | neuroscience | Early evidence loses weight over time. Cytokine half-life. |
| sidecar_confidence | model self-report confidence | metacognition | Extracted from model output, not trusted as ground truth. |
| coincidence_check | multi-signal convergence boost | evidence theory | Supralinear boost when multiple independent signals align. |

## State Machine

| Implementation Name | Reviewer Label | Domain | Notes |
|---|---|---|---|
| NORMAL | baseline monitoring | — | Default state. Ordinary evidence collection. |
| ORIENTING | protective orienting response | defensive cascade (PMC4495877) | Novel/surprising input → bounded investigation. |
| SAFE_DISTANCE | cautious engagement | threat assessment | Threat-leaning but not confirmed. Risky actions suppressed. |
| INVESTIGATING | bounded evidence collection | active sensing | Budget-limited investigation. |
| COMMIT_READY | decision commitment | decision theory | Enough evidence to act. Terminal. |
| ABSTAIN_READY | recognized ambiguity / deferred judgment | abstention literature | Evidence insufficient or contradictory. |
| ESCALATE_READY | threat escalation | incident response | Danger exceeds local capacity. |
| SWARM_CALL | multi-axis consultation request | distributed cognition | Pressure from multiple axes simultaneously. |

## Dual-Boundary / SPRT Mode

| Implementation Name | Reviewer Label | Domain | Notes |
|---|---|---|---|
| commit_threat_boundary | upper decision boundary | SPRT (Wald 1943) | Evidence balance above this → commit threat. |
| commit_safe_boundary | lower decision boundary | SPRT | Evidence balance below this → commit safe. |
| continue zone | uncertainty preservation region | sequential analysis | Between boundaries. System gathers more evidence. |
| ABSTAIN (budget exhaustion) | inconclusive / deferred | SPRT truncation | Budget runs out inside continue zone → no invented verdict. |
| boundary_crossed | threshold exceedance | decision theory | Which boundary was crossed (threat/safe/none). |

## Memory

| Implementation Name | Reviewer Label | Domain | Notes |
|---|---|---|---|
| SplitMemoryStore | dual-store episodic memory | Soar semantic/episodic | Threat and tolerance patterns stored separately. |
| threat memory | threat-pattern familiarity | immune system (inflammation) | Known dangerous patterns. Lowers commit threshold. |
| tolerance memory | benign-pattern familiarity | immune system (tolerance) | Known safe patterns. Prevents permanent inflammation. |
| novelty_distance | familiarity gradient | pattern matching | How far the current alert is from anything seen before. |
| close_episode | episodic encoding / memory consolidation | cognitive science | Post-decision: write experience to memory. The strange loop. |

## Receipts / Audit

| Implementation Name | Reviewer Label | Domain | Notes |
|---|---|---|---|
| receipt | episodic audit record | verification | Turn-by-turn JSON proof of behavior. |
| posture_trace | state transition log | formal verification | Every posture change with trigger and metrics. |
| history | evidence accumulation trace | audit | Per-turn record of scores, states, actions. |
| cost block | computational resource accounting | reproducibility | Wall time, CPU time, peak memory. WO-RECEIPT-COST-01. |

## Architecture Layers

| Implementation Name | Reviewer Label | Domain | Notes |
|---|---|---|---|
| FSA lifecycle gate | constraint compliance layer | Wray/Jones/Laird (2023) | Legal operator ordering. |
| evidence sensors | appraisal subsystem | appraisal theory | Bidirectional classification of tool results. |
| shadow monitor | metacognitive control layer | metacognition | Posture tracking. Hidden from model. |
| gate authority | decision authority layer | control theory | Override or assist the model's verdict. |
| early-verdict guard | premature commitment prevention | decision theory | Structural minimum-evidence requirement. |
| dual-agent gate | independent verification layer | fault tolerance | Recomputation by second agent. |
| dual-store memory | experience-modulated familiarity | episodic memory | Threat/tolerance learning across episodes. |

---

## Usage Convention

**In code:** `monitor.threat_score`, `ShadowState.ORIENTING`, `evidence_decay`
**In papers:** "accumulated threat appraisal," "protective orienting response," "temporal discounting"
**In email to Steven:** Either vocabulary works — he reads code. Use reviewer labels for clarity.
