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
from lineage_b.params import ACTIONS, EPSILON

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


class ProvenanceError(RuntimeError):
    pass


def behavior_records(dep_id: str, events, calls, epsilon: float = EPSILON) -> List[BehaviorDecisionRecord]:
    """Align harness events (one per step, in order) with the policy calls
    (v1.5.2 §1): rejects any disagreement in arm, (episode, t) ordering,
    propensity, randomized flag, proposal or authority/final-action semantics."""
    events = list(events)
    if len(events) != len(calls):
        raise ProvenanceError("behavior events and policy calls differ in number")
    out, prev = [], None
    for e, (prop, act, p, rnd) in zip(events, calls):
        if e.arm != BEHAVIOR_ARM:
            raise ProvenanceError(f"behavior event arm {e.arm!r} != {BEHAVIOR_ARM!r}")
        key = (e.episode, e.t)
        if prev is not None and not (key == (prev[0], prev[1] + 1) or (key[0] == prev[0] + 1 and key[1] == 0)):
            raise ProvenanceError(f"behavior events out of order at {key}")
        prev = key
        if (p, rnd) != (e.propensity, e.randomized):
            raise ProvenanceError(f"propensity/randomized disagree at {key}")
        if e.authority_path == "arbitration":
            if not (e.final_action == act == e.proposal):
                raise ProvenanceError(f"logged action is not the executed arbitration action at {key}")
            expect = (1 - epsilon) if act == prop else epsilon / (len(ACTIONS) - 1)
            if not rnd or abs(p - expect) > 1e-12:
                raise ProvenanceError(f"propensity inconsistent with proposal/logged action at {key}")
        else:
            if rnd or p != 1.0 or e.proposal is not None or act != prop:
                raise ProvenanceError(f"non-arbitration step treated as randomized at {key}")
        out.append(BehaviorDecisionRecord(dep_id, e.episode, e.t, BEHAVIOR_ARM, prop, act, p, rnd,
                                          e.authority_path, e.final_action, e.canonical_hash))
    return out


def verify_provenance(behavior, events_by_key, feedback_items, payload_of) -> dict:
    """v1.5.2 §1 independent check: events <-> BehaviorDecisionRecords <->
    learner FeedbackRecord.decision_ref."""
    problems = []
    by_key = {}
    for b in behavior:
        k = (b.episode, b.t)
        if k in by_key:
            problems.append(("duplicate_record", k))
        by_key[k] = b
        if b.canonical_hash != _hash(asdict(b)):
            problems.append(("record_hash", k))
    if set(by_key) != set(events_by_key):
        problems.append(("record_event_keys_differ", len(by_key), len(events_by_key)))
    hashes = set()
    for k, e in events_by_key.items():
        hashes.add(e.canonical_hash)
        b = by_key.get(k)
        if e.arm != BEHAVIOR_ARM:
            problems.append(("event_arm", k, e.arm))
        if b is None:
            continue
        if not (b.behavior_arm == BEHAVIOR_ARM and (b.episode, b.t) == (e.episode, e.t)
                and b.behavior_event_hash == e.canonical_hash and b.propensity == e.propensity
                and b.randomized == e.randomized and b.authority_path == e.authority_path
                and b.final_action == e.final_action):
            problems.append(("record_event_mismatch", k))
        if e.authority_path == "arbitration":
            if b.logged_action != e.final_action:
                problems.append(("logged_vs_final", k))
            away = b.controller_proposal != b.logged_action
            if away != (abs(b.propensity - EPSILON / (len(ACTIONS) - 1)) < 1e-12):
                problems.append(("proposal_vs_logged", k))
        elif b.randomized or b.propensity != 1.0:
            problems.append(("nonarbitration_randomized", k))
    n_fb = 0
    for f in feedback_items:
        n_fb += 1
        dk = tuple(payload_of(tuple(f.receipt_key))["decision_key"])
        e = events_by_key.get(dk)
        if e is None or f.decision_ref != e.canonical_hash or f.decision_ref not in hashes:
            problems.append(("feedback_link", f.sensor_id, f.seq, dk))
    return {"pass": not problems, "problems": problems[:20], "n_problems": len(problems),
            "steps": len(events_by_key), "feedback_checked": n_fb}
