"""Tests for WO-07 (from_spec/from_preset) and WO-08 (propose/step_or_propose).

Ported from GuardianCell + KRISPERcell patterns (echo-box/pssh).
"""

import json

import numpy as np
import pytest

from morphsat.core import (
    CandidateTransition,
    MorphSATGate,
    TaskEvent,
    TaskState,
    _PRESETS,
)


# ---------------------------------------------------------------------------
# WO-07: from_preset
# ---------------------------------------------------------------------------

class TestFromPreset:
    def test_task_lifecycle_preset_exists(self):
        assert "task_lifecycle" in _PRESETS

    def test_from_preset_task_lifecycle(self):
        gate = MorphSATGate.from_preset("task_lifecycle")
        assert gate._spec_id == "task_lifecycle_v1"
        assert gate._state_names == ["IDLE", "PLANNING", "WRITING", "TESTING", "DONE"]
        assert len(gate._event_names) == 7

    def test_from_preset_happy_path(self):
        """Preset gate should work identically to the default gate."""
        gate = MorphSATGate.from_preset("task_lifecycle")
        s, ok, a = gate.step(0)  # NEW_TASK
        assert ok and s == 1  # PLANNING

        s, ok, a = gate.step(1)  # PLAN_COMPLETE
        assert ok and s == 2  # WRITING

        s, ok, a = gate.step(2)  # CODE_COMPLETE
        assert ok and s == 3  # TESTING

        s, ok, a = gate.step(3)  # TEST_PASS
        assert ok and s == 4  # DONE

    def test_from_preset_guardian_blocks(self):
        gate = MorphSATGate.from_preset("task_lifecycle")
        gate.step(0)  # -> PLANNING
        s, ok, a = gate.step(6)  # DEPLOY from PLANNING
        assert not ok and a == "GUARDIAN_BLOCKED"

    def test_from_preset_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown preset"):
            MorphSATGate.from_preset("nonexistent")

    def test_preset_matches_default_gate(self):
        """Preset gate must produce identical results to default constructor."""
        default = MorphSATGate()
        preset = MorphSATGate.from_preset("task_lifecycle")

        # Run same event sequence through both
        events = [0, 1, 2, 4, 2, 3, 6]  # happy path with one test_fail
        for ev in events:
            d_s, d_ok, d_a = default.step(ev)
            p_s, p_ok, p_a = preset.step(ev)
            assert int(d_s) == int(p_s), f"State mismatch on event {ev}"
            assert d_ok == p_ok, f"Legal mismatch on event {ev}"
            assert d_a == p_a, f"Action mismatch on event {ev}"


# ---------------------------------------------------------------------------
# WO-07: from_spec (custom domain)
# ---------------------------------------------------------------------------

REVIEW_SPEC = {
    "id": "review_pipeline_v1",
    "states": ["DRAFT", "REVIEW", "APPROVED", "PUBLISHED"],
    "events": ["SUBMIT", "APPROVE", "REJECT", "PUBLISH", "RESET"],
    "transitions": {
        "DRAFT.SUBMIT": "REVIEW",
        "REVIEW.APPROVE": "APPROVED",
        "REVIEW.REJECT": "DRAFT",
        "APPROVED.PUBLISH": "PUBLISHED",
    },
    "reset_event": "RESET",
    "reset_target": "DRAFT",
    "guardian_blocked": [
        "DRAFT.PUBLISH",
        "REVIEW.PUBLISH",
    ],
}


class TestFromSpec:
    def test_custom_spec_loads(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        assert gate._spec_id == "review_pipeline_v1"
        assert gate._state_names == ["DRAFT", "REVIEW", "APPROVED", "PUBLISHED"]
        assert gate._event_names == ["SUBMIT", "APPROVE", "REJECT", "PUBLISH", "RESET"]

    def test_custom_happy_path(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        # DRAFT -> SUBMIT -> REVIEW
        s, ok, a = gate.step(0)  # SUBMIT
        assert ok and s == 1 and a == "ALLOWED"

        # REVIEW -> APPROVE -> APPROVED
        s, ok, a = gate.step(1)  # APPROVE
        assert ok and s == 2

        # APPROVED -> PUBLISH -> PUBLISHED
        s, ok, a = gate.step(3)  # PUBLISH
        assert ok and s == 3

    def test_custom_reject_loop(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        gate.step(0)  # -> REVIEW
        s, ok, a = gate.step(2)  # REJECT -> DRAFT
        assert ok and s == 0

    def test_custom_fsa_blocked(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        # DRAFT + APPROVE is not in transitions -> FSA_BLOCKED
        s, ok, a = gate.step(1)  # APPROVE from DRAFT
        assert not ok and a == "FSA_BLOCKED"

    def test_custom_guardian_blocked(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        # DRAFT + PUBLISH is guardian-blocked
        s, ok, a = gate.step(3)  # PUBLISH from DRAFT
        assert not ok and a == "GUARDIAN_BLOCKED"

    def test_custom_reset_from_any(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        gate.step(0)  # -> REVIEW
        gate.step(1)  # -> APPROVED
        s, ok, a = gate.step(4)  # RESET -> DRAFT
        assert ok and s == 0

    def test_custom_history_uses_names(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        gate.step(0)  # SUBMIT
        entry = gate.history[0]
        assert entry["from"] == "DRAFT"
        assert entry["event"] == "SUBMIT"
        assert entry["to"] == "REVIEW"

    def test_custom_receipt_includes_spec_id(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        gate.step(0)
        receipt = gate.to_receipt()
        assert receipt["spec_id"] == "review_pipeline_v1"


# ---------------------------------------------------------------------------
# WO-07: from_json (file-based loading)
# ---------------------------------------------------------------------------

class TestFromJSON:
    def test_load_from_file(self, tmp_path):
        spec_path = tmp_path / "review.json"
        spec_path.write_text(json.dumps(REVIEW_SPEC))

        gate = MorphSATGate.from_json(spec_path)
        assert gate._spec_id == "review_pipeline_v1"

        s, ok, a = gate.step(0)  # SUBMIT
        assert ok and s == 1

    def test_load_from_string_path(self, tmp_path):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(REVIEW_SPEC))

        gate = MorphSATGate.from_json(str(spec_path))
        assert gate._spec_id == "review_pipeline_v1"


# ---------------------------------------------------------------------------
# WO-08: propose (ranked alternatives)
# ---------------------------------------------------------------------------

class TestPropose:
    def test_propose_from_idle(self):
        gate = MorphSATGate()
        alts = gate.propose()
        assert len(alts) > 0
        assert all(isinstance(a, CandidateTransition) for a in alts)

    def test_propose_sorted_by_cost(self):
        gate = MorphSATGate()
        alts = gate.propose(max_candidates=10)
        costs = [a.cost for a in alts]
        assert costs == sorted(costs)

    def test_propose_only_legal(self):
        """Every proposed transition must be actually legal."""
        gate = MorphSATGate()
        for alt in gate.propose(max_candidates=10):
            # Verify it's really legal by checking the table
            next_val = int(gate.T[int(gate.state), alt.event])
            assert next_val >= 0, f"Proposed illegal transition: {alt}"
            assert (int(gate.state), alt.event) not in gate.guardian_blocked

    def test_propose_max_candidates(self):
        gate = MorphSATGate()
        alts = gate.propose(max_candidates=1)
        assert len(alts) <= 1

    def test_propose_after_blocked(self):
        """Propose alternatives after a guardian block."""
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)  # -> PLANNING

        # Try illegal: DEPLOY from PLANNING is guardian-blocked
        s, ok, a = gate.step(TaskEvent.DEPLOY)
        assert not ok

        # Now propose alternatives
        alts = gate.propose()
        assert len(alts) > 0
        # First alternative should have lowest cost (closest to DONE)
        alt_names = [a.event_name for a in alts]
        assert "PLAN_COMPLETE" in alt_names  # forward progress

    def test_propose_from_done(self):
        gate = MorphSATGate()
        gate.state = int(TaskState.DONE)
        alts = gate.propose()
        # From DONE: DEPLOY (stay at DONE, cost=0) and NEW_TASK go to PLANNING
        # But NEW_TASK is guardian-blocked from... no, DONE.NEW_TASK is NOT blocked
        alt_events = {a.event_name for a in alts}
        assert "DEPLOY" in alt_events or "RESET" in alt_events

    def test_propose_names_match_spec(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        alts = gate.propose()
        for alt in alts:
            assert alt.event_name in REVIEW_SPEC["events"]
            assert alt.next_state_name in REVIEW_SPEC["states"]

    def test_propose_custom_domain(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        # From DRAFT, only SUBMIT and RESET are legal
        alts = gate.propose(max_candidates=10)
        alt_names = {a.event_name for a in alts}
        assert "SUBMIT" in alt_names
        assert "RESET" in alt_names
        # APPROVE, REJECT, PUBLISH should NOT be proposed
        assert "APPROVE" not in alt_names
        assert "PUBLISH" not in alt_names


# ---------------------------------------------------------------------------
# WO-08: step_or_propose
# ---------------------------------------------------------------------------

class TestStepOrPropose:
    def test_legal_step_no_alternatives(self):
        gate = MorphSATGate()
        s, ok, a, alts = gate.step_or_propose(TaskEvent.NEW_TASK)
        assert ok
        assert alts == []
        assert int(s) == int(TaskState.PLANNING)

    def test_blocked_step_returns_alternatives(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)  # -> PLANNING

        s, ok, a, alts = gate.step_or_propose(TaskEvent.DEPLOY)
        assert not ok
        assert a == "GUARDIAN_BLOCKED"
        assert len(alts) > 0

    def test_alternatives_are_actionable(self):
        """Every alternative from step_or_propose should succeed if stepped."""
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)  # -> PLANNING

        _, ok, _, alts = gate.step_or_propose(TaskEvent.DEPLOY)
        assert not ok

        # Pick the first alternative and verify it works
        first = alts[0]
        s2, ok2, a2 = gate.step(first.event)
        assert ok2, f"Alternative {first.event_name} should be legal"
        assert int(s2) == first.next_state

    def test_custom_domain_step_or_propose(self):
        gate = MorphSATGate.from_spec(REVIEW_SPEC)
        # Try PUBLISH from DRAFT (guardian-blocked)
        s, ok, a, alts = gate.step_or_propose(3)  # PUBLISH
        assert not ok
        assert len(alts) > 0
        # SUBMIT should be in alternatives
        assert any(a.event_name == "SUBMIT" for a in alts)


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_default_constructor_unchanged(self):
        gate = MorphSATGate()
        assert int(gate.state) == 0
        s, ok, a = gate.step(TaskEvent.NEW_TASK)
        assert ok and int(s) == int(TaskState.PLANNING)

    def test_state_comparison_with_enum(self):
        gate = MorphSATGate()
        # state is int but should compare equal to TaskState enum
        assert gate.state == TaskState.IDLE
        assert gate.state == 0

    def test_custom_table_constructor(self):
        T = np.full((3, 2), -1, dtype=np.int32)
        T[0, 0] = 1
        T[1, 1] = 2
        gate = MorphSATGate(transition_table=T, enable_guardian=False)
        s, ok, a = gate.step(0)
        assert ok and int(s) == 1

    def test_guardian_disabled(self):
        gate = MorphSATGate(enable_guardian=False)
        gate.state = int(TaskState.PLANNING)
        s, ok, a = gate.step(TaskEvent.DEPLOY)
        assert not ok and a == "FSA_BLOCKED"

    def test_history_keys_unchanged(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)
        entry = gate.history[0]
        assert set(entry.keys()) == {"from", "event", "action", "to"}

    def test_receipt_keys_unchanged(self):
        gate = MorphSATGate()
        gate.step(TaskEvent.NEW_TASK)
        receipt = gate.to_receipt()
        assert "final_state" in receipt
        assert "total_transitions" in receipt
        assert "illegal_caught" in receipt
        assert "guardian_caught" in receipt
        assert "history" in receipt
