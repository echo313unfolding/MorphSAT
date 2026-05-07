<div align="center">

<img alt="MorphSAT" src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1117,100:1a6b6b&height=200&section=header&text=MorphSAT&fontSize=42&fontColor=58a6ff&animation=fadeIn&fontAlignY=35&desc=Constraint-control%20testbed%20for%20local%20LLM%20agents&descSize=16&descColor=8b949e&descAlignY=55" width="100%">

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-109%20passed-brightgreen)]()
[![Checkpoint](https://img.shields.io/badge/checkpoint-v7--shadow--monitor-blue)]()

**Evidence-based commit control, novelty response, and auditable execution traces.**

</div>

## What is this?

MorphSAT is a testbed for studying **when a local LLM agent should stop gathering evidence and commit to an action.**

An LLM agent with tool access can loop indefinitely — calling tools, reading results, calling more tools — without ever deciding. MorphSAT layers constraint-control mechanisms around the agent's loop and measures their effect on accuracy, tool usage, and commit timing.

The current checkpoint (v7) compares an **evidence-pressure controller** against an **anticipatory posture controller** that treats novelty as an orienting state rather than a scalar penalty.

> **For cognitive architecture researchers:** See [`docs/COGNITIVE_ARCHITECTURE_TRANSLATION.md`](docs/COGNITIVE_ARCHITECTURE_TRANSLATION.md) for a term mapping between MorphSAT internal names and concepts from Soar, ACT-R, and active inference.

## The proof chain

Seven versions tested on a 20-scenario security alert triage benchmark:

| Version | Mechanism | Accuracy | Key finding |
|---|---|---|---|
| v1 | Static FSA constraints | 55% | 0 useful interventions — too weak |
| v2 | Fixed tool-call counter | 67.5% | Any pressure helps |
| v3 | Adaptive budget (2/3/5) | 55–67.5% | Ceiling irrelevant, floor matters |
| **v4** | **Evidence-pressure gate** | **65%** | Best escalation (77.8%), best pre-v7 |
| v5 | + pattern memory | 62.5% | Mechanics work, accuracy fails — learned threats without tolerance |
| v6 | + bidirectional pressure | 55% | Novelty-as-penalty is the wrong abstraction |
| **v7** | **Anticipatory posture control** | **70%** | Best accuracy, benign recovery 78.6% (was 35.7%) |

## v7 result

|  | Evidence-pressure (v4) | Anticipatory posture (v7) |
|---|---|---|
| Overall accuracy | 62.5% | **70.0%** |
| Tool-loop rate | 35.0% | **25.0%** |
| Avg turns to decision | 5.4 | **4.8** |
| Benign accuracy | 35.7% | **78.6%** |
| Suspicious accuracy | **75.0%** | 62.5% |
| Escalation accuracy | **77.8%** | 66.7% |

v7 fixes the tolerance problem (benign +42.9pp) at the cost of suspicious/escalate regression. The tradeoff is real and not yet resolved.

**Key insight:** Novelty handling is a posture problem, not a threshold problem. When novelty was treated as a penalty (raise the commit threshold), the agent over-investigated benign scenarios and never learned tolerance. When novelty was treated as an orienting state (enter protective posture, gather bounded evidence, relax on safe evidence), benign recovery improved dramatically.

## Architecture

```
Layer 1: FSA lifecycle gate
         Legal task-state transitions. Blocks impossible sequences.

Layer 2: Evidence-pressure gate (v4)
         Sensor-driven commit timing. Se complexity threshold,
         evidence quality, sidecar confidence, urgency decay.
         Fires irreversibly when pressure crosses threshold.

Layer 3: Anticipatory posture controller (v7)
         Hidden state machine wrapping the agent's loop.
         Novelty → ORIENT → bounded investigation → decide.
         Safe evidence decays protective posture (tolerance).
         Multi-axis pressure → escalation signal.

Layer 4: Dual-store memory
         Threat patterns and tolerance patterns stored separately.
         Familiarity with known configurations speeds future decisions.

Layer 5: Episodic traces
         Turn-by-turn audit records of state, evidence, posture,
         and outcomes. Every decision is reproducible.
```

### Shadow monitor states

```
NORMAL ──→ ORIENTING ──→ SAFE_DISTANCE ──→ NORMAL (safe recovery)
              │
              └──→ INVESTIGATING ──→ COMMIT_READY (clear evidence)
                        │            ESCALATE_READY (high threat)
                        │            ABSTAIN_READY (contradictory)
                        └──→ SWARM_CALL (multi-axis pressure)
```

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

### Evidence-pressure gate

```python
from morphsat import CommitGate, SplitMemoryStore

memory = SplitMemoryStore("/tmp/memory.json")
gate = CommitGate(memory=memory)
gate.initialize(alert_text="Suspicious process spawned by cron")

# Feed tool results
action = gate.process_evidence("check_process", "PID 1234: /usr/bin/curl ...")
# action.action is "CONTINUE", "COMMIT", or "ABSTAIN"
# action.direction is "escalate", "benign", or None
```

### Shadow monitor (v7)

```python
from morphsat import ShadowMonitor, SplitMemoryStore

memory = SplitMemoryStore("/tmp/memory.json")
monitor = ShadowMonitor(memory=memory)
monitor.initialize(alert_text="Unknown binary in /tmp")

# Monitor enters ORIENT if alert is novel
print(monitor.state)  # ShadowState.ORIENTING

# Feed evidence — monitor transitions through states
action = monitor.process_evidence("check_hash", "Hash not in VirusTotal")
print(monitor.state)       # ShadowState.INVESTIGATING
print(action.action)       # "CONTINUE"

action = monitor.process_evidence("check_parent", "Parent: systemd")
print(monitor.state)       # ShadowState.COMMIT_READY
print(action.action)       # "COMMIT"
print(action.direction)    # "benign"

# Close episode — updates memory for next run
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
│   └── COGNITIVE_ARCHITECTURE_TRANSLATION.md
├── receipts/
│   └── v7_shadow_monitor/    # Benchmark receipts (single-seed + 3-seed)
└── pyproject.toml
```

109/109 tests passing (Python 3.10).

## Caveats

- N=20 scenario benchmark with simulated tool responses
- Temperature=0 (deterministic) — no stochastic variance across seeds
- Qwen2.5-Coder-3B doing security triage — small model, not its strongest domain
- The shadow monitor is tested on one task type (alert triage)
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
