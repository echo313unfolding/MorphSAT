"""A4V — invariants I1–I6 and structural facts (A4V prereg v1.1 §3.1, §5)."""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lineage_a import a4v as v
from lineage_a.evaluate_a4v import EXPECTED_COUNTS, decide, structural_counts
from lineage_a.generator import fam_g, fam_i, fam_t
from lineage_a.policies import ABSTAIN, ACCEPT, a4_corroboration, shuffle_ids
from lineage_a.records import ObservationRecord as R

ROOT = Path(__file__).resolve().parent.parent / "lineage_a"
G, T = fam_g(), fam_t()
ALL = G + T
C = lambda o, d, s, u: R(o, d, s, u, True)


@pytest.mark.parametrize("fn", [v.a4v, v.a4v_wide, v.a4v_corr_alias, v.a4v_other_alias])
def test_I1_I2_I4_only_accept_to_abstain(fn):
    for p in ALL:
        a4, x = a4_corroboration(p.records), fn(p.records)
        assert x in (a4, ABSTAIN)
        if x != a4:
            assert a4 == ACCEPT


def test_I2_I3_change_iff_veto_condition():
    for p in ALL:
        changed = v.a4v(p.records) != a4_corroboration(p.records)
        assert changed == v.alias_veto_fires(p.records)


def test_sham_changes_only_veto_set():
    for p in ALL:
        assert a4_corroboration(shuffle_ids(p.pid, p.records)) == a4_corroboration(p.records)
        s = v.a4v_shuffle_sham(p.records, p.pid)
        assert s in (a4_corroboration(p.records), ABSTAIN)


def test_I5_no_new_threshold():
    src = (ROOT / "a4v.py").read_text()
    tree = ast.parse(src)
    nums = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
            and isinstance(n.value, (int, float)) and not isinstance(n.value, bool)}
    assert nums <= {0, 1}             # subtype split only (n_up == 0 / == 1)
    assert "from lineage_a.policies import" in src and " K" in src


def test_I6_no_oracle():
    tree = ast.parse((ROOT / "a4v.py").read_text())
    forbidden = {"x_pre", "drift", "adversarial", "q", "env", "family", "label", "ground_truth",
                 "posterior", "world", "meta"}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {a.arg for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) for a in n.args.args}
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not names & forbidden
    assert "lineage_a.world" not in mods and "lineage_a.evaluate" not in mods


def test_structural_counts_match_prereg():
    i_set = fam_i(G)
    dec = {p.pid: decide(p) for p in ALL}
    got = structural_counts({"FAM-G": G, "FAM-T": T, "FAM-I": i_set}, dec)
    assert {k: tuple(x) for k, x in got.items()} == EXPECTED_COUNTS


def test_veto_structures():
    vetoed = {p.meta["structure"] for p in ALL if v.alias_veto_fires(p.records)}
    assert vetoed == {"B-corr", "B-oth", "shared-upstream"}


class TestCases:
    def test_b_corr_aliases_vetoed(self):
        r = [C(0, "benign", "S_c", "U_c"), R(1, "benign", "S_q0", "U_c"), R(2, "benign", "S_q1", "U_c")]
        assert a4_corroboration(r) == ACCEPT and v.a4v(r) == ABSTAIN
        assert v.a4v_corr_alias(r) == ABSTAIN and v.a4v_other_alias(r) == ACCEPT

    def test_b_oth_vetoed(self):
        r = [C(0, "benign", "S_c", "U_c"), R(1, "benign", "S_q0", "U_x"), R(2, "benign", "S_q1", "U_x")]
        assert v.a4v(r) == ABSTAIN and v.a4v_other_alias(r) == ABSTAIN and v.a4v_corr_alias(r) == ACCEPT

    def test_independent_not_vetoed(self):
        r = [C(0, "benign", "S_c", "U_c"), R(1, "benign", "S_q0", "U_q0"), R(2, "benign", "S_q1", "U_q1")]
        assert v.a4v(r) == ACCEPT

    def test_repeats_not_vetoed_by_a4v_but_by_wide(self):
        for sid, uid in (("S_c", "U_c"), ("S_x", "U_x")):
            r = [C(0, "benign", "S_c", "U_c"), R(1, "benign", sid, uid), R(2, "benign", sid, uid)]
            assert v.a4v(r) == ACCEPT and v.a4v_wide(r) == ABSTAIN

    def test_reject_untouched(self):
        r = [C(0, "benign", "S_c", "U_c"), R(1, "threat", "S_q0", "U_x"), R(2, "threat", "S_q1", "U_x")]
        assert a4_corroboration(r) == v.a4v(r) == v.a4v_wide(r)
