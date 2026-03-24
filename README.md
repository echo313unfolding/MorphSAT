# MorphSAT

Finite-state constraint enforcement for sequential decision systems.

MorphSAT provides two primitives:

1. **FSA Gate** (`morphsat.core`) -- A hard finite-state automaton that enforces legal transitions in a task lifecycle. Illegal transitions are blocked. An optional guardian policy layer adds domain-specific veto rules on top.

2. **Token Adjacency Scoring** (`morphsat.token`) -- Soft constraint scoring over token sequences using lane-based adjacency rules and cosine-annealed temperature scheduling.

## Install

```bash
pip install morphsat            # numpy only
pip install morphsat[torch]     # optional torch support
pip install morphsat[dev]       # pytest for development
```

## Quick Start -- FSA Gate

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

## Quick Start -- Token Adjacency

```python
from morphsat import MorphSATScorer, score_token_sequence

# Score a token sequence against 4-lane adjacency rules
tokens = ["cat", "runs", "fast", "through", "door", "opens", "wide", "into"]
indices = [0, 1, 2, 3, 4, 5, 6, 7]

results = score_token_sequence(tokens, indices)
for r in results:
    print(f"  pos={r['pos']} lane={r['lane_name']} score={r['score']:.3f}")
```

The 4-lane structure (ENTITY / ACTION / QUALITY / RELATION) enforces natural
sequential flow. Non-preferred transitions receive a soft penalty scaled by
cosine-annealed temperature.

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

## Receipt Serialization

```python
from morphsat.receipt import wrap_receipt
import json

receipt = wrap_receipt(
    tag="my-experiment",
    payload={"result": 42},
)
print(json.dumps(receipt, indent=2))
```

## Related

- [helix-substrate](https://github.com/echo313unfolding/helix-substrate) -- Compressed-native execution substrate where MorphSAT was first deployed as a task-state enforcement layer.

## License

MIT
