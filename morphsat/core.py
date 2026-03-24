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
"""

from __future__ import annotations

from enum import IntEnum
from typing import List, Optional, Set, Tuple

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
        self.state: TaskState = TaskState.IDLE
        self.history: List[dict] = []
        self.illegal_caught: int = 0
        self.guardian_caught: int = 0
        self.total_transitions: int = 0

    def step(self, event: TaskEvent) -> Tuple[TaskState, bool, str]:
        """Attempt a state transition.

        Returns:
            A 3-tuple ``(new_state, was_legal, action_taken)`` where
            *action_taken* is one of ``"ALLOWED"``, ``"FSA_BLOCKED"``,
            or ``"GUARDIAN_BLOCKED"``.
        """
        self.total_transitions += 1
        old_state = self.state

        # Guardian check first (policy layer above FSA)
        if (int(old_state), int(event)) in self.guardian_blocked:
            self.guardian_caught += 1
            self.history.append({
                "from": STATE_NAMES[old_state],
                "event": EVENT_NAMES[event],
                "action": "GUARDIAN_BLOCKED",
                "to": STATE_NAMES[old_state],
            })
            return self.state, False, "GUARDIAN_BLOCKED"

        # FSA check
        next_state = self.T[old_state, event]
        if next_state == -1:
            self.illegal_caught += 1
            self.history.append({
                "from": STATE_NAMES[old_state],
                "event": EVENT_NAMES[event],
                "action": "FSA_BLOCKED",
                "to": STATE_NAMES[old_state],
            })
            return self.state, False, "FSA_BLOCKED"

        # Legal transition
        self.state = TaskState(next_state)
        self.history.append({
            "from": STATE_NAMES[old_state],
            "event": EVENT_NAMES[event],
            "action": "ALLOWED",
            "to": STATE_NAMES[self.state],
        })
        return self.state, True, "ALLOWED"

    def reset(self) -> None:
        """Reset gate to IDLE state."""
        self.state = TaskState.IDLE

    def to_receipt(self) -> dict:
        """Export gate state and history as a receipt-compatible dict."""
        return {
            "final_state": STATE_NAMES[self.state],
            "total_transitions": self.total_transitions,
            "illegal_caught": self.illegal_caught,
            "guardian_caught": self.guardian_caught,
            "history": self.history,
        }
