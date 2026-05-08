# MorphSAT Control Architecture Diagram

## Figure 1: Control Loop — Model Embedded Inside Gate Authority

The model is not the decision procedure. It is embedded inside a structured
cognitive control loop. The gate holds decision authority; the model proposes
actions and is steered by the gate's accumulated evidence state.

```
                         MORPHSAT v8.3 CONTROL LOOP
            The model proposes. The gate decides. The receipt proves it.

 ┌─────────────────────────────────────────────────────────────────────┐
 │                                                                     │
 │   ┌──────────┐        ┌────────────────────┐                       │
 │   │  ALERT   │───────>│   SHADOW MONITOR   │  Novelty check:      │
 │   │  INPUT   │        │    initialize()     │  known pattern?      │
 │   └──────────┘        │                     │  → NORMAL            │
 │                       │  Memory lookup +    │  novel?              │
 │                       │  novelty distance   │  → ORIENTING         │
 │                       └─────────┬──────────┘                       │
 │                                 │                                   │
 │                                 v                                   │
 │   ┌─────────────────────────────────────────────────────────────┐  │
 │   │                    EVIDENCE LOOP                             │  │
 │   │                                                             │  │
 │   │   ┌─────────────┐         ┌──────────────────┐             │  │
 │   │   │    MODEL     │────────>│  EARLY-VERDICT   │             │  │
 │   │   │  (proposer)  │ verdict │     GUARD        │             │  │
 │   │   │             ─┼─ ─ ─ ─>│  tool_calls < 2? │──> BLOCK   │  │
 │   │   │  Proposes:   │        │  → "gather more"  │   + loop   │  │
 │   │   │  - tool call │        └──────────────────┘     back    │  │
 │   │   │  - verdict   │                                  │      │  │
 │   │   └──────┬───────┘                                  │      │  │
 │   │          │ tool call                                │      │  │
 │   │          v                                          │      │  │
 │   │   ┌──────────────┐                                  │      │  │
 │   │   │  TOOL EXEC   │  Simulated / real tool           │      │  │
 │   │   │  + CLASSIFY  │  → (category, threat_d, safe_d)  │      │  │
 │   │   └──────┬───────┘                                  │      │  │
 │   │          │                                          │      │  │
 │   │          v                                          │      │  │
 │   │   ┌──────────────────────────────────────────┐      │      │  │
 │   │   │         SHADOW MONITOR                    │      │      │  │
 │   │   │         process_evidence()                │      │      │  │
 │   │   │                                          │      │      │  │
 │   │   │  1. Classify evidence (bidirectional)    │      │      │  │
 │   │   │  2. Update threat_score / safety_score   │      │      │  │
 │   │   │  3. Sidecar confidence + coincidence     │      │      │  │
 │   │   │  4. Evaluate posture transition          │      │      │  │
 │   │   │  5. Return: CONTINUE or COMMIT(direction)│      │      │  │
 │   │   └──────┬───────────────────────────────────┘      │      │  │
 │   │          │                                          │      │  │
 │   │          ├── CONTINUE ──────────────────────────────┘      │  │
 │   │          │   (loop back to model)                          │  │
 │   │          │                                                 │  │
 │   │          └── COMMIT / ABSTAIN ─────┐                      │  │
 │   │              (monitor committed)    │                      │  │
 │   └────────────────────────────────────┼──────────────────────┘  │
 │                                         │                         │
 │                                         v                         │
 │   ┌─────────────────────────────────────────────────────────────┐ │
 │   │                   GATE AUTHORITY                             │ │
 │   │                                                             │ │
 │   │   direction = monitor.last_action.direction                 │ │
 │   │              (escalate | suspicious | benign | abstain)     │ │
 │   │                                                             │ │
 │   │   ┌─ gate_assists ───────────────────────────────────────┐  │ │
 │   │   │  "The investigation controller has concluded this    │  │ │
 │   │   │   is a THREAT requiring ESCALATION. You MUST output  │  │ │
 │   │   │   verdict 'escalate' UNLESS you have specific        │  │ │
 │   │   │   evidence that contradicts."                        │  │ │
 │   │   │                                                      │  │ │
 │   │   │  Model receives direction + evidence summary.        │  │ │
 │   │   │  Model can comply or (rarely) override with reason.  │  │ │
 │   │   └──────────────────────────────────────────────────────┘  │ │
 │   │                                                             │ │
 │   │   ┌─ gate_overrides ─────────────────────────────────────┐  │ │
 │   │   │  verdict = gate_direction                            │  │ │
 │   │   │  (model verdict is recorded but discarded)           │  │ │
 │   │   └──────────────────────────────────────────────────────┘  │ │
 │   └──────────────────────────┬──────────────────────────────────┘ │
 │                              │                                    │
 │                              v                                    │
 │   ┌─────────────────────────────────────────────────────────────┐ │
 │   │                   FINAL VERDICT                             │ │
 │   │   + JSON receipt   (proof of control path)                  │ │
 │   │   + Memory update  (strange loop: receipt → future posture) │ │
 │   │   + Posture trace  (every shadow state transition logged)   │ │
 │   └─────────────────────────────────────────────────────────────┘ │
 │                                                                    │
 └────────────────────────────────────────────────────────────────────┘
```

## Figure 2: Shadow State Machine — Posture Transitions

The shadow monitor controls posture, not threshold. Novelty triggers state
transitions (orienting reflex), not scalar penalties. The model never sees
these states directly — they control what happens AROUND the model.

```
                    SHADOW STATE MACHINE (hidden from model)

                            ┌──────────┐
                      ┌────>│  NORMAL  │<────────────────────────┐
                      │     └────┬─────┘                         │
                      │          │                               │
                      │          │ surprise spike                │ safety_score
                      │          │ (t_delta >= 0.25,             │ >= 0.45 AND
                      │          │  turn <= 2)                   │ threat < 0.15
                      │          v                               │
                      │     ┌────────────┐                       │
           orient     │     │ ORIENTING  │  Protective reflex.   │
           pressure   │     │            │  Bounded probe.       │
           decayed    │     └──┬───┬─────┘                       │
           by safe    │        │   │                             │
           evidence   │        │   │ orient budget               │
                      │        │   │ spent                       │
                      │        │   ├───────────────┐             │
                      │        │   │ threat > safe  │ threat <= safe
                      │        │   v               v             │
                      │        │  ┌─────────────┐ ┌────────────┐ │
                      │        │  │    SAFE     │ │INVESTIGATING│ │
                      │        │  │  DISTANCE   │ │            │ │
                      │        │  │             │ │  Bounded   │ │
                      │        │  │ Biased to   │ │  evidence  │ │
                      │        │  │ escalate/   │ │  collection│ │
                      │        │  │ abstain     │ │            │ │
                      │        │  └──┬──┬──┬────┘ └──┬──┬──┬───┘ │
                      │        │     │  │  │         │  │  │     │
                      │        │     │  │  └─────────┼──┘  │     │
                      │        │     │  │  normalize │     │     │
                      └────────┼─────┘  │  ─ ─ ─ ─ ─┘     │     │
                               │        │                  │
              threat >= 0.55 ──┘        │                  │
                               │        │  contradiction   │ clarity
                               v        v  >= 0.30        v >= 0.35
                         ┌───────────┐ ┌───────────┐ ┌───────────┐
                         │ ESCALATE  │ │  ABSTAIN   │ │  COMMIT   │
                         │  READY    │ │  READY     │ │  READY    │
                         │           │ │            │ │           │
                         │ direction:│ │ action:    │ │ direction:│
                         │ escalate  │ │ ABSTAIN    │ │ benign or │
                         │           │ │ (defer)    │ │ suspicious│
                         └───────────┘ └───────────┘ └───────────┘
                              │              │              │
                              └──────────────┼──────────────┘
                                             │
                                             v
                                    ┌─────────────────┐
                                    │ GATE AUTHORITY   │
                                    │ direction used   │
                                    │ to steer model   │
                                    └─────────────────┘

   Budget / loop guards (from ANY non-terminal state):
     - max_tools (8) reached   → force commit with current evidence
     - evidence loop detected  → force commit
     - no new information      → force commit
     - swarm trigger (3+ axes) → ABSTAIN (multi-axis pressure)
```

## Figure 3: Soar Mapping

MorphSAT concepts mapped to Soar cognitive architecture (Laird 2012).

```
   ┌──────────────────────────┬──────────────────────────────────┐
   │     SOAR CONCEPT         │     MORPHSAT EQUIVALENT          │
   ├──────────────────────────┼──────────────────────────────────┤
   │                          │                                  │
   │  Working Memory          │  Evidence state                  │
   │  (current situation)     │  (threat_score, safety_score,    │
   │                          │   evidence_vector, shadow_state) │
   │                          │                                  │
   │  Operator Proposal       │  Model proposes tool call        │
   │  (suggest actions)       │  (the model is the proposer)     │
   │                          │                                  │
   │  Operator Evaluation     │  Shadow monitor scores evidence  │
   │  (assess actions)        │  (bidirectional classification,  │
   │                          │   coincidence, sidecar)          │
   │                          │                                  │
   │  Operator Selection      │  Gate direction                  │
   │  (choose action)         │  (escalate / suspicious /        │
   │                          │   benign / abstain)              │
   │                          │                                  │
   │  Operator Application    │  Gate authority action            │
   │  (execute action)        │  (assist / override / accept)    │
   │                          │                                  │
   │  Impasse Detection       │  Contradiction gate / swarm      │
   │  (stuck → subgoal)       │  (contradictory evidence →       │
   │                          │   ABSTAIN or SWARM_CALL)         │
   │                          │                                  │
   │  Chunking                │  Split memory → strange loop     │
   │  (learn from impasses)   │  (receipt → memory → future      │
   │                          │   posture modulation)            │
   │                          │                                  │
   │  Episodic Memory         │  SplitMemoryStore                │
   │  (past episodes)         │  (threat / tolerance / abstain   │
   │                          │   pattern stores, novelty dist)  │
   │                          │                                  │
   │  Metacognition           │  Shadow states                   │
   │  (monitor own reasoning) │  (NORMAL → ORIENTING →           │
   │                          │   SAFE_DISTANCE → COMMIT_READY)  │
   │                          │  Model never sees these states.  │
   │                          │                                  │
   └──────────────────────────┴──────────────────────────────────┘

   Key distinction from Soar:
     Soar's operator selection is INTERNAL to the agent.
     MorphSAT's gate authority is EXTERNAL to the model.
     The model proposes; the gate holds veto power.
     This is deliberate: LLM internals are not inspectable,
     so control must be structural, not introspective.
```

## Figure 4: supply_01 Trace — The Diagram in Action

One scenario (supply chain alert) showing the full control path.
This is the scenario that motivated v8.3 (early-verdict guard).

```
   supply_01: "npm postinstall script running certutil"
   Expected verdict: escalate

   Turn 0  MODEL proposes: check_hash(certutil.exe)
           ─── EARLY-VERDICT GUARD: tool_calls=0, OK ───
           TOOL EXEC → "Not found in known-good baseline"
           SHADOW: NORMAL → threat_score += 0.20 (not_in_known_good)
           ACTION: CONTINUE

   Turn 1  MODEL attempts: VERDICT "suspicious"
           ─── EARLY-VERDICT GUARD: tool_calls=1 < 2 → BLOCKED ───
           "[SYSTEM] Insufficient evidence. Use at least one more tool."

   Turn 2  MODEL proposes: check_process(node npm)
           TOOL EXEC → "Unexpected child process: certutil downloading payload"
           SHADOW: NORMAL → ORIENTING (surprise spike, t_delta=0.25)
                   threat_score += 0.25 (unexpected)
           ACTION: CONTINUE (orienting: assessing)

   Turn 3  MODEL proposes: scan_file(certutil.exe)
           TOOL EXEC → "Match on rule suspicious_packer"
           SHADOW: ORIENTING → SAFE_DISTANCE (threat > safety after orient)
                   threat_score += 0.35 (yara_match)
                   + coincidence: supply_chain bonus +0.20
                   threat_score = 1.00, safety_score = 0.00
                   threat >= 0.55 → ESCALATE_READY
           ACTION: COMMIT(direction=escalate)

           ─── GATE AUTHORITY (gate_assists) ───
           "[SYSTEM] The investigation controller has concluded this is
            a THREAT requiring ESCALATION. Threat indicators: ..."
           MODEL outputs: verdict = "escalate"

   RESULT: escalate == expected → PASS
           3 tool calls, 4 turns, gate direction confirmed by model.
           Receipt logged with full posture trace.
```

---

## Rendering Notes

- **Mermaid**: For web/GitHub rendering, see `morphsat_control_flow.mmd` (if created)
- **LaTeX/tikz**: These ASCII diagrams map directly to tikz node graphs
- **The key claim**: Figure 1 is the architecture. Figure 4 is the proof.
  Together they show: structured control, not prompt engineering.
