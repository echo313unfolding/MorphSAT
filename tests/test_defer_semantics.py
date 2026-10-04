"""P3 — DEFER semantics (prereg v2 §1, v2.1 A3)."""

import pytest

from morphsat.commit_gate import SplitMemoryStore
from morphsat.shadow_monitor import (
    DEFER_REASON_CLASSES, NON_DEFER_REASONS, ShadowMonitor, ShadowState,
)
from morphsat.terminal_authority import resolve_terminal_authority as R


def mon(tmp_path, defer=True, dual=True):
    m = ShadowMonitor(memory=SplitMemoryStore(str(tmp_path / "m.json")),
                      enable_dual_boundary=dual, enable_defer=defer)
    m.initialize("Unknown binary executing")
    return m


def in_zone(m, t=0.30, s=0.10):
    m.threat_score, m.safety_score = t, s
    return t - s


class TestStateTable:
    def test_continue(self, tmp_path):
        m = mon(tmp_path)
        assert (m.local_acquisition_closed, m.decision_terminal) == (False, False)

    def test_defer(self, tmp_path):
        m = mon(tmp_path); b = in_zone(m)
        a = m._force_commit("bench_end", b)
        assert a.action == "DEFER" and m.state == ShadowState.DEFERRED
        assert (m.local_acquisition_closed, m.decision_terminal) == (True, False)
        assert m.committed is False and m.terminal_latched is False

    def test_commit(self, tmp_path):
        m = mon(tmp_path); m.safety_score = 0.9
        assert m._force_commit("bench_end", -0.9).action == "COMMIT"
        assert (m.local_acquisition_closed, m.decision_terminal) == (True, True)

    def test_abstain(self, tmp_path):
        m = mon(tmp_path); m.threat_score = m.safety_score = 0.5
        assert m._force_commit("bench_end", 0.0).action == "ABSTAIN"   # contradiction
        assert (m.local_acquisition_closed, m.decision_terminal) == (True, True)

    def test_acquisition_stops_after_defer(self, tmp_path):
        m = mon(tmp_path); m._force_commit("bench_end", in_zone(m))
        n = m.total_tools
        assert m.process_evidence("t", "unexpected outbound").action == "DEFERRED"
        assert m.total_tools == n


class TestReasonWhitelist:
    @pytest.mark.parametrize("reason,cls", sorted(DEFER_REASON_CLASSES.items()))
    def test_whitelisted(self, tmp_path, reason, cls):
        m = mon(tmp_path)
        assert m._force_commit(reason, in_zone(m)).action == "DEFER"
        assert m.reason_for_defer == cls

    def test_exact_whitelist(self):
        assert DEFER_REASON_CLASSES == {
            "bench_end": "HARNESS_END",
            "investigate_budget": "TOOL_BUDGET_EXHAUSTED",
            "safe_distance_budget": "TOOL_BUDGET_EXHAUSTED",
            "max_tools_reached": "MAX_TOOLS",
            "loop_in_normal": "STAGNATION",
            "investigate_no_progress": "STAGNATION"}

    @pytest.mark.parametrize("reason", sorted(NON_DEFER_REASONS))
    def test_recognized_non_defer(self, tmp_path, reason):
        m = mon(tmp_path)
        assert m._force_commit(reason, in_zone(m)).action == "ABSTAIN"
        assert m.unrecognized_defer_reason is None

    def test_unknown_reason_fails_closed(self, tmp_path):
        m = mon(tmp_path)
        assert m._force_commit("some_new_harness_end", in_zone(m)).action == "ABSTAIN"
        assert m.unrecognized_defer_reason == "some_new_harness_end"


class TestNeverDefer:
    def test_contradiction(self, tmp_path):
        m = mon(tmp_path); m.threat_score = m.safety_score = 0.35
        assert m._force_commit("bench_end", 0.0).action == "ABSTAIN"

    def test_boundary_crossed_commits(self, tmp_path):
        m = mon(tmp_path); m.threat_score = 0.7
        assert m._force_commit("bench_end", 0.7).action == "COMMIT"

    def test_single_boundary_mode(self, tmp_path):
        m = mon(tmp_path, dual=False); m.threat_score = 0.2
        assert m._force_commit("bench_end", 0.2).action == "COMMIT"

    def test_disabled_flag_keeps_abstain(self, tmp_path):
        m = mon(tmp_path, defer=False)
        a = m._force_commit("bench_end", in_zone(m))
        assert a.action == "ABSTAIN" and m.local_acquisition_closed == m.decision_terminal

    def test_receipt_keys_only_when_enabled(self, tmp_path):
        assert "reason_for_defer" not in mon(tmp_path, defer=False).to_receipt()
        assert "reason_for_defer" in mon(tmp_path).to_receipt()


class TestAuthorityOnDefer:
    def test_only_arbitration_resolves(self):
        r = R("DEFER", None, False, "COMMIT", "benign", "two_stage_qubo")
        assert r.final_action == "DEFER" and r.blocked_by_terminal
        assert R("DEFER", None, False).final_action == "DEFER"
        r = R("DEFER", None, False, "COMMIT", "escalate", "arbitration")
        assert (r.final_action, r.final_direction, r.applied_source) == ("COMMIT", "escalate", "arbitration")

    @pytest.mark.parametrize("bad", [("DEFER", None), ("CONTINUE", None),
                                     ("ABSTAIN", "benign"), ("COMMIT", None)])
    def test_arbitration_output_validated(self, bad):
        with pytest.raises(ValueError):
            R("DEFER", None, False, *bad, "arbitration")

    @pytest.mark.parametrize("m", [("COMMIT", "escalate"), ("ABSTAIN", None)])
    def test_arbitration_on_terminal_fails_closed(self, m):
        with pytest.raises(ValueError):
            R(*m, True, "COMMIT", "benign", "arbitration")
