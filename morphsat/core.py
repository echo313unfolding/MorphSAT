"""
MorphSAT Core -- Task-State FSA Enforcement Gate
=================================================

Hard FSA enforcement layer for task-state transitions in sequential decision
pipelines.  The gate sits between pipeline steps and enforces a finite-state
automaton on the task lifecycle.  Illegal transitions are blocked -- the
pipeline holds or aborts.

FSA: 5 states (IDLE -> PLANNING -> WRITING -> TESTING -> DONE),
     7 events, 23 illegal transitions.
Guardian layer adds 7 domain-specific vow blocks on top.

Usage::

    from morphsat import MorphSATGate, TaskEvent, classify_event

    gate = MorphSATGate()
    gate.step(TaskEvent.NEW_TASK)         # IDLE -> PLANNING
    event = classify_event(output, "generate")
    state, legal, action = gate.step(event)

Custom domains via JSON spec::

    spec = {
        "id": "review_pipeline",
        "states": ["DRAFT", "REVIEW", "APPROVED", "PUBLISHED"],
        "events": ["SUBMIT", "APPROVE", "REJECT", "PUBLISH"],
        "transitions": {
            "DRAFT.SUBMIT": "REVIEW",
            "REVIEW.APPROVE": "APPROVED",
            "REVIEW.REJECT": "DRAFT",
            "APPROVED.PUBLISH": "PUBLISHED",
        },
        "guardian_blocked": ["DRAFT.PUBLISH", "REVIEW.PUBLISH"],
    }
    gate = MorphSATGate.from_spec(spec)
    state, legal, action = gate.step(0)  # SUBMIT event

Ranked alternative proposals when blocked::

    state, legal, action = gate.step(event)
    if not legal:
        alternatives = gate.propose()  # top-3 legal transitions
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import numpy as np


# ---------------------------------------------------------------------------
# Task-State FSA
# ---------------------------------------------------------------------------

class TaskState(IntEnum):
    """States in the task lifecycle FSA."""
    IDLE = 0
    PLANNING = 1
    WRITING = 2
    TESTING = 3
    DONE = 4


class TaskEvent(IntEnum):
    """Events that drive FSA transitions."""
    NEW_TASK = 0       # user submits a request
    PLAN_COMPLETE = 1  # planner step finishes
    CODE_COMPLETE = 2  # coder step finishes
    TEST_PASS = 3      # verifier says PASS
    TEST_FAIL = 4      # verifier says FAIL
    RESET = 5          # user requests restart
    DEPLOY = 6         # user requests deployment


N_STATES = len(TaskState)
N_EVENTS = len(TaskEvent)

STATE_NAMES: List[str] = [s.name for s in TaskState]
EVENT_NAMES: List[str] = [e.name for e in TaskEvent]

# Transition table: T[state, event] -> next_state  (-1 = illegal)
TRANSITION_TABLE: np.ndarray = np.full((N_STATES, N_EVENTS), -1, dtype=np.int32)

# Legal transitions
TRANSITION_TABLE[TaskState.IDLE,     TaskEvent.NEW_TASK]      = TaskState.PLANNING
TRANSITION_TABLE[TaskState.PLANNING, TaskEvent.PLAN_COMPLETE] = TaskState.WRITING
TRANSITION_TABLE[TaskState.WRITING,  TaskEvent.CODE_COMPLETE] = TaskState.TESTING
TRANSITION_TABLE[TaskState.TESTING,  TaskEvent.TEST_PASS]     = TaskState.DONE
TRANSITION_TABLE[TaskState.TESTING,  TaskEvent.TEST_FAIL]     = TaskState.WRITING  # revision loop
TRANSITION_TABLE[TaskState.DONE,     TaskEvent.NEW_TASK]      = TaskState.PLANNING
TRANSITION_TABLE[TaskState.DONE,     TaskEvent.DEPLOY]        = TaskState.DONE     # legal deploy from DONE
# RESET from any state goes to IDLE
for _s in TaskState:
    TRANSITION_TABLE[_s, TaskEvent.RESET] = TaskState.IDLE

N_ILLEGAL: int = int((TRANSITION_TABLE == -1).sum())
N_LEGAL: int = int((TRANSITION_TABLE >= 0).sum())


# ---------------------------------------------------------------------------
# Guardian Vows (domain-specific policy constraints)
# ---------------------------------------------------------------------------

# Blocked regardless of FSA legality -- extra policy layer.
GUARDIAN_BLOCKED: Set[Tuple[int, int]] = {
    (TaskState.IDLE,     TaskEvent.DEPLOY),     # can't deploy from idle
    (TaskState.PLANNING, TaskEvent.DEPLOY),     # can't deploy from planning
    (TaskState.WRITING,  TaskEvent.DEPLOY),     # can't deploy while writing
    (TaskState.TESTING,  TaskEvent.DEPLOY),     # can't deploy while testing
    (TaskState.WRITING,  TaskEvent.NEW_TASK),   # can't start new task while writing
    (TaskState.TESTING,  TaskEvent.NEW_TASK),   # can't start new task while testing
    (TaskState.PLANNING, TaskEvent.NEW_TASK),   # can't start new task while planning
}


# ---------------------------------------------------------------------------
# Event Classification (grounding layer)
# ---------------------------------------------------------------------------

# Mapping from pipeline role names to FSA event classification
_ROLE_TO_EVENT_MAP = {
    "plan": TaskEvent.PLAN_COMPLETE,
    "generate": TaskEvent.CODE_COMPLETE,
    "parse": TaskEvent.PLAN_COMPLETE,      # parser produces a plan-like artifact
    "compile": TaskEvent.CODE_COMPLETE,    # compiler produces executable output
}


def classify_event(step_output: str, step_role: str) -> TaskEvent:
    """Classify a pipeline step output into a TaskEvent.

    This is the grounding layer -- maps continuous (text) output to a
    discrete FSA event.  Uses keyword patterns specific to each step role.

    Args:
        step_output: The text output from a pipeline step.
        step_role: The role of the step (``"plan"``, ``"generate"``,
            ``"verify"``, ``"deploy"``, ``"reset"``, ``"new_task"``).

    Returns:
        The detected :class:`TaskEvent`.
    """
    text = step_output.lower().strip()

    if step_role == "new_task":
        return TaskEvent.NEW_TASK

    if step_role == "plan":
        return TaskEvent.PLAN_COMPLETE

    if step_role == "generate":
        return TaskEvent.CODE_COMPLETE

    if step_role == "verify":
        if "pass" in text and "fail" not in text:
            return TaskEvent.TEST_PASS
        if "fail" in text:
            return TaskEvent.TEST_FAIL
        return TaskEvent.TEST_PASS  # ambiguous -> pass (conservative)

    if step_role == "deploy":
        return TaskEvent.DEPLOY

    if step_role == "reset":
        return TaskEvent.RESET

    # Non-FSA roles -- use lookup or fall back
    if step_role in _ROLE_TO_EVENT_MAP:
        return _ROLE_TO_EVENT_MAP[step_role]

    return TaskEvent.NEW_TASK  # fallback


# ---------------------------------------------------------------------------
# Candidate Transition (WO-08: ranked alternative proposals)
# ---------------------------------------------------------------------------

@dataclass
class CandidateTransition:
    """A legal transition proposed as an alternative when a step is blocked.

    Returned by :meth:`MorphSATGate.propose` -- ranked by cost (lower is
    better).  Ported from KRISPERcell.CandidateAction (echo-box/pssh).
    """
    event: int
    event_name: str
    next_state: int
    next_state_name: str
    cost: float


# ---------------------------------------------------------------------------
# Presets (WO-07: JSON-loadable constraint definitions)
# ---------------------------------------------------------------------------

_PRESETS: Dict[str, Dict[str, Any]] = {
    "task_lifecycle": {
        "id": "task_lifecycle_v1",
        "states": ["IDLE", "PLANNING", "WRITING", "TESTING", "DONE"],
        "events": [
            "NEW_TASK", "PLAN_COMPLETE", "CODE_COMPLETE",
            "TEST_PASS", "TEST_FAIL", "RESET", "DEPLOY",
        ],
        "transitions": {
            "IDLE.NEW_TASK": "PLANNING",
            "PLANNING.PLAN_COMPLETE": "WRITING",
            "WRITING.CODE_COMPLETE": "TESTING",
            "TESTING.TEST_PASS": "DONE",
            "TESTING.TEST_FAIL": "WRITING",
            "DONE.NEW_TASK": "PLANNING",
            "DONE.DEPLOY": "DONE",
        },
        "reset_event": "RESET",
        "reset_target": "IDLE",
        "guardian_blocked": [
            "IDLE.DEPLOY", "PLANNING.DEPLOY",
            "WRITING.DEPLOY", "TESTING.DEPLOY",
            "WRITING.NEW_TASK", "TESTING.NEW_TASK",
            "PLANNING.NEW_TASK",
        ],
    },
}


def _build_from_spec(spec: Dict[str, Any]) -> Tuple[
    np.ndarray, Set[Tuple[int, int]], List[str], List[str]
]:
    """Parse a JSON spec into (transition_table, guardian_set, state_names, event_names)."""
    states = spec["states"]
    events = spec["events"]
    n_s, n_e = len(states), len(events)
    state_idx = {name: i for i, name in enumerate(states)}
    event_idx = {name: i for i, name in enumerate(events)}

    T = np.full((n_s, n_e), -1, dtype=np.int32)

    for key, target in spec.get("transitions", {}).items():
        s_name, e_name = key.split(".", 1)
        T[state_idx[s_name], event_idx[e_name]] = state_idx[target]

    # Reset event: legal from all states
    if "reset_event" in spec and "reset_target" in spec:
        re = event_idx[spec["reset_event"]]
        rt = state_idx[spec["reset_target"]]
        for si in range(n_s):
            T[si, re] = rt

    guardian: Set[Tuple[int, int]] = set()
    for entry in spec.get("guardian_blocked", []):
        s_name, e_name = entry.split(".", 1)
        guardian.add((state_idx[s_name], event_idx[e_name]))

    return T, guardian, list(states), list(events)


# ---------------------------------------------------------------------------
# MorphSAT Gate
# ---------------------------------------------------------------------------

class MorphSATGate:
    """Hard FSA enforcement gate for task-state transitions.

    Sits between pipeline steps.  Each step output is classified into a
    :class:`TaskEvent` via :func:`classify_event`, then the gate enforces
    the FSA transition.  Illegal transitions are blocked -- the step output
    is suppressed and the state is held.

    Guardian vows add a second policy layer on top of FSA legality.

    Args:
        transition_table: Custom ``(N_STATES, N_EVENTS)`` int32 array.
            Defaults to :data:`TRANSITION_TABLE`.
        guardian_blocked: Set of ``(state, event)`` pairs to block.
            Defaults to :data:`GUARDIAN_BLOCKED`.
        enable_guardian: If ``False``, disables the guardian layer entirely.
    """

    def __init__(
        self,
        transition_table: Optional[np.ndarray] = None,
        guardian_blocked: Optional[Set[Tuple[int, int]]] = None,
        enable_guardian: bool = True,
    ):
        self.T = (
            transition_table if transition_table is not None
            else TRANSITION_TABLE
        ).copy()
        self.guardian_blocked: Set[Tuple[int, int]] = (
            (guardian_blocked if guardian_blocked is not None else GUARDIAN_BLOCKED)
            if enable_guardian
            else set()
        )
        self._state_names: List[str] = list(STATE_NAMES)
        self._event_names: List[str] = list(EVENT_NAMES)
        self._spec_id: Optional[str] = None
        self.state: int = 0  # IDLE
        self.history: List[dict] = []
        self.illegal_caught: int = 0
        self.guardian_caught: int = 0
        self.total_transitions: int = 0

    # ---------- constructors (WO-07) ----------

    @classmethod
    def from_spec(cls, spec: Dict[str, Any]) -> "MorphSATGate":
        """Build a gate from a JSON-compatible spec dict.

        Ported from GuardianCell.from_spec (echo-box/pssh).  Makes MorphSAT
        configurable for arbitrary domains without code changes.

        Args:
            spec: Dict with ``states``, ``events``, ``transitions``,
                and optionally ``guardian_blocked``, ``reset_event``,
                ``reset_target``.  See module docstring for format.

        Returns:
            A :class:`MorphSATGate` configured for the spec's domain.
        """
        T, guardian, s_names, e_names = _build_from_spec(spec)
        gate = cls(transition_table=T, guardian_blocked=guardian)
        gate._state_names = s_names
        gate._event_names = e_names
        gate._spec_id = spec.get("id")
        return gate

    @classmethod
    def from_preset(cls, name: str) -> "MorphSATGate":
        """Load a gate from a built-in preset.

        Ported from GuardianCell.from_preset (echo-box/pssh).

        Available presets:
            - ``"task_lifecycle"``: The default 5-state task lifecycle FSA.

        Args:
            name: Preset name.

        Returns:
            A :class:`MorphSATGate` configured for the preset's domain.

        Raises:
            ValueError: If the preset name is unknown.
        """
        if name not in _PRESETS:
            available = ", ".join(sorted(_PRESETS.keys()))
            raise ValueError(
                f"Unknown preset: {name!r}. Available: {available}"
            )
        return cls.from_spec(_PRESETS[name])

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "MorphSATGate":
        """Load a gate from a JSON file on disk.

        Args:
            path: Path to a JSON file containing a spec dict.

        Returns:
            A :class:`MorphSATGate` configured from the file.
        """
        p = Path(path)
        spec = json.loads(p.read_text())
        return cls.from_spec(spec)

    # ---------- core API ----------

    def _state_name(self, idx: int) -> str:
        """Human-readable name for a state index."""
        if 0 <= idx < len(self._state_names):
            return self._state_names[idx]
        return str(idx)

    def _event_name(self, idx: int) -> str:
        """Human-readable name for an event index."""
        if 0 <= idx < len(self._event_names):
            return self._event_names[idx]
        return str(idx)

    def step(self, event: int) -> Tuple[int, bool, str]:
        """Attempt a state transition.

        Args:
            event: Event index (or :class:`TaskEvent` enum value).

        Returns:
            A 3-tuple ``(new_state, was_legal, action_taken)`` where
            *action_taken* is one of ``"ALLOWED"``, ``"FSA_BLOCKED"``,
            or ``"GUARDIAN_BLOCKED"``.
        """
        self.total_transitions += 1
        old_state = int(self.state)
        ev = int(event)

        # Guardian check first (policy layer above FSA)
        if (old_state, ev) in self.guardian_blocked:
            self.guardian_caught += 1
            self.history.append({
                "from": self._state_name(old_state),
                "event": self._event_name(ev),
                "action": "GUARDIAN_BLOCKED",
                "to": self._state_name(old_state),
            })
            return self.state, False, "GUARDIAN_BLOCKED"

        # FSA check
        next_state = int(self.T[old_state, ev])
        if next_state == -1:
            self.illegal_caught += 1
            self.history.append({
                "from": self._state_name(old_state),
                "event": self._event_name(ev),
                "action": "FSA_BLOCKED",
                "to": self._state_name(old_state),
            })
            return self.state, False, "FSA_BLOCKED"

        # Legal transition
        self.state = next_state
        self.history.append({
            "from": self._state_name(old_state),
            "event": self._event_name(ev),
            "action": "ALLOWED",
            "to": self._state_name(next_state),
        })
        return self.state, True, "ALLOWED"

    # ---------- proposal API (WO-08) ----------

    def propose(self, max_candidates: int = 3) -> List[CandidateTransition]:
        """Propose legal transitions from the current state, ranked by cost.

        Ported from KRISPERcell.propose (echo-box/pssh).  Turns MorphSAT
        from a gate ("no, illegal") into a constrained steering system
        ("no, illegal -- here are your legal options").

        Cost heuristic: distance from the terminal state (highest index).
        Lower cost = closer to completion.

        Args:
            max_candidates: Maximum number of alternatives to return.

        Returns:
            List of :class:`CandidateTransition` sorted by cost ascending.
        """
        n_events = self.T.shape[1]
        terminal = self.T.shape[0] - 1  # highest state = terminal
        cur = int(self.state)
        candidates: List[CandidateTransition] = []

        for ev in range(n_events):
            next_val = int(self.T[cur, ev])
            if next_val == -1:
                continue
            if (cur, ev) in self.guardian_blocked:
                continue
            cost = float(terminal - next_val)
            candidates.append(CandidateTransition(
                event=ev,
                event_name=self._event_name(ev),
                next_state=next_val,
                next_state_name=self._state_name(next_val),
                cost=cost,
            ))

        candidates.sort(key=lambda c: c.cost)
        return candidates[:max_candidates]

    def step_or_propose(
        self, event: int, max_candidates: int = 3,
    ) -> Tuple[int, bool, str, List[CandidateTransition]]:
        """Step if legal; if blocked, also return ranked alternatives.

        Convenience method combining :meth:`step` and :meth:`propose`.

        Returns:
            A 4-tuple ``(state, legal, action, alternatives)`` where
            *alternatives* is empty if the step was legal.
        """
        state, legal, action = self.step(event)
        if legal:
            return state, legal, action, []
        return state, legal, action, self.propose(max_candidates)

    # ---------- state management ----------

    def reset(self) -> None:
        """Reset gate to initial state (index 0)."""
        self.state = 0

    def to_receipt(self) -> dict:
        """Export gate state and history as a receipt-compatible dict."""
        receipt = {
            "final_state": self._state_name(int(self.state)),
            "total_transitions": self.total_transitions,
            "illegal_caught": self.illegal_caught,
            "guardian_caught": self.guardian_caught,
            "history": self.history,
        }
        if self._spec_id is not None:
            receipt["spec_id"] = self._spec_id
        return receipt
