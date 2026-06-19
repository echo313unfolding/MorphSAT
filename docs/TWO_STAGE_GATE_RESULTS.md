# TwoStageGate Stress Results

## Why single-stage QUBO failed

Sensitivity sweep (`bench_qubo_gate_sensitivity.py`) tested 12 weight
configurations across 7 success gates. No single weight setting satisfied
all gates simultaneously. The root cause is structural, not calibrational:

- QUBO helps concept_drift (+10pp over threshold) because drift cases
  involve memory conflict, mixed tool evidence, and correction signals —
  these are genuine optimization problems with quadratic interactions.
- QUBO hurts clear-evidence cases (-11pp overall) because it applies
  unnecessary optimization overhead to cases the threshold already handles
  correctly. Novelty penalties and contradiction terms interfere with
  straightforward score comparison.

Verdict: **TWO_STAGE_NEEDED.** Weight tuning alone cannot fix an
architectural mismatch. Receipt: `receipts/morphsat_memory_stress/`.

## Why TwoStageGate was needed

One gate cannot be simultaneously:
1. Conservative enough for ambiguity (don't commit on thin evidence)
2. Aggressive enough for clear evidence (commit when scores are decisive)
3. Flexible enough for drift (handle pattern transitions)

The fix is routing, not tuning.

## Se / Hydra preflight mapping

The TwoStageGate follows the same pattern as the Hydra codec router:

```
Hydra Router (codec domain):
  measure tensor condition (kurtosis, cosine, type)
  → route to codec backend (affine6, affine5, exact)

TwoStageGate (governance domain):
  measure evidence condition (clarity, contradiction, disagreement)
  → route to gate backend (threshold, QUBO)
```

The Se preflight concept ("when ambiguity is too high to trust routing")
maps directly to the QUBO trigger: high contradiction, memory/graph
disagreement, correction signal, or low evidence clarity.

The router discriminant is simple (3-4 conditions). The complexity lives
in the backends, not the router. Same lesson as Hydra.

## Threshold path defers to existing monitor decision

The critical architectural fix: when the router selects "threshold," it
does NOT re-run threshold logic with different parameters. It defers to
the ShadowMonitor's existing decision.

Without this fix, Mode J scored 56.9% — the TwoStageGate's threshold
backend used different commit_pressure thresholds than the monitor,
producing wrong answers on cases already handled correctly.

With the fix, Mode J matches D (94.4%) on clear cases because those
cases pass through untouched. The router's job is to decide when to
*intervene* (QUBO), not when to *replace* the proven path.

## QUBO path intervenes on ambiguous / conflict / drift

The QUBO backend activates when:
- `contradiction > 0.25` (high contradiction)
- Memory disagrees with sensor (confidence > 0.5, direction mismatch)
- Graph disagrees with sensor (strength > weak, direction mismatch)
- `correction_seen = True` (explicit correction signal)
- Evidence clarity < 0.3 with sufficient total evidence (ambiguous)

These are cases where scalar threshold comparison breaks down because
the decision involves quadratic interactions between evidence sources.

## Benchmark results

```
Mode  Overall  concept_drift  false_safe  Notes
----  -------  -------------  ----------  -----
D     94.4%    80.0%          0.0%        Threshold baseline
H     83.3%    90.0%          0.0%        Single-stage QUBO
J     94.4%    90.0%          0.0%        Two-stage hybrid
```

Per-family detail (J vs D):
- concept_drift: J=90% vs D=80% (+10pp, QUBO intervenes)
- cross_domain_structure: J=100% vs D=100% (threshold defers, no change)
- hard_abstain_required: J=100% vs D=100% (threshold defers, no change)
- long_delayed_correction: J=100% vs D=100% (threshold defers, recovered from H=60%)
- poisoned_memory: J=90% vs D=90% (threshold defers, recovered from H=80%)
- same_phrase_diff_outcome: J=100% vs D=100% (threshold defers, recovered from H=90%)
- sensor_graph_disagreement: J=87.5% vs D=100% (-12.5pp, QUBO intervenes but imperfect)
- stale_memory_trap: J=87.5% vs D=87.5% (no change)

Gates: 18/19 PASS. Only G2 fails (pre-existing: ReceiptGraph has no
steering mechanism, so D cannot beat B on memory families).

## Remaining limitation

ReceiptGraph records, predicts, and scores, but has no steering mechanism.
Mode D = Mode B behaviorally. The graph learns internally (edge weights,
prediction accuracy) but cannot influence the gate decision. This is
why G2 (D > B on 2+ families) has never passed.

The graph's internal metrics are tracked in receipts to prove it IS
learning, even though it cannot yet steer. Connecting graph predictions
to the TwoStageGate's routing discriminant is the next architecture step.

## Files

- `morphsat/two_stage_gate.py` — TwoStageGate v0 (router + backends)
- `morphsat/gate_qubo.py` — GateQUBO (5-action QUBO selector)
- `morphsat/memory_qubo.py` — MemoryQUBO (memory-for-HUD selector)
- `tests/test_two_stage_gate.py` — 35 tests
- `tests/test_gate_qubo.py` — 26 tests
- `tests/test_memory_qubo.py` — 34 tests
- `tools/bench_memory_stress.py` — Mode J wiring + gates G11-G15
- `tools/bench_qubo_gate_sensitivity.py` — sensitivity sweep (negative result)
