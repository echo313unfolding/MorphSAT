"""P3 — temporal leakage controls (prereg v2.1 A2)."""

import sys
from dataclasses import asdict, replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from morphsat.arbitration import ArbitrationRequest, arbitrate  # noqa: E402
from morphsat.canonical_history import CanonicalHistory, HistoryRecord  # noqa: E402


def rec(i, d="escalate", sup=(), resolved="monitor"):
    return HistoryRecord(f"r{i}", "F", i, f"F/s{i}", ("alpha", "beta"), (), "COMMIT", d,
                         d, False, tuple(sup), resolved)


def store(n):
    h = CanonicalHistory()
    for i in range(n):
        h.append(rec(i))
    return h


def request(slots, order):
    return ArbitrationRequest("F", order, "F/t", "e", "B2", "HARNESS_END", 0.3, 0.1, 0.1,
                              (), ("alpha", "beta"), tuple(slots))


class TestStoreVisibility:
    def test_future_records_in_store_are_invisible(self):
        h = store(10)
        assert [r.order for r in h.candidates("F", 4, frozenset({"alpha", "beta"}))] == [0, 1, 2, 3]

    def test_appending_future_records_does_not_change_result(self):
        h = store(4)
        before = arbitrate(request(h.candidates("F", 4, frozenset({"alpha", "beta"})), 4))
        for i in range(4, 9):
            h.append(rec(i, d="benign"))
        after = arbitrate(request(h.candidates("F", 4, frozenset({"alpha", "beta"})), 4))
        assert before == after

    def test_arbitration_resolved_records_excluded(self):
        h = store(2); h.append(rec(2, resolved="arbitration"))
        assert [r.order for r in h.candidates("F", 5, frozenset({"alpha", "beta"}))] == [0, 1]

    def test_k_max_most_recent(self):
        assert [r.order for r in store(9).candidates("F", 9, frozenset({"alpha", "beta"}))] == [4, 5, 6, 7, 8]


class TestRequestValidity:
    def test_future_record_in_request_fails_closed(self):
        with pytest.raises(ValueError):
            arbitrate(request([rec(0), rec(5)], order=5))

    def test_current_record_in_request_fails_closed(self):
        with pytest.raises(ValueError):
            arbitrate(request([rec(0), rec(3)], order=3))

    def test_foreign_run_record_fails_closed(self):
        with pytest.raises(ValueError):
            arbitrate(request([rec(0), replace(rec(1), run_id="G")], order=4))

    def test_forward_supersedes_rejected_at_write(self):
        h = store(2)
        with pytest.raises(ValueError):
            h.append(rec(2, sup=("r7",)))

    def test_records_are_immutable(self):
        with pytest.raises(Exception):
            rec(0).final_direction = "benign"


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    import bench_memory_stress as B
    from test_decision_event import _isolate_bench
    mp = pytest.MonkeyPatch()
    _isolate_bench(B, mp, tmp_path_factory.mktemp("leak_iso"))
    yield B
    mp.undo()


class TestPrefixInvariance:
    @pytest.mark.parametrize("baseline", ["B1", "B2", "B2M", "B3"])
    def test_truncated_run_gives_identical_arbitration(self, bench, baseline):
        full = bench.run_stress_mode("A", bench.STRESS_FAMILIES, enable_defer=True,
                                     arbitration_baseline=baseline)
        fam = "concept_drift"
        idx = [s["id"] for s in bench.STRESS_FAMILIES[fam]].index("drift_06")
        trunc = {fam: bench.STRESS_FAMILIES[fam][:idx + 1]}
        part = bench.run_stress_mode("A", trunc, enable_defer=True, arbitration_baseline=baseline)
        f = next(e for e in full.decision_events if e.scenario_id == "drift_06")
        p = next(e for e in part.decision_events if e.scenario_id == "drift_06")
        assert f.arbitration_result == p.arbitration_result
        assert f.arbitration_request["slot_refs"] == p.arbitration_request["slot_refs"]
