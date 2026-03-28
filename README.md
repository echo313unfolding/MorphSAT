<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://capsule-render.vercel.app/api?type=waving&color=0:0d1117,100:1a6b6b&height=200&section=header&text=MorphSAT&fontSize=42&fontColor=58a6ff&animation=fadeIn&fontAlignY=35&desc=Morphogenetic%20constraint%20satisfaction&descSize=16&descColor=8b949e&descAlignY=55">
  <source media="(prefers-color-scheme: light)" srcset="https://capsule-render.vercel.app/api?type=waving&color=0:f0f6fc,100:2ababa&height=200&section=header&text=MorphSAT&fontSize=42&fontColor=1f2328&animation=fadeIn&fontAlignY=35&desc=Morphogenetic%20constraint%20satisfaction&descSize=16&descColor=656d76&descAlignY=55">
  <img alt="MorphSAT" src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1117,100:1a6b6b&height=200&section=header&text=MorphSAT&fontSize=42&fontColor=58a6ff&animation=fadeIn&fontAlignY=35&desc=Morphogenetic%20constraint%20satisfaction&descSize=16&descColor=8b949e&descAlignY=55">
</picture>

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://python.org)
[![License](https://img.shields.io/badge/license-Echo%20Labs-green)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-53%20passed-brightgreen)]()

**Finite-state constraint enforcement for sequential decision systems.**
**Hard FSA gates + soft token adjacency scoring. NumPy only. No GPU required.**

</div>

# MorphSAT

MorphSAT provides two constraint primitives for sequential decision pipelines:

1. **FSA Gate** (`morphsat.core`) -- A hard finite-state automaton that enforces legal transitions in a task lifecycle. Illegal transitions are blocked. An optional guardian policy layer adds domain-specific veto rules on top.

2. **Token Adjacency Scoring** (`morphsat.token`) -- Soft constraint scoring over token sequences using a 4-lane semantic structure (ENTITY / ACTION / QUALITY / RELATION) with cosine-annealed temperature scheduling.

The FSA gate was originally built as the task-state enforcement layer for compressed AI inference pipelines. The token scorer applies lane-based adjacency rules as soft penalties, allowing preferred sequential flow without hard masking.

## Install

```bash
pip install morphsat            # numpy only
pip install morphsat[torch]     # optional torch support
pip install morphsat[dev]       # pytest for development
```

## Quick start -- FSA Gate

```python
from morphsat import MorphSATGate, TaskState, TaskEvent, classify_event

gate = MorphSATGate()
assert gate.state == TaskState.IDLE

# Legal transition
state, legal, action = gate.step(TaskEvent.NEW_TASK)
assert state == TaskState.PLANNING
assert legal is True

# Illegal transition (can't deploy from PLANNING)
state, legal, action = gate.step(TaskEvent.DEPLOY)
assert legal is False
assert action == "GUARDIAN_BLOCKED"

# Export audit trail
receipt = gate.to_receipt()
print(receipt["history"])
```

### FSA structure

5 states, 7 events, two enforcement layers:

```
IDLE --> PLANNING --> WRITING --> TESTING --> DONE
  ^         |           ^           |          |
  |       RESET       TEST_FAIL    |        DEPLOY (legal)
  +------ RESET --------+-----RESET---------RESET
                                             NEW_TASK (loops back to PLANNING)
```

**FSA layer:** Transition table with 12 legal and 23 illegal transitions. Illegal transitions return `FSA_BLOCKED` and hold the current state.

**Guardian layer:** 7 domain-specific veto rules that block transitions even if the FSA allows them. Examples: no deploy from any state except DONE, no new task while writing or testing. Returns `GUARDIAN_BLOCKED`.

### Event classification

The grounding layer maps pipeline step outputs to discrete FSA events:

```python
event = classify_event(step_output="All tests pass", step_role="verify")
# Returns TaskEvent.TEST_PASS

event = classify_event(step_output="2 tests fail", step_role="verify")
# Returns TaskEvent.TEST_FAIL
```

Supported roles: `new_task`, `plan`, `generate`, `verify`, `deploy`, `reset`, `parse`, `compile`.

## Quick start -- Token Adjacency

```python
from morphsat import MorphSATScorer, score_token_sequence

# Score a token sequence against 4-lane adjacency rules
tokens = ["cat", "runs", "fast", "through", "door", "opens", "wide", "into"]
indices = [0, 1, 2, 3, 4, 5, 6, 7]

results = score_token_sequence(tokens, indices)
for r in results:
    print(f"  pos={r['pos']} lane={r['lane_name']} score={r['score']:.3f}")
```

### 4-lane semantic structure

Tokens are assigned to lanes by position (`pos % 4`):

| Lane | Name | Preferred next |
|------|------|---------------|
| 0 | ENTITY | ACTION, QUALITY |
| 1 | ACTION | QUALITY, RELATION, ENTITY |
| 2 | QUALITY | RELATION, ENTITY, ACTION |
| 3 | RELATION | ENTITY, ACTION |

Non-preferred transitions receive a soft penalty scaled by cosine-annealed temperature. The default adjacency table is engineered so that all sequential positions are preferred -- penalties only appear with non-sequential or custom lane assignments.

### Temperature schedule

The scorer uses reverse cosine annealing: starts cold (`Tmin`), warms to `T0` over `steps_anneal` steps. At cold temperatures, non-preferred transitions receive larger penalties.

```python
scorer = MorphSATScorer(sat_T0=1.0, sat_Tmin=0.5, steps_anneal=200, soft_lambda=4.0)
```

## Custom FSA

Supply your own transition table and guardian blocks:

```python
import numpy as np
from morphsat import MorphSATGate

# 3-state, 2-event custom FSA
T = np.full((3, 2), -1, dtype=np.int32)
T[0, 0] = 1   # state 0 + event 0 -> state 1
T[1, 1] = 2   # state 1 + event 1 -> state 2

gate = MorphSATGate(transition_table=T, enable_guardian=False)
```

## Custom morph tables

Load adjacency rules from JSON:

```python
from morphsat import load_morph_table, MorphSATScorer

table = load_morph_table("my_rules.json")
scorer = MorphSATScorer(morph_table=table)
```

Supported modes: `lane` (4-lane structure), `simple` (prev-token lookup), `prev+pos` (prev-token + position pair).

## Receipt serialization

Every gate produces a receipt for audit:

```python
from morphsat.receipt import wrap_receipt
import json

receipt = wrap_receipt(
    tag="my-experiment",
    payload={"result": 42},
)
print(json.dumps(receipt, indent=2))
# Includes: tag, timestamp, sha256 of payload, payload
```

## Project structure

```
morphsat/
+-- morphsat/
|   +-- __init__.py       # Public API
|   +-- core.py           # FSA gate, TaskState/TaskEvent enums, classify_event
|   +-- token.py          # MorphSATScorer, lane adjacency, score_token_sequence
|   +-- receipt.py        # Receipt wrapping with SHA256 content hash
+-- tests/
|   +-- test_core.py      # 31 tests: FSA structure, legal/illegal transitions, receipts
|   +-- test_token.py     # 22 tests: lane structure, scoring, temperature, masking
+-- tools/
|   +-- bridge_mamba_test.py  # MorphSAT + Mamba-130m compressed inference bridge test
+-- pyproject.toml        # Package config, numpy>=1.24, optional torch/dev deps
```

53/53 tests passing (Python 3.10).

## Companion projects

| Project | Description |
|---------|-------------|
| [helix-substrate](https://github.com/echo313unfolding/helix-substrate) | Calibration-free neural network compression. MorphSAT was first deployed as its task-state enforcement layer. |
| [helix-online-kv](https://github.com/echo313unfolding/helix-online-kv) | Online KV cache compression + compressed-domain attention using the same VQ codec. |
| [echo_runtime](https://github.com/echo313unfolding/echo_runtime) | Unified compressed AI runtime. HelixLinear + CompressedKVCache + CDC-03 in one forward pass. |
| [FGIP](https://github.com/echo313unfolding/FGIP) | Forensic graph intelligence platform. Lobbying networks, ownership graphs, adversarial-tested investment theses. |

## License

MIT -- see [LICENSE](LICENSE).

<div align="center">
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0d1117,100:1a6b6b&height=100&section=footer" width="100%">
</div>
