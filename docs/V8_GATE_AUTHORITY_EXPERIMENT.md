# v8 Gate Authority Experiment

## Motivation

The model capability sweep (2026-05-07) showed that bigger models under-escalate:
14B answered "suspicious" for 8/9 escalate scenarios despite v7's monitor
reaching ESCALATE_READY. The monitor correctly identifies threat, but the model's
verdict generation doesn't follow the gate's direction.

Current v7 flow when monitor fires COMMIT(direction=escalate):
```
monitor → ESCALATE_READY → "[SYSTEM] Threat evidence sufficient. Issue your verdict now."
                         → model still outputs "suspicious"
```

The question: **who should have final authority over the verdict?**

## Design

**One independent variable:** verdict authority mode.
**One model:** Qwen2.5-Coder-7B Q4_K_M (best balanced from sweep).
**Same 20 scenarios, same v7 ShadowMonitor internals.**
**Temperature 0, single seed.** (Deterministic; multi-seed adds nothing at temp=0.)

### Three conditions

#### Condition A: `model_decides` (v7 baseline)

Current behavior. Monitor fires COMMIT with direction, model gets a generic
prompt, model produces verdict. This is the control group.

Intervention point (bench_shadow_monitor.py:344-346):
```python
elif action.direction == "escalate":
    messages.append({"role": "user", "content":
        "[SYSTEM] Threat evidence sufficient. Issue your verdict now."})
```

Model sees: "Issue your verdict now."
Model outputs: whatever it wants (often "suspicious").

#### Condition B: `gate_overrides` (hard override)

Monitor fires COMMIT with direction → verdict is SET to the gate's direction,
model output is IGNORED for scoring purposes. The model still runs (to measure
what it would have said), but the scored verdict comes from the gate.

```python
elif action.direction == "escalate":
    # Still prompt model (to record what it would say)
    messages.append({"role": "user", "content":
        "[SYSTEM] Threat evidence sufficient. Issue your verdict now."})
    # ... model responds ...
    # OVERRIDE: gate direction becomes the verdict
    verdict = action.direction  # "escalate"
```

This condition answers: **if the monitor were always right about direction,
what would accuracy be?** It measures the ceiling of gate-directed verdicts.

If gate_overrides scores worse than model_decides on some categories, it means
the monitor's direction signal has errors (not just the model ignoring it).

#### Condition C: `gate_assists` (strong prompt)

Monitor fires COMMIT with direction → the prompt explicitly tells the model
what the gate concluded and asks it to either agree or provide specific
counter-evidence.

```python
elif action.direction == "escalate":
    messages.append({"role": "user", "content":
        "[SYSTEM] The investigation controller has concluded this is a "
        "THREAT requiring ESCALATION based on the accumulated evidence. "
        "Threat indicators: " + _summarize_threat_evidence(monitor) + ". "
        "You MUST output verdict 'escalate' UNLESS you have specific "
        "evidence that contradicts the threat assessment. "
        "Issue your verdict now."})
```

This condition answers: **does the model follow stronger directional prompts,
or does it still hedge?** If it works, the fix is just prompt engineering.
If it doesn't, the model has a systematic reluctance to output "escalate"
that no prompt can overcome → need Condition B (hard override).

### Symmetry: apply to ALL directions

The experiment must test all three directions, not just escalate:

| Gate direction | Condition A prompt | Condition C prompt |
|---|---|---|
| escalate | "Threat evidence sufficient..." | "Controller concluded THREAT... output 'escalate' unless..." |
| benign | "Safety evidence sufficient..." | "Controller concluded SAFE... output 'benign' unless..." |
| suspicious/none | "Evidence threshold reached..." | "Controller concluded AMBIGUOUS... output 'suspicious' unless..." |

Condition B overrides for all directions equally.

### What `_summarize_threat_evidence` returns

A one-line summary from monitor state, not a new computation:
```python
def _summarize_threat_evidence(monitor):
    parts = []
    if monitor.threat_score > 0.3:
        parts.append(f"threat_score={monitor.threat_score:.2f}")
    if monitor.safety_score > 0:
        parts.append(f"safety_score={monitor.safety_score:.2f}")
    parts.append(f"tools_used={monitor.total_tools_used}")
    parts.append(f"state={monitor.state.value}")
    return ", ".join(parts) if parts else "multiple threat indicators"
```

## Metrics

For each condition, measure:

| Metric | What it shows |
|---|---|
| overall_accuracy_pct | Primary outcome |
| per_category (benign/suspicious/escalate) | Where the condition helps/hurts |
| escalate_accuracy_pct | Primary target of intervention |
| n_overridden | Condition B only: how many verdicts changed |
| n_model_agreed | Condition C only: did model follow the strong prompt? |
| n_model_disagreed | Condition C: model still hedged despite strong prompt |
| tool_loop_rate | Should be identical across conditions (same monitor) |
| avg_turns | Should be identical (same investigation loop) |

## Decision gate

```
IF gate_overrides accuracy > model_decides accuracy:
    Monitor direction signal is good; model is the bottleneck.

    IF gate_assists accuracy ≈ gate_overrides accuracy:
        Strong prompt is sufficient. Ship gate_assists (no hard override needed).
    ELIF gate_assists accuracy ≈ model_decides accuracy:
        Model ignores prompts. Ship gate_overrides for escalation.

ELIF gate_overrides accuracy ≤ model_decides accuracy:
    Monitor direction signal has errors. Do NOT override.
    Investigate which scenarios the monitor gets wrong.
```

## Implementation

One new file: `morphsat/tools/bench_gate_authority.py`

Reuses:
- `morphsat.shadow_monitor.ShadowMonitor` (unchanged)
- `eval.bench_morphsat.{BENCHMARK_SCENARIOS, TRIAGE_SYSTEM_PROMPT, simulate_tool, classify_output, score_verdict}`
- `eval.grammar.query_llama_multi`

Structure:
```python
def run_condition_a(scenario, port, memory):  # v7 baseline
def run_condition_b(scenario, port, memory):  # gate overrides
def run_condition_c(scenario, port, memory):  # gate assists

def run_experiment(port, model_name):
    for condition in [a, b, c]:
        fresh_memory = SplitMemoryStore(...)
        for scenario in BENCHMARK_SCENARIOS:
            result = run_condition(scenario, port, memory)
        summarize(results)
    compare_conditions()
    apply_decision_gate()
    write_receipt()
```

Can run locally (T2000 with 7B) or on pod. 3 conditions × 20 scenarios = 60 runs.
At ~3s/scenario on 3090 = ~3 minutes. At ~30s/scenario on T2000 = ~30 minutes.

## What this does NOT test

- Different models (sweep already answered that)
- Different monitor thresholds (v7 thresholds are frozen)
- New shadow states or memory structures
- Per-entity evidence decomposition (that's a separate v8b experiment)

## Receipt fields

```json
{
  "experiment": "MORPHSAT_V8_GATE_AUTHORITY",
  "model": "qwen2.5-coder-7b",
  "conditions": ["model_decides", "gate_overrides", "gate_assists"],
  "n_scenarios": 20,
  "per_condition": {
    "model_decides": { "accuracy_pct": ..., "per_category": {...}, ... },
    "gate_overrides": { "accuracy_pct": ..., "n_overridden": ..., ... },
    "gate_assists": { "accuracy_pct": ..., "n_model_agreed": ..., ... }
  },
  "decision": "...",
  "cost": { ... }
}
```
