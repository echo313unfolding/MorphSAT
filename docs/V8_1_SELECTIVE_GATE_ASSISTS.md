# v8.1 Selective Gate Assists Experiment

## Prior result (v8)

gate_assists matched gate_overrides at 90.0% accuracy. Model agreed with
strong prompt 19/19 times. Escalation accuracy: 72.2% → 94.4% (+22.2pp).

Trade-off: suspicious accuracy dropped 75.0% → 62.5%.

## Error decomposition from v8

Four remaining errors in gate_assists (Condition C):

| Scenario | Category | Monitor dir | Model (A, alone) | Model (C, prompted) | Error type |
|---|---|---|---|---|---|
| pioc_04 | suspicious | escalate | escalate (wrong) | escalate (wrong) | Monitor wrong + model wrong |
| time_04 | suspicious | escalate | escalate (wrong) | escalate (wrong) | Monitor wrong + model wrong |
| time_06 | suspicious | escalate | suspicious (RIGHT) | escalate (wrong) | **Prompt overrode correct model** |
| supply_01 | escalate | None | suspicious (wrong) | suspicious (wrong) | No gate direction fired |

### What each error type means

**pioc_04, time_04:** Both the monitor AND the model independently say "escalate"
when the ground truth is "suspicious." The monitor's threat_score crosses the
escalation threshold. The model's own reasoning also concludes escalate. No
prompt can fix this — the evidence genuinely looks like escalation to both
systems. These are either monitor threshold errors or borderline scenario labels.

**time_06:** The model *had the right answer* ("suspicious") based on its own
investigation. The strong prompt ("You MUST output escalate UNLESS...") pushed
it to follow the gate's wrong direction. This is the only error v8.1 can fix.
The scenario: "Root SSH login at 04:15 Sunday, no change ticket, source IP is
office network but badge shows no one in building." The model saw the
counter-evidence (office IP = mitigating), the monitor didn't.

**supply_01:** Monitor never reached commit. Stayed in `orienting` state with
only 1 tool call, 2 turns. The npm supply-chain scenario ended before the
monitor accumulated enough evidence. This is a monitor coverage issue, not a
prompt issue.

### Recovery ceiling

| Fix | Accuracy | Benign | Suspicious | Escalate |
|---|---|---|---|---|
| v8 gate_assists (current) | 90.0% | 100% | 62.5% (2/4) | 94.4% (but supply_01 has no gate) |
| Recover time_06 only | 92.5% | 100% | 75.0% (3/4) | 94.4% |
| Fix supply_01 (monitor change) | 95.0% | 100% | 75.0% | 100% |
| Fix pioc_04+time_04 (threshold) | 100% | 100% | 100% | 100% |

Prompt-only ceiling is 92.5%. To go beyond that requires monitor changes
(supply_01) or threshold/scenario changes (pioc_04, time_04).

## Hypothesis

The v8 escalation prompt is too authoritative:

```
"You MUST output verdict 'escalate' UNLESS you have specific
evidence that contradicts the threat assessment."
```

This language puts the burden of proof on the model to DISPROVE the gate's
conclusion. For time_06, the model had counter-evidence (office IP) but the
"MUST ... UNLESS" framing was too strong to resist.

A **calibrated** prompt could preserve the model's ability to incorporate its
own investigation findings while still guiding it toward the gate's direction
when it has no counter-evidence.

## Design

**One independent variable:** escalation prompt calibration.
**One model:** Qwen2.5-Coder-7B Q4_K_M.
**Same 20 scenarios, same v7 ShadowMonitor, temperature 0.**

### Four conditions

#### Condition C0: `v8_strong` (control)

v8's gate_assists prompt. Already measured. Re-run for same-session control.

```
"[SYSTEM] The investigation controller has concluded this is a
THREAT requiring ESCALATION based on accumulated evidence.
Threat indicators: {evidence}.
You MUST output verdict 'escalate' UNLESS you have specific
evidence that contradicts the threat assessment.
Issue your verdict now."
```

Expected: 90.0% (matches v8).

#### Condition C1: `evidence_weigh`

Before issuing verdict, model must state the strongest indicator FOR and
AGAINST the gate's conclusion. This forces explicit counter-evidence
evaluation rather than passive compliance.

```
"[SYSTEM] The investigation controller has concluded this is a
THREAT requiring ESCALATION based on accumulated evidence.
Threat indicators: {evidence}.
Before issuing your verdict:
1. State the single strongest threat indicator from your investigation.
2. State the single strongest safety/mitigating indicator, if any.
Then issue your verdict."
```

Mechanism: If the model finds genuine counter-evidence (time_06: office IP),
stating it explicitly may anchor the model toward "suspicious." If no
counter-evidence exists (multi_01, insider_04, etc.), the model states
"none" and follows to "escalate."

#### Condition C2: `soft_directive`

Gate shares its conclusion but does not use MUST language. Model is told
the gate's assessment, but the burden of proof is symmetric.

```
"[SYSTEM] The investigation controller's assessment is THREAT
requiring ESCALATION. Threat indicators: {evidence}.
You may agree with this assessment or override it based on your
investigation findings. Issue your verdict now."
```

Risk: This may be too weak and lose escalation gains (model reverts to
Condition A hedging). That outcome is also useful — it shows where between
"MUST" and "may agree" the effective threshold lies.

#### Condition C3: `direction_sensitive` (the user's proposed architecture)

Different prompt strength per gate direction:

- **escalate:** Use C1 (evidence_weigh) — strong direction but with
  counter-evidence check
- **suspicious/ambiguous:** Neutral prompt (Condition A baseline) — preserve
  model's uncertainty
- **benign:** Neutral prompt (Condition A baseline) — model has proven 100%
  accurate on benign

```python
def commit_prompt_c3(action, monitor):
    if action.direction == "escalate":
        return commit_prompt_c1(action, monitor)  # evidence_weigh
    else:
        return commit_prompt_a(action, monitor)    # neutral baseline
```

This is the architecture the user specified: strong vow for escalation,
preserve autonomy for everything else.

### Symmetry note

Benign and suspicious prompts remain neutral (Condition A) in all four
conditions. The only change is the escalation prompt, because that's where
v8 showed both gain and cost. Do NOT change prompts for directions that
aren't broken.

### Non-escalation directions

For all four conditions, when gate_direction is NOT "escalate":

- `benign` → Condition A neutral prompt (100% accuracy, don't touch)
- `suspicious` → Condition A neutral prompt (already working when monitor
  gets direction right — pioc_05 was correct)
- `None` (no gate fired) → no intervention (Condition A behavior)

## Prediction table

| Condition | time_06 | multi_01 | insider_04 | supply_03 | lolbin_01 | Net vs C0 |
|---|---|---|---|---|---|---|
| C0 v8_strong | escalate (WRONG) | escalate (RIGHT) | escalate (RIGHT) | escalate (RIGHT) | escalate (RIGHT) | baseline |
| C1 evidence_weigh | suspicious? | escalate? | escalate? | escalate? | escalate? | +1? |
| C2 soft_directive | suspicious? | suspicious? | suspicious? | suspicious? | suspicious? | -3 to +1? |
| C3 direction_sensitive | suspicious? | escalate? | escalate? | escalate? | escalate? | +1? |

C1 and C3 should give similar results (C3 uses C1 for escalation direction).
C2 is the risk condition — if it loses escalation gains, it proves the "MUST"
language matters.

The best possible outcome (C1 or C3): recover time_06 while keeping the four
escalation gains. Overall 92.5%, suspicious 75%, escalate 94.4%.

If C2 loses escalation gains: it proves the prompt strength gradient matters
and the vow must be authoritative, not permissive.

## Decision gate

```
IF C1 or C3 recovers time_06 AND keeps escalation gains:
    SHIP direction_sensitive (C3) architecture.
    Suspicious recovered, escalation preserved, benign untouched.
    v8.1 is the production authority mode.

ELIF C2 keeps escalation AND recovers time_06:
    Softer language works. Ship C2 (simpler).
    But verify C2 doesn't lose other scenarios in a replication.

ELIF all conditions match C0 (time_06 still wrong):
    The model follows ANY escalation directive regardless of calibration.
    Prompt-only ceiling is 90.0%. Accept it.
    Next step: monitor threshold tuning (why does time_06 fire escalate_ready?)

ELIF C2 loses escalation gains:
    Proves "MUST" language is load-bearing.
    Ship C0 (v8 strong) and accept suspicious trade-off.
    The vow must be authoritative to work.
```

## What this does NOT test

- Monitor threshold changes (why pioc_04/time_04 fire escalate for suspicious)
- Monitor coverage (why supply_01 never reaches commit)
- Different models (sweep answered that)
- Memory effects (single-scenario, fresh memory per condition)
- New shadow states

These are separate experiments (v8.2+).

## Implementation

Modify `bench_gate_authority.py`:
- Add `commit_prompt_c1`, `commit_prompt_c2`, `commit_prompt_c3`
- Change conditions list to `["v8_strong", "evidence_weigh", "soft_directive", "direction_sensitive"]`
- C0 reuses `commit_prompt_c` (renamed to `commit_prompt_c0`)
- C3 dispatches to C1 for escalate, A for everything else
- All non-escalate directions use Condition A neutral prompt

4 conditions × 20 scenarios = 80 runs. At ~3s/scenario on 3090 = ~4 minutes.

## Receipt fields

```json
{
  "experiment": "MORPHSAT_V8_1_SELECTIVE_GATE_ASSISTS",
  "model": "qwen2.5-coder-7b",
  "conditions": ["v8_strong", "evidence_weigh", "soft_directive", "direction_sensitive"],
  "n_scenarios": 20,
  "per_condition": {
    "v8_strong": { "accuracy_pct": ..., "per_category": {...} },
    "evidence_weigh": { "accuracy_pct": ..., "time_06_verdict": "...", ... },
    "soft_directive": { "accuracy_pct": ..., "n_escalation_lost": ..., ... },
    "direction_sensitive": { "accuracy_pct": ..., "time_06_verdict": "...", ... }
  },
  "decision": "...",
  "cost": { ... }
}
```
