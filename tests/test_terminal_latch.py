"""
P2A — terminal latch semantic normalization.

`terminal_latched` is the precise name of the latch historically called
`committed`. It is set by ANY terminal action (COMMIT, ABSTAIN, SWARM_CALL).
`committed` remains a read/write alias and the serialized receipt key.
"""

import tempfile

import pytest

from morphsat.commit_gate import CommitGate, SplitMemoryStore
from morphsat.shadow_monitor import ShadowMonitor, ShadowState


@pytest.fixture
def monitor(tmp_path):
    return ShadowMonitor(memory=SplitMemoryStore(str(tmp_path / "m.json")))


class TestAlias:
    def test_alias_reads_latch(self, monitor):
        assert monitor.committed is False and monitor.terminal_latched is False
        monitor.terminal_latched = True
        assert monitor.committed is True

    def test_alias_writes_latch(self, monitor):
        monitor.committed = True
        assert monitor.terminal_latched is True

    def test_commit_gate_alias(self, tmp_path):
        g = CommitGate(memory=SplitMemoryStore(str(tmp_path / "g.json")))
        g.committed = True
        assert g.terminal_latched is True and g.committed is True

    def test_receipt_key_unchanged(self, monitor):
        r = monitor.to_receipt()
        assert "committed" in r and "terminal_latched" not in r
        assert r["committed"] == monitor.terminal_latched


class TestLatchCoversAllTerminalActions:
    def test_commit_latches(self, monitor):
        monitor.initialize("Unknown binary executing")
        monitor.safety_score = 0.9
        a = monitor._force_commit("test", -0.9)
        assert a.action == "COMMIT" and monitor.terminal_latched

    def test_abstain_latches(self, monitor):
        monitor.initialize("Unknown binary executing")
        monitor.threat_score = monitor.safety_score = 0.5
        a = monitor._force_commit("test", 0.0)
        assert a.action == "ABSTAIN" and monitor.terminal_latched

    def test_swarm_call_latches_as_abstain(self, monitor):
        monitor.initialize("Unknown binary executing")   # novelty axis
        monitor.threat_score = monitor.safety_score = 0.35
        a = monitor._transition(evidence_clarity=0.0, contradiction=0.35,
                                threat_delta=0.0, safety_delta=0.0,
                                is_looping=False, no_new_info=False)
        assert monitor.state == ShadowState.SWARM_CALL
        assert a.action == "ABSTAIN" and monitor.terminal_latched

    def test_post_latch_pseudo_action_after_abstain(self, monitor):
        """'COMMITTED' is returned after ANY terminal latch, including ABSTAIN."""
        monitor.initialize("Unknown binary executing")
        monitor.threat_score = monitor.safety_score = 0.5
        monitor._force_commit("test", 0.0)
        assert monitor.process_evidence("t", "anything").action == "COMMITTED"
        assert monitor.last_action.action == "ABSTAIN"
