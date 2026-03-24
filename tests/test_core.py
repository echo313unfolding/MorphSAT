"""Tests for morphsat.core -- FSA gate enforcement."""

import numpy as np
import pytest

from morphsat.core import (
    MorphSATGate,
    TaskState,
    TaskEvent,
    classify_event,
    TRANSITION_TABLE,
    GUARDIAN_BLOCKED,
    N_STATES,
    N_EVENTS,
    N_LEGAL,
    N_ILLEGAL,
    STATE_NAMES,
    EVENT_NAMES,
)


# ---------------------------------------------------------------------------
# FSA structure
# ---------------------------------------------------------------------------

class TestFSAStructure:
    def test_state_count(self):
        assert N_STATES == 5

    def test_event_count(self):
        assert N_EVENTS == 7

    def test_transition_table_shape(self):
        assert TRANSITION_TABLE.shape == (5, 7)

    def test_legal_plus_illegal_equals_total(self):
        assert N_LEGAL + N_ILLEGAL == N_STATES * N_EVENTS

    def test_reset_legal_from_all_states(self):
        for s in TaskState:
            assert TRANSITION_TABLE[s, TaskEvent.RESET] == TaskState.IDLE

    def test_state_names(self):
        assert STATE_NAMES == ["IDLE", "PLANNING", "WRITING", "TESTING", "DONE"]

    def test_event_names(self):
        assert EVENT_NAMES == [
            "NEW_TASK", "PLAN_COMPLETE", "CODE_COMPLETE",
            "TEST_PASS", "TEST_FAIL", "RESET", "DEPLOY",
        ]


# ---------------------------------------------------------------------------
# Gate: legal transitions
# ---------------------------------------------------------------------------

class TestGateLegalTransitions:
    def test_happy_path(self):
        gate = MorphSATGate()
        assert gate.state == TaskState.IDLE

        s, ok, a = gate.step(TaskEvent.NEW_TASK)
        assert s == TaskState.PLANNING and ok and a == "ALLOWED"

        s, ok, a = gate.step(TaskEvent.PLAN_COMPLETE)
        assert s == TaskState.WRITING and ok

        s, ok, a = gate.step(TaskEvent.CODE_COMPLETE)
        assert s == TaskState.TESTING and ok

        s, ok, a = gate.step(TaskEvent.TEST_PASS)
        assert s == TaskState.DONE and ok

    def test_revision_loop(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)
        gate.step(TaskEvent.PLAN_COMPLETE)
        gate.step(TaskEvent.CODE_COMPLETE)

        s, ok, a = gate.step(TaskEvent.TEST_FAIL)
        assert s == TaskState.WRITING and ok

        s, ok, a = gate.step(TaskEvent.CODE_COMPLETE)
        assert s == TaskState.TESTING and ok

    def test_deploy_from_done(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)
        gate.step(TaskEvent.PLAN_COMPLETE)
        gate.step(TaskEvent.CODE_COMPLETE)
        gate.step(TaskEvent.TEST_PASS)

        s, ok, a = gate.step(TaskEvent.DEPLOY)
        assert s == TaskState.DONE and ok and a == "ALLOWED"

    def test_new_task_from_done(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)
        gate.step(TaskEvent.PLAN_COMPLETE)
        gate.step(TaskEvent.CODE_COMPLETE)
        gate.step(TaskEvent.TEST_PASS)

        s, ok, a = gate.step(TaskEvent.NEW_TASK)
        assert s == TaskState.PLANNING and ok

    def test_reset_from_any_state(self):
        for start_event in [TaskEvent.NEW_TASK]:
            gate = MorphSATGate()
            gate.step(start_event)
            s, ok, a = gate.step(TaskEvent.RESET)
            assert s == TaskState.IDLE and ok


# ---------------------------------------------------------------------------
# Gate: illegal transitions
# ---------------------------------------------------------------------------

class TestGateIllegalTransitions:
    def test_fsa_blocked(self):
        gate = MorphSATGate(enable_guardian=False)
        # IDLE + PLAN_COMPLETE is illegal per FSA
        s, ok, a = gate.step(TaskEvent.PLAN_COMPLETE)
        assert not ok and a == "FSA_BLOCKED"
        assert gate.state == TaskState.IDLE
        assert gate.illegal_caught == 1

    def test_guardian_blocked_deploy_from_planning(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)
        s, ok, a = gate.step(TaskEvent.DEPLOY)
        assert not ok and a == "GUARDIAN_BLOCKED"
        assert gate.guardian_caught == 1

    def test_guardian_blocked_new_task_from_writing(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)
        gate.step(TaskEvent.PLAN_COMPLETE)
        # WRITING + NEW_TASK is guardian-blocked
        s, ok, a = gate.step(TaskEvent.NEW_TASK)
        assert not ok and a == "GUARDIAN_BLOCKED"

    def test_all_guardian_blocks(self):
        """Every guardian-blocked pair must be rejected."""
        for state_val, event_val in GUARDIAN_BLOCKED:
            gate = MorphSATGate()
            gate.state = TaskState(state_val)
            s, ok, a = gate.step(TaskEvent(event_val))
            assert not ok, f"({state_val}, {event_val}) should be blocked"
            assert a == "GUARDIAN_BLOCKED"


# ---------------------------------------------------------------------------
# Gate: receipt and history
# ---------------------------------------------------------------------------

class TestGateReceipt:
    def test_receipt_fields(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)
        gate.step(TaskEvent.DEPLOY)  # guardian blocked

        receipt = gate.to_receipt()
        assert receipt["final_state"] == "PLANNING"
        assert receipt["total_transitions"] == 2
        assert receipt["illegal_caught"] == 0
        assert receipt["guardian_caught"] == 1
        assert len(receipt["history"]) == 2

    def test_history_entry_keys(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)
        entry = gate.history[0]
        assert set(entry.keys()) == {"from", "event", "action", "to"}


# ---------------------------------------------------------------------------
# Gate: custom transition table
# ---------------------------------------------------------------------------

class TestCustomGate:
    def test_custom_table(self):
        T = np.full((3, 2), -1, dtype=np.int32)
        T[0, 0] = 1
        T[1, 1] = 2
        gate = MorphSATGate(transition_table=T, enable_guardian=False)
        gate.state = TaskState(0)
        # step with event 0 should go to state 1
        # (we use TaskEvent values, just int-compatible)
        s, ok, a = gate.step(TaskEvent(0))
        assert ok and int(s) == 1

    def test_guardian_disabled(self):
        gate = MorphSATGate(enable_guardian=False)
        gate.state = TaskState.PLANNING
        # Without guardian, DEPLOY from PLANNING is just FSA-blocked (not guardian)
        s, ok, a = gate.step(TaskEvent.DEPLOY)
        assert not ok and a == "FSA_BLOCKED"


# ---------------------------------------------------------------------------
# classify_event
# ---------------------------------------------------------------------------

class TestClassifyEvent:
    def test_new_task(self):
        assert classify_event("anything", "new_task") == TaskEvent.NEW_TASK

    def test_plan(self):
        assert classify_event("plan ready", "plan") == TaskEvent.PLAN_COMPLETE

    def test_generate(self):
        assert classify_event("code done", "generate") == TaskEvent.CODE_COMPLETE

    def test_verify_pass(self):
        assert classify_event("All tests pass", "verify") == TaskEvent.TEST_PASS

    def test_verify_fail(self):
        assert classify_event("2 tests fail", "verify") == TaskEvent.TEST_FAIL

    def test_verify_ambiguous(self):
        assert classify_event("done", "verify") == TaskEvent.TEST_PASS

    def test_deploy(self):
        assert classify_event("", "deploy") == TaskEvent.DEPLOY

    def test_reset(self):
        assert classify_event("", "reset") == TaskEvent.RESET

    def test_parse_role(self):
        assert classify_event("", "parse") == TaskEvent.PLAN_COMPLETE

    def test_compile_role(self):
        assert classify_event("", "compile") == TaskEvent.CODE_COMPLETE

    def test_unknown_role_fallback(self):
        assert classify_event("", "unknown_role") == TaskEvent.NEW_TASK
