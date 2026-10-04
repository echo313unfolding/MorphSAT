"""
P2C — canonical self-history reconciliation (C10, C7).

Every persistent store is a projection of ONE canonical outcome; stores
may not disagree about the emitted outcome nor invent one.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from morphsat.commit_gate import SplitMemoryStore  # noqa: E402
from morphsat.correction_echo import CorrectionEcho  # noqa: E402
from morphsat.history_projection import (  # noqa: E402
    canonical_outcome_core, graph_projection, memory_projection,
)
from morphsat.receipt_graph import NON_DIRECTIONAL_OUTCOMES, ReceiptGraph  # noqa: E402

MODES = "ABCDHJKLM"


def core(action, direction, posture="commit_ready", eid="e1"):
    return canonical_outcome_core(eid, action, direction, action, direction, posture)


class TestProjections:
    @pytest.mark.parametrize("a,d,p,mem,graph", [
        ("COMMIT", "benign", "", "benign", "benign"),
        ("COMMIT", "suspicious", "", "suspicious", "suspicious"),
        ("COMMIT", "escalate", "", "escalate", "escalate"),
        ("ABSTAIN", None, "abstain_ready", "abstain", "abstain"),
        ("ABSTAIN", None, "swarm_call", None, "handoff"),
        ("CONTINUE", None, "normal", None, "unknown"),
    ])
    def test_mapping(self, a, d, p, mem, graph):
        assert memory_projection(a, d, p) == mem
        assert graph_projection(a, d, p) == graph

    @pytest.mark.parametrize("bad", [None, "unknown", "abstain"])
    def test_commit_without_direction_rejected(self, bad):
        with pytest.raises(ValueError):
            memory_projection("COMMIT", bad)
        with pytest.raises(ValueError):
            graph_projection("COMMIT", bad)

    def test_outcome_ref_deterministic_and_semantic(self):
        assert core("COMMIT", "benign")["outcome_ref"] == core("COMMIT", "benign")["outcome_ref"]
        assert core("COMMIT", "benign")["outcome_ref"] != core("COMMIT", "escalate")["outcome_ref"]

    def test_non_directional_set(self):
        assert {"abstain", "unknown", "handoff", None} <= NON_DIRECTIONAL_OUTCOMES


class TestSplitMemoryCanonical:
    SIG = [("check_hash", "unknown")]

    def _rec(self, tmp_path, c):
        m = SplitMemoryStore(str(tmp_path / "m.json"))
        lbl = m.record_canonical(self.SIG, c, 0.1, "Some alert text here", 0.2, 0.2, 3)
        return m, lbl

    def test_abstain_goes_to_abstain_store_not_threat(self, tmp_path):
        m, lbl = self._rec(tmp_path, core("ABSTAIN", None, "abstain_ready"))
        assert lbl == "abstain" and len(m.abstain) == 1
        assert not m.threat and not m.tolerance
        entry = next(iter(m.abstain.values()))
        assert entry.event_refs == [core("ABSTAIN", None, "abstain_ready")["outcome_ref"]]

    @pytest.mark.parametrize("c", [core("ABSTAIN", None, "swarm_call"),
                                   core("CONTINUE", None, "normal")])
    def test_no_verdict_memory_for_handoff_or_continue(self, tmp_path, c):
        m, lbl = self._rec(tmp_path, c)
        assert lbl is None and not (m.threat or m.tolerance or m.abstain)

    def test_legacy_record_episode_unchanged(self, tmp_path):
        m = SplitMemoryStore(str(tmp_path / "m.json"))
        m.record_episode(self.SIG, "suspicious", 0.1, "Some alert text", 0.2, 0.2, 3)
        assert len(m.threat) == 1 and next(iter(m.threat.values())).event_refs == []

    def test_old_memory_files_still_load(self, tmp_path):
        import json
        p = tmp_path / "old.json"
        p.write_text(json.dumps({"threat": {"h": {
            "pattern_hash": "h", "resolution": "escalate", "confidence": 0.9}},
            "tolerance": {}, "abstain": {}}))
        assert SplitMemoryStore(str(p)).threat["h"].event_refs == []


class TestReceiptGraphCanonical:
    def _receipt(self, canon=None, legacy_dir="escalate"):
        r = {"gate_version": "v7_shadow_monitor", "final_action": "COMMIT",
             "final_direction": legacy_dir, "evidence_vector": [["t", "unexpected"]]}
        if canon is not None:
            r["canonical_outcome"] = canon
        return r

    def test_node_uses_emitted_outcome_and_keeps_monitor_provenance(self, tmp_path):
        g = ReceiptGraph(str(tmp_path / "g.json"))
        c = canonical_outcome_core("e", "COMMIT", "escalate", "COMMIT", "escalate",
                                   "escalate_ready", "none", "two_stage_qubo", True)
        n = g.add_node("h1", self._receipt(c), 0)
        assert (n.outcome, n.action) == ("escalate", "COMMIT")
        assert n.attempted_override_source == "two_stage_qubo"
        assert n.outcome_ref == c["outcome_ref"]

    def test_abstain_node_does_not_vote(self, tmp_path):
        g = ReceiptGraph(str(tmp_path / "g.json"))
        g.add_node("a", self._receipt(core("ABSTAIN", None, "abstain_ready")), 0)
        assert g.nodes["a"].outcome == "abstain"
        assert g.predict(tags=g.nodes["a"].tags)["predicted_outcome"] == "unknown"

    def test_legacy_null_outcome_does_not_vote(self, tmp_path):
        """Pre-P2C ABSTAIN nodes stored outcome=None, which used to vote."""
        g = ReceiptGraph(str(tmp_path / "g.json"))
        r = self._receipt(None, legacy_dir=None); r["final_action"] = "ABSTAIN"
        g.add_node("old", r, 0)
        assert g.nodes["old"].outcome is None
        assert g.predict(tags=g.nodes["old"].tags)["predicted_outcome"] == "unknown"


class TestCorrectionEchoCanonical:
    A1 = "Port scan detected from build server alpha"
    A2 = "CORRECTION port scan from build server alpha authorized"

    def test_prior_outcome_from_own_history(self):
        e = CorrectionEcho(ttl=5)
        e.observe_canonical(self.A1, "s0", "ref0", "COMMIT", "escalate", False, False)
        mk = e.observe_canonical(self.A2, "s1", "ref1", "COMMIT", "benign", True, False)
        assert (mk.outcome_before, mk.outcome_before_ref) == ("escalate", "ref0")
        assert (mk.outcome_after, mk.outcome_after_ref) == ("benign", "ref1")
        assert mk.provenance == "canonical"

    def test_no_prior_gives_unknown_not_constant(self):
        e = CorrectionEcho(ttl=5)
        mk = e.observe_canonical(self.A2, "s1", "ref1", "COMMIT", "benign", True, False)
        assert (mk.outcome_before, mk.outcome_before_ref) == ("unknown", None)

    def test_no_marker_without_detected_correction(self):
        e = CorrectionEcho(ttl=5)
        assert e.observe_canonical(self.A2, "s1", "r", "COMMIT", "benign", False, False) is None

    def test_no_marker_from_abstain(self):
        e = CorrectionEcho(ttl=5)
        assert e.observe_canonical(self.A2, "s1", "r", "ABSTAIN", None, True, False) is None

    def test_recursion_guard_echo_influenced(self):
        e = CorrectionEcho(ttl=5)
        assert e.observe_canonical(self.A2, "s1", "r", "COMMIT", "benign", True, True) is None
        assert e.markers == []

    def test_echo_produced_outcome_never_used_as_prior(self):
        e = CorrectionEcho(ttl=5)
        e.observe_canonical(self.A1, "s0", "ref0", "COMMIT", "escalate", False, False)
        e.observe_canonical(self.A1, "s1", "refE", "COMMIT", "benign", False, False,
                            applied_source="echo_tiebreak")
        assert e.prior_outcome(self.A2) == ("escalate", "ref0")

    def test_marker_ttl_matches_legacy(self):
        a, b = CorrectionEcho(ttl=5), CorrectionEcho(ttl=5)
        a.observe_episode(self.A2, "s", True, "benign", "escalate")
        b.observe_canonical(self.A2, "s", "r", "COMMIT", "benign", True, False)
        assert a.markers[0].ttl == b.markers[0].ttl


@pytest.fixture(scope="module")
def p2c_runs(tmp_path_factory):
    import bench_memory_stress as B
    from test_decision_event import _isolate_bench
    mp = pytest.MonkeyPatch()
    _isolate_bench(B, mp, tmp_path_factory.mktemp("p2c_iso"))
    try:
        yield {m: B.run_stress_mode(m, B.STRESS_FAMILIES) for m in MODES}, B
    finally:
        mp.undo()


class TestStoreCoherenceInvariant:
    def test_every_store_traces_to_the_canonical_event(self, p2c_runs):
        runs, _ = p2c_runs
        for m in MODES:
            refs = {}
            for e in runs[m].decision_events:
                refs[e.outcome_ref] = e
                sm = e.stores["splitmemory"]
                assert sm["label"] == memory_projection(e.final_action, e.final_direction, e.posture_final)
                if sm["label"] is not None:
                    assert sm["entry_present"] and sm["outcome_ref_present"], (m, e.scenario_id)
                if "receiptgraph" in e.stores:
                    g = e.stores["receiptgraph"]
                    assert g["outcome"] == graph_projection(e.final_action, e.final_direction, e.posture_final)
                    assert g["action"] == e.final_action
                    assert g["outcome_ref"] == e.outcome_ref
                if e.stores.get("echo", {}).get("marker_created"):
                    mk = e.stores["echo"]["marker_created"]
                    assert mk["outcome_after"] == e.final_direction
                    assert mk["outcome_after_ref"] == e.outcome_ref
                    if mk["outcome_before_ref"] is not None:
                        prior = refs[mk["outcome_before_ref"]]   # must be an EARLIER real event
                        assert prior.family == e.family
                        assert prior.episode_index < e.episode_index
                        lbl = prior.final_direction if prior.final_action == "COMMIT" else "abstain"
                        assert mk["outcome_before"] == lbl

    def test_no_store_records_a_threat_for_abstain(self, p2c_runs):
        runs, _ = p2c_runs
        for m in MODES:
            for e in runs[m].decision_events:
                if e.final_action == "ABSTAIN":
                    assert e.stores["splitmemory"]["store"] in ("abstain", None)
                    assert e.stores.get("receiptgraph", {}).get("outcome", "abstain") in ("abstain", "handoff")

    def test_canonical_flags_off_reproduce_legacy_stores(self, p2c_runs):
        _, B = p2c_runs
        r = B.run_stress_mode("D", B.STRESS_FAMILIES, canonical_memory=False, canonical_echo=False)
        ab = [e for e in r.decision_events if e.final_action == "ABSTAIN"]
        assert ab and all(e.stores["splitmemory"]["store"] == "threat" for e in ab)
        assert all(e.stores["receiptgraph"]["outcome"] is None for e in ab)
