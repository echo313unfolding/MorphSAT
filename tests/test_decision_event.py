"""
P1 — DecisionEvent instrumentation tests (Phase 2.5).

Proves the instrumentation is observational:
  * hashes are deterministic from semantic content only,
  * enabling/disabling event collection leaves every behavioral output
    of the stress benchmark identical,
  * no DecisionEvent value is read by the decision path,
  * final_* means exactly what the bench emitted; monitor_* is provenance.

Characterization tests pin the CURRENT (public GitHub state 14689b7)
semantics, including known defects (terminal-state overrides, store
divergence). They are expected to change in a later behavioral phase.
"""

import ast
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from morphsat.decision_event import (  # noqa: E402
    DecisionEvent,
    E10_OBSERVABLES,
    events_digest,
    severity_change,
)

MODES = "ABCDHJKLM"


# ---------------------------------------------------------------------------
# Isolation: keep bench temp files out of the shared /tmp namespace
# ---------------------------------------------------------------------------

def _isolate_bench(B, mp, tmpdir):
    """Redirect hard-coded /tmp paths used by the bench into tmpdir."""
    base_store = B.SplitMemoryStore

    class _IsolatedStore(base_store):
        def __init__(self, store_path="commit_gate_memory.json"):
            p = str(store_path)
            if p.startswith("/tmp/"):
                p = os.path.join(str(tmpdir), os.path.basename(p))
            super().__init__(p)

    counter = {"n": 0}

    def _make_tmp(suffix):
        counter["n"] += 1
        return os.path.join(str(tmpdir), f"bench_{suffix}_{counter['n']}")

    mp.setattr(B, "SplitMemoryStore", _IsolatedStore)
    mp.setattr(B, "_make_tmp", _make_tmp)


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    import bench_memory_stress as B
    mp = pytest.MonkeyPatch()
    _isolate_bench(B, mp, tmp_path_factory.mktemp("bench_iso"))
    yield B
    mp.undo()


@pytest.fixture(scope="module")
def runs(bench):
    """All modes with and without event collection."""
    on = {m: bench.run_stress_mode(m, bench.STRESS_FAMILIES) for m in MODES}
    off = {m: bench.run_stress_mode(m, bench.STRESS_FAMILIES,
                                    collect_events=False) for m in MODES}
    return on, off


def _event(runs, mode, sid):
    return next(e for e in runs[0][mode].decision_events if e.scenario_id == sid)


# ---------------------------------------------------------------------------
# Schema / hashing
# ---------------------------------------------------------------------------

def _minimal(**kw):
    base = dict(
        episode_id="X/f/000/s", mode="X", family="f", episode_index=0,
        scenario_id="s", evidence_signature=[["t", "clean"]],
        monitor_action="COMMIT", monitor_direction="benign",
        monitor_terminal=True, monitor_forced_at_bench_end=False,
        posture_initial="normal", posture_final="commit_ready",
        posture_transitions=[], monitor_abstain_due_to_uncertainty=False,
        monitor_boundary_crossed="safe", threat_score=0.1,
        safety_score=0.5, contradiction=0.1,
        final_action="COMMIT", final_direction="benign",
    )
    base.update(kw)
    return DecisionEvent(**base)


class TestSchemaAndHash:
    def test_hash_deterministic(self):
        assert _minimal().event_hash == _minimal().event_hash

    def test_hash_sensitive_to_semantics(self):
        assert _minimal().event_hash != _minimal(final_direction="escalate").event_hash

    def test_float_noise_below_precision_ignored(self):
        assert (_minimal(threat_score=0.1).event_hash
                == _minimal(threat_score=0.10000000001).event_hash)

    def test_event_hash_not_in_its_own_payload(self):
        assert "event_hash" not in _minimal().payload()
        assert _minimal().to_dict()["event_hash"] == _minimal().event_hash

    def test_no_environment_fields_in_schema(self):
        keys = set(_minimal().payload())
        for forbidden in ("timestamp", "pid", "hostname", "path", "wall_time"):
            assert not any(forbidden in k for k in keys), forbidden

    def test_monitor_and_final_are_distinct_fields(self):
        keys = set(_minimal().payload())
        assert {"monitor_action", "monitor_direction",
                "final_action", "final_direction"} <= keys

    def test_severity_change(self):
        assert severity_change("escalate", "suspicious") == "down"
        assert severity_change("benign", "escalate") == "up"
        assert severity_change(None, "benign") == "n/a"

    def test_digest_order_sensitive(self):
        a, b = _minimal(), _minimal(scenario_id="t")
        assert events_digest([a, b]) != events_digest([b, a])


# ---------------------------------------------------------------------------
# Behavioral neutrality (the core P1 guarantee)
# ---------------------------------------------------------------------------

class TestNeutrality:
    def test_episode_results_identical_with_and_without_events(self, runs):
        on, off = runs
        for m in MODES:
            assert [asdict(e) for e in on[m].episodes] == \
                   [asdict(e) for e in off[m].episodes], m

    def test_mode_metrics_identical(self, runs):
        on, off = runs
        for m in MODES:
            assert on[m].to_dict() == off[m].to_dict(), m

    def test_one_event_per_episode(self, runs):
        on, off = runs
        for m in MODES:
            assert len(on[m].decision_events) == len(on[m].episodes) == 82
            assert off[m].decision_events == []

    def test_package_does_not_import_decision_event(self):
        for py in (ROOT / "morphsat").glob("*.py"):
            if py.name == "decision_event.py":
                continue
            tree = ast.parse(py.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert node.module != "morphsat.decision_event", py.name
                if isinstance(node, ast.Import):
                    assert all(a.name != "morphsat.decision_event"
                               for a in node.names), py.name

    def test_obs_is_write_only_before_close_episode(self):
        """Every READ of _obs / event_sink in run_stress_episode happens
        after monitor.close_episode(); before it, _obs is only assigned."""
        src = (ROOT / "tools" / "bench_memory_stress.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "run_stress_episode")
        close_line = min(
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "close_episode")
        store_targets = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store):
                store_targets.add(id(n.value))
        reads = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Name) and n.id in ("_obs", "event_sink")
            and isinstance(n.ctx, ast.Load) and id(n) not in store_targets
        ]
        assert reads, "expected post-close reads"
        early = [ln for ln in reads if ln < close_line]
        assert early == [], f"_obs/event_sink read before close_episode: {early}"

    def test_decision_events_unused_by_gates_and_metrics(self):
        src = (ROOT / "tools" / "bench_memory_stress.py").read_text()
        tree = ast.parse(src)
        allowed = {"run_stress_mode", "write_stress_receipt"}
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            if fn.name in allowed:
                continue
            for n in ast.walk(fn):
                if isinstance(n, ast.Attribute) and n.attr == "decision_events":
                    pytest.fail(f"decision_events read in {fn.name}")


# ---------------------------------------------------------------------------
# Faithfulness of final_* and provenance
# ---------------------------------------------------------------------------

class TestFaithfulness:
    def test_final_fields_equal_emitted_outcome(self, runs):
        on, _ = runs
        for m in MODES:
            for ep, ev in zip(on[m].episodes, on[m].decision_events):
                assert ev.scenario_id == ep.scenario_id
                assert ev.final_action == ep.final_action, (m, ep.scenario_id)
                # v2: final_direction is canonical (None = no substantive
                # direction); the legacy scoring projection is scored_as.
                assert ev.evaluation["scored_as"] == ep.final_verdict
                if ev.final_direction is None:
                    assert ev.final_direction_defaulted
                    assert ep.final_verdict == "suspicious"
                else:
                    assert ev.final_direction == ep.final_verdict
                assert ev.evaluation["correct"] == ep.verdict_correct

    def test_no_gate_modes_have_no_override(self, runs):
        on, _ = runs
        for m in "ABCD":
            assert all(e.override_source == "none"
                       for e in on[m].decision_events), m

    def test_override_source_records_assigning_stage_even_if_unchanged(self, runs):
        """K/L: the two-stage QUBO branch assigns the final outcome in some
        episodes but never changes the direction. override_source records
        WHICH stage set the output; final_changed_from_monitor records
        WHETHER it differs."""
        on, _ = runs
        for m in "KL":
            evs = on[m].decision_events
            assert any(e.override_source == "two_stage_qubo" for e in evs), m
            assert not any(e.final_direction != e.monitor_direction
                           for e in evs), m

    def test_splitmemory_records_scored_projection(self, runs):
        """P2B leaves memory semantics unchanged: SplitMemory still receives
        the legacy scored value (ABSTAIN -> 'suspicious'), i.e. C10."""
        on, _ = runs
        for m in MODES:
            for e in on[m].decision_events:
                assert e.stores["splitmemory_resolution"] == e.evaluation["scored_as"]

    def test_no_environment_noise_in_bench_events(self, runs):
        on, _ = runs
        blob = json.dumps([e.to_dict() for m in MODES
                           for e in on[m].decision_events])
        assert "/tmp" not in blob and "bench_iso" not in blob


class TestCrossProcessDeterminism:
    def test_digests_match_fresh_process(self, runs, tmp_path):
        code = f"""
import sys, os, json
sys.path.insert(0, {str(ROOT)!r}); sys.path.insert(0, {str(ROOT / 'tools')!r})
import pytest
sys.path.insert(0, {str(ROOT / 'tests')!r})
from test_decision_event import _isolate_bench
import bench_memory_stress as B
from morphsat.decision_event import events_digest
mp = pytest.MonkeyPatch(); _isolate_bench(B, mp, {str(tmp_path)!r})
print(json.dumps({{m: events_digest(B.run_stress_mode(m, B.STRESS_FAMILIES).decision_events)
                  for m in {MODES!r}}}))
"""
        out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                             text=True, check=True).stdout.strip().splitlines()[-1]
        fresh = json.loads(out)
        on, _ = runs
        assert fresh == {m: events_digest(on[m].decision_events) for m in MODES}


# ---------------------------------------------------------------------------
# Characterization of CURRENT semantics (expected to change in P3)
# ---------------------------------------------------------------------------

class TestTerminalAuthorityCharacterization:
    """P2B (D1 = A2): COMMIT and ABSTAIN are terminal. Downstream
    disagreement is preserved as attempted_* provenance, never applied."""

    def test_hard_invariant_all_modes(self, runs):
        on, _ = runs
        for m in MODES:
            for e in on[m].decision_events:
                if e.monitor_terminal and e.monitor_action in ("COMMIT", "ABSTAIN"):
                    assert e.final_action == e.monitor_action, (m, e.scenario_id)
                    assert e.final_direction == e.monitor_direction, (m, e.scenario_id)

    def test_abstain_direction_never_fabricated(self, runs):
        on, _ = runs
        for m in MODES:
            for e in on[m].decision_events:
                if e.final_action == "ABSTAIN":
                    assert e.final_direction is None

    def test_applied_safety_counts_zero(self, runs):
        on, _ = runs
        for m in MODES:
            ev = [e.evaluation for e in on[m].decision_events]
            assert sum(x["committed_escalate_downgrade_applied"] for x in ev) == 0, m
            assert sum(x["terminal_abstain_override_applied"] for x in ev) == 0, m
            assert sum(x["terminal_state_overridden"] for x in ev) == 0, m

    def test_no_incoherent_finals(self, runs):
        on, _ = runs
        for m in MODES:
            assert not any(e.final_action_direction_incoherent
                           for e in on[m].decision_events), m

    def test_M_wc03_downgrade_attempt_blocked(self, runs):
        e = _event(runs, "M", "wc_03")
        assert (e.monitor_action, e.monitor_direction) == ("COMMIT", "escalate")
        assert e.echo_match and e.echo_injected_memory and e.echo_outcome == "benign"
        assert e.route_backend == "qubo" and e.route_reason == "memory_disagrees"
        assert e.override_source == "none"
        assert (e.attempted_override_source, e.attempted_action,
                e.attempted_direction) == ("two_stage_qubo", "COMMIT", "suspicious")
        assert e.override_blocked_by_terminal is True
        assert (e.final_action, e.final_direction) == ("COMMIT", "escalate")
        assert e.evaluation["committed_escalate_downgrade_attempt"] is True
        assert e.evaluation["committed_escalate_downgrade_applied"] is False
        assert e.evaluation["correct"] is True
        # memory semantics unchanged in P2B: stores now agree on escalate
        assert e.stores == {"splitmemory_resolution": "escalate",
                            "receiptgraph_node_outcome": "escalate"}

    @pytest.mark.parametrize("sid", ["drift_05", "drift_06", "stale_03"])
    def test_M_echo_tiebreak_on_abstain_blocked(self, runs, sid):
        e = _event(runs, "M", sid)
        assert e.monitor_action == "ABSTAIN" and e.monitor_terminal is True
        assert (e.attempted_override_source, e.attempted_action,
                e.attempted_direction) == ("echo_tiebreak", "ABSTAIN", "benign")
        assert e.override_blocked_by_terminal is True
        assert (e.final_action, e.final_direction) == ("ABSTAIN", None)
        assert e.evaluation["terminal_abstain_override_attempt"] is True
        assert e.evaluation["terminal_abstain_override_applied"] is False

    def test_M_drift06_first_contradiction_still_injects(self, runs):
        e = _event(runs, "M", "drift_06")
        assert e.threat_score > e.safety_score
        assert (e.echo_contradiction_count_pre,
                e.echo_contradiction_count_post) == (0, 1)
        assert e.echo_injected_memory is True

    def test_stores_diverge_on_abstain_without_override(self, runs):
        """C10 still present in P2B (memory semantics untouched): every
        ABSTAIN is 'unknown' in ReceiptGraph projection but 'suspicious'
        (threat store) in SplitMemory."""
        on, _ = runs
        abst = [e for e in on["D"].decision_events if e.monitor_action == "ABSTAIN"]
        assert len(abst) == 19
        for e in abst:
            assert e.final_direction is None and e.final_direction_defaulted
            assert e.stores == {"splitmemory_resolution": "suspicious",
                                "receiptgraph_node_outcome": "unknown"}

    def test_echo_provenance_is_oracle_and_hardcoded(self, runs):
        on, _ = runs
        made = [e for e in on["M"].decision_events
                if "echo_marker_created_from" in e.stores]
        assert made
        for e in made:
            src = e.stores["echo_marker_created_from"]
            assert src["outcome_before"] == "escalate"
            assert src["is_correction_source"] == "scenario.has_correction_tools"

    def test_attempt_counts(self, runs):
        """Attempts that would have changed the scored direction. J and M
        match the Phase 2.5 attribution (2, 4). H is 11, not 12: a
        second-order history effect — in poison_07 the pre-A2 QUBO saw a
        threat-store memory entry created by an earlier OVERRIDDEN verdict;
        under A2 that entry never exists and the QUBO proposes CONTINUE,
        whose scored direction equals the monitor's."""
        on, _ = runs
        def dir_attempts(m):
            return sum(
                e.override_blocked_by_terminal
                and (e.attempted_direction or "suspicious")
                != (e.monitor_direction or "suspicious")
                for e in on[m].decision_events)
        assert {m: dir_attempts(m) for m in "HJM"} == {"H": 11, "J": 2, "M": 4}

    def test_enforcement_off_reproduces_pre_A2(self, bench):
        r = bench.run_stress_mode("M", bench.STRESS_FAMILIES,
                                  enforce_terminal_authority=False)
        e = next(x for x in r.decision_events if x.scenario_id == "wc_03")
        assert (e.final_action, e.final_direction) == ("COMMIT", "suspicious")
        assert e.override_source == "two_stage_qubo"
        assert e.override_blocked_by_terminal is False
        assert e.evaluation["committed_escalate_downgrade_applied"] is True
        assert r.correct == 78
