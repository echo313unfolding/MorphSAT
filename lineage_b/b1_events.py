"""B1-side learning-phase provenance (prereg v1.5.1 §5). EVALUATOR side.

Only the logging policy executes an action during learning. Each step has one
behavior ControlDecisionEvent (arm "G0-logging", from the frozen harness) and
one BehaviorDecisionRecord that keeps G0's own controller proposal separate
from mu's randomized logged action."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import List

from lineage_b.events import _hash
from lineage_b.logging_policy import LoggingPolicy

BEHAVIOR_ARM = "G0-logging"


@dataclass(frozen=True)
class BehaviorDecisionRecord:
    deployment: str
    episode: int
    t: int
    behavior_arm: str
    controller_proposal: str          # G0 controller at theta0
    logged_action: str                # mu's choice (equals the proposal when not randomized)
    propensity: float
    randomized: bool
    authority_path: str
    final_action: str                 # executed action
    behavior_event_hash: str          # canonical hash of the behavior ControlDecisionEvent
    canonical_hash: str = ""

    def __post_init__(self):
        object.__setattr__(self, "canonical_hash", _hash(asdict(self)))


class RecordingPolicy(LoggingPolicy):
    """The frozen logging policy, unchanged in behaviour; it additionally records
    (controller proposal, chosen action, propensity, randomized) per call."""

    def __init__(self, rng):
        super().__init__(rng)
        self.calls: List[tuple] = []

    def choose(self, proposal: str, randomizable: bool):
        out = super().choose(proposal, randomizable)
        self.calls.append((proposal,) + tuple(out))
        return out


def behavior_records(dep_id: str, events, calls) -> List[BehaviorDecisionRecord]:
    """Align harness events (one per step, in order) with the policy calls."""
    if len(events) != len(calls):
        raise RuntimeError("behavior events and policy calls are misaligned")
    out = []
    for e, (prop, act, p, rnd) in zip(events, calls):
        if e.authority_path == "arbitration" and e.final_action != act:
            raise RuntimeError("executed action differs from the logged action")
        out.append(BehaviorDecisionRecord(dep_id, e.episode, e.t, BEHAVIOR_ARM, prop, act, p, rnd,
                                          e.authority_path, e.final_action, e.canonical_hash))
    return out
