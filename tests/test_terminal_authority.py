"""P2B — unit tests for the terminal authority invariant (D1 = A2)."""

import pytest

from morphsat.terminal_authority import (
    TERMINAL_AUTHORITY_ACTIONS,
    resolve_terminal_authority as R,
)


def test_terminal_actions():
    assert TERMINAL_AUTHORITY_ACTIONS == {"COMMIT", "ABSTAIN"}


def test_no_proposal_returns_monitor():
    r = R("COMMIT", "escalate", True)
    assert (r.final_action, r.final_direction, r.applied_source) == ("COMMIT", "escalate", "none")
    assert not r.attempted and not r.blocked_by_terminal


def test_agreeing_proposal_is_not_an_attempt():
    r = R("COMMIT", "escalate", True, "COMMIT", "escalate", "two_stage_qubo")
    assert r.applied_source == "two_stage_qubo"
    assert not r.attempted and not r.blocked_by_terminal


@pytest.mark.parametrize("prop", [("COMMIT", "suspicious"), ("COMMIT", "benign"),
                                  ("CONTINUE", None), ("ABSTAIN", None)])
def test_terminal_commit_cannot_be_replaced(prop):
    r = R("COMMIT", "escalate", True, *prop, "gate_qubo")
    assert (r.final_action, r.final_direction) == ("COMMIT", "escalate")
    assert r.attempted and r.blocked_by_terminal
    assert (r.attempted_source, r.attempted_action, r.attempted_direction) == ("gate_qubo", *prop)
    assert r.applied_source == "none"


@pytest.mark.parametrize("prop", [("ABSTAIN", "benign"), ("COMMIT", "escalate"),
                                  ("CONTINUE", None)])
def test_terminal_abstain_cannot_be_replaced(prop):
    r = R("ABSTAIN", None, True, *prop, "echo_tiebreak")
    assert (r.final_action, r.final_direction) == ("ABSTAIN", None)
    assert r.blocked_by_terminal


def test_non_terminal_monitor_allows_proposal():
    r = R("CONTINUE", None, False, "COMMIT", "benign", "two_stage_qubo")
    assert (r.final_action, r.final_direction, r.applied_source) == ("COMMIT", "benign", "two_stage_qubo")
    assert r.attempted and not r.blocked_by_terminal


def test_unlatched_flag_disables_authority():
    """monitor_terminal=False is the pre-A2 behavior (used by the bench's
    enforce_terminal_authority=False switch)."""
    r = R("COMMIT", "escalate", False, "COMMIT", "suspicious", "two_stage_qubo")
    assert r.final_direction == "suspicious" and not r.blocked_by_terminal
