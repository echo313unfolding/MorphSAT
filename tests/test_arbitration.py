"""P3 — arbitration policy, thresholds, projections (prereg v2 §5/§7, v2.1 A1/A4)."""

import ast
import hashlib
from pathlib import Path

import pytest

from morphsat.arbitration import (
    ArbitrationRequest, arbitrate, sham_mask, supersession_exclusions,
)
from morphsat.canonical_history import HistoryRecord

ROOT = Path(__file__).resolve().parent.parent


def rec(i, action="COMMIT", d="escalate", lean=None, sup=(), corr=False, run="F"):
    return HistoryRecord(f"r{i}", run, i, f"{run}/s{i}", ("alpha", "beta"), (),
                         action, d if action == "COMMIT" else None,
                         lean or (d if action == "COMMIT" and d != "suspicious" else "neutral"),
                         corr, tuple(sup), "monitor")


def req(slots, baseline="B2", t=0.2, s=0.3, sig=(("t", "clean"),), order=10, key="F/target"):
    return ArbitrationRequest("F", order, key, "X/F/010/target", baseline, "HARNESS_END",
                              t, s, min(t, s), tuple(sig), ("alpha", "beta"), tuple(slots))


class TestThresholds:
    @pytest.mark.parametrize("n,agree,expect", [
        (2, 2, "COMMIT"), (2, 1, "ABSTAIN"), (3, 3, "COMMIT"), (3, 2, "ABSTAIN"),
        (4, 3, "COMMIT"), (4, 2, "ABSTAIN"), (5, 4, "COMMIT"), (5, 3, "ABSTAIN")])
    def test_table(self, n, agree, expect):
        slots = [rec(i, d="escalate") for i in range(agree)] + \
                [rec(i, d="suspicious") for i in range(agree, n)]
        assert arbitrate(req(slots, t=0.3, s=0.1)).action == expect

    def test_uncertainty_in_denominator(self):
        pass3_1 = [rec(0), rec(1), rec(2), rec(3, action="ABSTAIN")]
        assert arbitrate(req(pass3_1, t=0.3, s=0.1)).share == 0.75
        assert arbitrate(req(pass3_1, t=0.3, s=0.1)).action == "COMMIT"
        fail = [rec(0), rec(1), rec(2, action="ABSTAIN")]
        assert arbitrate(req(fail, t=0.3, s=0.1)).action == "ABSTAIN"

    def test_ineligible_and_b0(self):
        assert arbitrate(req([rec(0)])).action == "ABSTAIN"
        assert arbitrate(req([rec(0), rec(1)], baseline="B0")).action == "ABSTAIN"
        assert arbitrate(req([rec(0), rec(1)], baseline="B0")).records_used == ()


class TestBenignGuard:
    def benign(self, **kw):
        return arbitrate(req([rec(0, d="benign"), rec(1, d="benign")], **kw))

    def test_passes_at_exact_zero(self):
        assert self.benign(t=0.0925, s=0.0925).action == "COMMIT"

    def test_blocked_positive_balance(self):
        assert self.benign(t=0.30, s=0.29).action == "ABSTAIN"

    @pytest.mark.parametrize("cat", ["yara_match", "unexpected", "outbound_port", "critical_cve",
                                     "not_in_known_good", "unsigned", "obfuscated",
                                     "persistence", "lateral_movement"])
    def test_blocked_by_live_threat_category(self, cat):
        assert self.benign(t=0.1, s=0.3, sig=(("t", cat),)).action == "ABSTAIN"

    @pytest.mark.parametrize("cat", ["ambiguous", "moderate_signal", "unknown"])
    def test_ambiguous_categories_do_not_block(self, cat):
        assert self.benign(t=0.1, s=0.3, sig=(("t", cat),)).action == "COMMIT"

    def test_escalate_not_guarded(self):
        assert arbitrate(req([rec(0), rec(1)], t=0.1, s=0.3)).direction == "escalate"


class TestProjections:
    def test_b1_uses_lean_only(self):
        slots = [rec(0, d="escalate", lean="benign"), rec(1, d="escalate", lean="benign")]
        assert arbitrate(req(slots, "B1", t=0.1, s=0.3)).direction == "benign"
        assert arbitrate(req(slots, "B2", t=0.1, s=0.3)).direction == "escalate"

    def test_b1_neutral_is_uncertainty(self):
        assert arbitrate(req([rec(0, lean="neutral"), rec(1, lean="neutral")], "B1")).n_uncertain == 2

    def test_same_slots_all_baselines(self):
        slots = [rec(0), rec(1), rec(2, d="benign", corr=True, sup=("r0", "r1"))]
        for b in ("B1", "B2", "B2M", "B3"):
            r = arbitrate(req(slots, b))
            assert set(r.records_used) | {x for x, _ in r.records_excluded} == {"r0", "r1", "r2"}

    def test_b3_supersession_no_backfill(self):
        slots = [rec(0), rec(1), rec(2, d="benign", corr=True, sup=("r0", "r1"))]
        assert supersession_exclusions(tuple(slots)) == ["r0", "r1"]
        r = arbitrate(req(slots, "B3"))
        assert r.records_used == ("r2",) and r.action == "ABSTAIN"   # 1 directional < 2

    def test_b2_ignores_supersedes(self):
        slots = [rec(0), rec(1), rec(2, d="benign", corr=True, sup=("r0", "r1"))]
        assert arbitrate(req(slots, "B2")).records_excluded == ()

    def test_b2m_masks_same_count_by_frozen_hash(self):
        slots = [rec(0), rec(1), rec(2, d="benign", corr=True, sup=("r0", "r1"))]
        r = arbitrate(req(slots, "B2M"))
        assert len(r.records_excluded) == 2 and all(x[1] == "sham_mask" for x in r.records_excluded)
        rank = sorted(slots, key=lambda s: hashlib.sha256(f"F/target|{s.episode_key}".encode()).hexdigest())
        assert [x for x, _ in r.records_excluded] == [s.outcome_ref for s in rank[:2]]
        assert sham_mask("F/target", tuple(slots), 0) == []

    def test_result_cites_refs_and_hash_deterministic(self):
        r1 = arbitrate(req([rec(0), rec(1)])); r2 = arbitrate(req([rec(0), rec(1)]))
        assert r1.records_used == ("r0", "r1") and r1.result_hash == r2.result_hash


class TestNoOracle:
    FORBIDDEN = {"category", "ground_truth", "has_correction_tools", "scored_as",
                 "evaluation", "expected", "scenario"} | {
                 "drift_like", "stale_memory_like", "poisoned_memory_like",
                 "sensor_graph_conflict", "routing_triggered"}

    @pytest.mark.parametrize("mod", ["arbitration.py", "canonical_history.py"])
    def test_no_oracle_identifiers(self, mod):
        tree = ast.parse((ROOT / "morphsat" / mod).read_text())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
                {a.arg for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) for a in n.args.args} | \
                {n.target.id for n in ast.walk(tree) if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
        assert not names & self.FORBIDDEN
