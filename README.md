<div align="center">

<img alt="MorphSAT" src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1117,100:1a6b6b&height=200&section=header&text=MorphSAT&fontSize=42&fontColor=58a6ff&animation=fadeIn&fontAlignY=35&desc=Constraint-control%20testbed%20for%20local%20LLM%20agents&descSize=16&descColor=8b949e&descAlignY=55" width="100%">

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-109%20passed-brightgreen)]()
[![Checkpoint](https://img.shields.io/badge/checkpoint-v8.3--gate--authority-blue)]()
[![PyPI](https://img.shields.io/pypi/v/morphsat)](https://pypi.org/project/morphsat/)

**Structured commit control for LLM agent loops. The model proposes; the gate decides.**

</div>

## What is this?

MorphSAT is a testbed for studying **when a local LLM agent should stop gathering evidence and commit to an action.**

An LLM agent with tool access can loop indefinitely — calling tools, reading results, calling more tools — without ever deciding. Or it can commit prematurely on insufficient evidence. MorphSAT wraps the agent's loop in a structured cognitive control stack — an external state machine that accumulates evidence, tracks posture, and holds decision authority. The model proposes actions; the gate decides when and how to commit.

The current checkpoint (v8.3) achieves **100% accuracy** on a 20-scenario security triage benchmark across all three control conditions, up from 85% when the model decides alone.

> **For cognitive architecture researchers:** See [`docs/COGNITIVE_ARCHITECTURE_TRANSLATION.md`](docs/COGNITIVE_ARCHITECTURE_TRANSLATION.md) for a term mapping to Soar, ACT-R, and active inference. See [`docs/morphsat_technical_note.md`](docs/morphsat_technical_note.md) for the 2-page technical note with full results.

## The proof chain

Nine versions tested on a 20-scenario security alert triage benchmark (Qwen2.5-Coder-7B, temperature 0, simulated tools):

| Version | Mechanism | Accuracy | Key finding |
|---|---|---|---|
| v1 | Static FSA constraints | 55% | 0 useful interventions — too weak |
| v2 | Fixed tool-call counter | 67.5% | Any pressure helps |
| v3 | Adaptive budget (2/3/5) | 55-67.5% | Ceiling irrelevant, floor matters |
| v4 | Evidence-pressure gate | 65% | Best escalation (77.8%), best pre-v7 |
| v5 | + pattern memory | 62.5% | Learned threats without tolerance |
| v6 | + bidirectional pressure | 55% | Novelty-as-penalty is the wrong abstraction |
| v7 | Anticipatory posture control | 70% | Benign recovery 78.6% (was 35.7%) |
| v8.0 | + gate authority (assists) | 90% | Model follows structured direction |
| v8.2 | + classifier/threshold fixes | 97.5% | 2 bugs: false yara match, threshold mismatch |
| **v8.3** | **+ early-verdict guard** | **100%** | **Blocks premature verdicts before min evidence** |

## v8.3 result

Three experimental conditions, 20 scenarios each (60 total runs):

| Condition | Accuracy | Benign | Suspicious | Escalate | Description |
|---|---|---|---|---|---|
| model_decides | 85.0% | 100% | 75.0% | 77.8% | Model alone, monitor runs silently |
| gate_overrides | **100%** | 100% | 100% | 100% | Gate replaces model verdict |
| gate_assists | **100%** | 100% | 100% | 100% | Gate steers model via strong prompt |

- `gate_overrides` corrected 6 model errors (6 helped, 0 hurt).
- `gate_assists` achieved 100% model agreement — the model followed the monitor's direction in every case.
- Escalation accuracy: +22.2pp from model_decides to gate_assists.

**Key insight:** The control structure, not the model, is the decision authority. The same 7B model achieves 85% accuracy alone and 100% when embedded in the MorphSAT control loop. The gap is structural, not prompt engineering: an external state machine accumulates evidence, tracks posture, and communicates direction through a typed interface.

## Architecture

```
Layer 1: FSA lifecycle gate
         Legal task-state transitions. Blocks impossible sequences.

Layer 2: Evidence sensors
         Bidirectional classification: each tool result produces
         (threat_delta, safety_delta). Coincidence detection boosts
         on multi-signal convergence. Sidecar confidence from model output.

Layer 3: Shadow monitor (v7+)
         Hidden posture state machine wrapping the agent's loop.
         Novelty → ORIENT → bounded investigation → decide.
         Safe evidence decays protective posture (tolerance).
         The model never sees these states — they control what
         happens AROUND the model.

Layer 4: Gate authority (v8+)
         When the monitor commits to a direction, it communicates
         that direction to the model (gate_assists) or overrides
         the model's verdict entirely (gate_overrides).

Layer 5: Early-verdict guard (v8.3)
         Blocks the model from issuing a verdict before gathering
         minimum evidence (2 tool calls). Structural, not prompt-based.

Layer 6: Dual-store memory
         Threat patterns and tolerance patterns stored separately.
         Familiarity modulates future posture (the strange loop).

Layer 7: Receipts
         Turn-by-turn JSON audit: state, evidence, posture, outcomes.
         Every decision is reproducible. SHA256-stamped.
```

### Shadow monitor states

```
NORMAL ──→ ORIENTING ──→ SAFE_DISTANCE ──→ NORMAL (safe recovery)
              │                  └──→ ESCALATE_READY (threat confirmed)
              │                  └──→ ABSTAIN_READY (contradictory)
              │
              └──→ INVESTIGATING ──→ COMMIT_READY (clear evidence)
                        │            ESCALATE_READY (high threat)
                        │            ABSTAIN_READY (contradictory)
                        └──→ SWARM_CALL (multi-axis pressure)

Budget guards from any state: max tools, evidence loop, no new info → force commit
```

> **Full architecture diagram:** See [`docs/morphsat_control_diagram.md`](docs/morphsat_control_diagram.md) for control flow, shadow state machine, Soar mapping, and a worked example (supply_01 trace).

## Install

```bash
pip install morphsat
```

Or from source:

```bash
git clone https://github.com/echo313unfolding/MorphSAT.git
cd MorphSAT
pip install -e ".[dev]"
```

## Quick start

### FSA lifecycle gate

```python
from morphsat import MorphSATGate, TaskState, TaskEvent

gate = MorphSATGate()
state, legal, action = gate.step(TaskEvent.NEW_TASK)
assert state == TaskState.PLANNING
assert legal is True
```

### Shadow monitor + gate authority (v8.3)

```python
from morphsat import ShadowMonitor, SplitMemoryStore

memory = SplitMemoryStore("/tmp/memory.json")
monitor = ShadowMonitor(memory=memory)
monitor.initialize(alert_text="Unknown binary in /tmp")

# Monitor enters ORIENT if alert is novel
print(monitor.state)  # ShadowState.ORIENTING

# Feed evidence — monitor transitions through posture states
action = monitor.process_evidence("check_hash", "Hash not in VirusTotal")
print(monitor.state)       # ShadowState.INVESTIGATING
print(action.action)       # "CONTINUE"

action = monitor.process_evidence("check_parent", "Parent: systemd")
print(monitor.state)       # ShadowState.COMMIT_READY
print(action.action)       # "COMMIT"
print(action.direction)    # "benign"

# Gate authority: use monitor.last_action.direction to steer the model
# gate_assists: "The controller concluded this is BENIGN. Issue verdict."
# gate_overrides: verdict = monitor.last_action.direction (model discarded)

# Close episode — updates memory for next run (the strange loop)
monitor.close_episode("benign", confidence=0.8)
```

## Project structure

```
morphsat/
├── morphsat/
│   ├── __init__.py           # Public API
│   ├── core.py               # FSA gate, TaskState/TaskEvent, classify_event
│   ├── token.py              # Token adjacency scoring (4-lane structure)
│   ├── pressure_gate.py      # v4 evidence-pressure gate
│   ├── commit_gate.py        # v6 bidirectional commit gate + split memory
│   ├── shadow_monitor.py     # v7 anticipatory posture controller
│   └── receipt.py            # Receipt wrapping with SHA256 content hash
├── tests/
│   ├── test_core.py          # 31 tests: FSA structure, transitions, receipts
│   ├── test_token.py         # 22 tests: lane scoring, temperature, masking
│   └── test_shadow_monitor.py # 22 tests: v7 posture predictions
├── docs/
│   ├── PRESSURE_GATE_SPEC.md
│   ├── COGNITIVE_ARCHITECTURE_TRANSLATION.md
│   ├── morphsat_technical_note.md      # 2-page technical note (v8.3 results)
│   └── morphsat_control_diagram.md     # Architecture diagrams + Soar mapping
├── receipts/
│   ├── v7_shadow_monitor/    # v7 benchmark receipts (single-seed + 3-seed)
│   └── morphsat_v83_early_verdict_guard/  # v8.3 benchmark receipt (60 runs, 20 scenarios x 3 conditions, 100% gate modes)
├── tools/
│   └── bench_gate_authority.py  # Gate authority benchmark harness
└── pyproject.toml
```

109/109 tests passing (Python 3.10).

## Caveats

- N=20 scenario benchmark with simulated tool responses
- Temperature=0 (deterministic) — no stochastic variance across seeds
- Qwen2.5-Coder-7B doing security triage — not its primary domain
- The shadow monitor is tested on one task type (alert triage)
- 100% gate_assists accuracy is an upper bound on this benchmark, not a claim about arbitrary inputs
- The evidence classifier is keyword-based, not learned
- This is a research testbed, not a production system

## Companion projects

| Project | Description |
|---------|-------------|
| [helix-substrate](https://github.com/echo313unfolding/helix-substrate) | Calibration-free neural network compression (HXQ). |
| [sentinel-hybrid-stack](https://github.com/echo313unfolding/sentinel-hybrid-stack) | Hybrid SSM-Transformer security monitoring pipeline. |
| [helix-codec](https://github.com/echo313unfolding/helix-codec) | Standalone C99 tensor codec library. |

## License

MIT — see [LICENSE](LICENSE).

<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1117,100:1a6b6b&height=100&section=footer" width="100%">
</div>
