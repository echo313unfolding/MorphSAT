"""Lineage A — required tests (prereg v1.3 Amendment 3) and unit tests."""

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lineage_a import corollary as cor
from lineage_a.generator import fam_g, fam_i, fam_t
from lineage_a.policies import (
    ABSTAIN, ACCEPT, REJECT, a1_majority, a2_recency, a3b_frozen_b3,
    a4_corroboration, a5_independent, a5n_naive, s1_count_sham, shuffle_ids,
)
from lineage_a.records import DeclaredRecord, ObservationRecord as R, Pattern, declared_view
from lineage_a.world import ENVS, Env, posterior

ROOT = Path(__file__).resolve().parent.parent / "lineage_a"


def pat(recs):
    return Pattern("t", "X", "t", tuple(recs))


class TestGenerator:
    def test_counts(self):
        g, t = fam_g(), fam_t()
        assert (len(g), len(t), len(fam_i(g))) == (248, 54, 20)

    def test_famt_placement_only_within_cell(self):
        t = fam_t()
        for s in ("repeated", "shared-upstream", "independent"):
            for b in (1, 2, 3):
                ps = [p for p in t if p.meta["structure"] == s and p.meta["b"] == b and p.meta["c"] == "benign"]
                ms = {tuple(sorted((r.direction, r.source_id, r.upstream_id) for r in p.records)) for p in ps}
                assert len(ms) == 1 and len(ps) == b + 1

    def test_fam_i_structures(self):
        assert {p.meta["structure"] for p in fam_i()} == {"A-corr", "B-corr", "A-oth", "B-oth", "C"}

    def test_b_corr_aliases_share_correction_upstream(self):
        p = next(p for p in fam_g() if p.meta["structure"] == "B-corr" and p.meta["n_post"] == 3)
        post = [r for r in p.records if r.order > p.correction.order]
        assert len({r.source_id for r in post}) == 3 and {r.upstream_id for r in post} == {"U_c"}


class TestWorld:
    def test_singleton_upstream_is_independent_reading(self):
        recs = [R(0, "threat", "S_p0", "U_p0"), R(1, "benign", "S_c", "U_c", True)]
        q = {posterior(pat(recs), Env(0.7, 0.5, rho, 0.0))["q"] for rho in (0.0, 0.5, 1.0)}
        assert max(q) - min(q) < 1e-12

    def test_rho1_copies_count_once(self):
        base = [R(0, "threat", "S_p0", "U_p0"), R(1, "benign", "S_c", "U_c", True),
                R(2, "benign", "S_x", "U_x")]
        rep = base + [R(3, "benign", "S_x", "U_x"), R(4, "benign", "S_x", "U_x")]
        e = Env(0.7, 0.5, 1.0, 0.0)
        assert abs(posterior(pat(base), e)["q"] - posterior(pat(rep), e)["q"]) < 1e-12
        e0 = Env(0.7, 0.5, 0.0, 0.0)
        assert posterior(pat(rep), e0)["q"] > posterior(pat(base), e0)["q"]

    def test_adversary_raises_mc_mass(self):
        recs = [R(0, "threat", "S_p0", "U_p0"), R(1, "benign", "S_c", "U_c", True),
                R(2, "benign", "S_q0", "U_c"), R(3, "benign", "S_q1", "U_c")]
        assert posterior(pat(recs), Env(0.9, 0.2, 1.0, 0.0))["mc"] == 0.0
        assert posterior(pat(recs), Env(0.9, 0.2, 1.0, 0.3))["mc"] > 0.0

    def test_impossible_pattern_gets_zero_weight(self):
        from lineage_a.evaluate import weights
        bad = [R(0, "threat", "S_p0", "U_p0"), R(1, "benign", "S_c", "U_c", True), R(2, "threat", "S_c", "U_c")]
        good = [R(0, "threat", "S_p0", "U_p0"), R(1, "benign", "S_c", "U_c", True), R(2, "benign", "S_c", "U_c")]
        pb, pg = Pattern("bad", "X", "cell", tuple(bad)), Pattern("good", "X", "cell", tuple(good))
        e = Env(0.7, 0.5, 1.0, 0.0)
        posts = {"bad": posterior(pb, e), "good": posterior(pg, e)}
        assert posts["bad"]["Z"] == 0.0 and posts["bad"]["q"] is None
        assert weights([pb, pg], posts) == {"bad": 0.0, "good": 1.0}

    def test_grid(self):
        assert len(ENVS) == 24 and {e.rho for e in ENVS} == {0.0, 0.5, 1.0}


C = lambda o, d, s, u: R(o, d, s, u, True)


class TestPolicies:
    def test_majority_share(self):
        recs = [R(0, "threat", "a", "a"), C(1, "benign", "S_c", "U_c"), R(2, "benign", "b", "b"), R(3, "benign", "d", "d")]
        assert a1_majority(recs) == ACCEPT
        assert a1_majority(recs[:3]) == ABSTAIN

    def test_recency(self):
        assert a2_recency([C(0, "benign", "S_c", "U_c"), R(1, "threat", "x", "x")]) == REJECT

    def test_b3_removes_earlier_opposite(self):
        recs = [R(0, "threat", "a", "a"), R(1, "threat", "b", "b"), C(2, "benign", "S_c", "U_c"), R(3, "benign", "x", "x")]
        assert a3b_frozen_b3(recs) == ACCEPT

    def test_a4_a5_a5n_on_b_corr(self):
        recs = [C(0, "benign", "S_c", "U_c"), R(1, "benign", "S_q0", "U_c"), R(2, "benign", "S_q1", "U_c")]
        assert a4_corroboration(recs) == ACCEPT
        assert a5n_naive(recs) == ACCEPT       # fooled by aliases
        assert a5_independent(recs) == ABSTAIN  # not fooled

    def test_a5_independent_support(self):
        recs = [C(0, "benign", "S_c", "U_c"), R(1, "benign", "S_q0", "U_q0"), R(2, "benign", "S_q1", "U_q1")]
        assert a5_independent(recs) == ACCEPT

    def test_a5_contradiction(self):
        recs = [C(0, "benign", "S_c", "U_c"), R(1, "threat", "a", "a"), R(2, "threat", "b", "b")]
        assert a5_independent(recs) == REJECT

    def test_s1_direction_blind(self):
        recs = [C(0, "benign", "S_c", "U_c"), R(1, "threat", "a", "a"), R(2, "threat", "b", "b")]
        assert s1_count_sham(recs) == ACCEPT

    def test_shuffle_preserves_marginals(self):
        p = next(p for p in fam_g() if p.meta["structure"] == "C" and p.meta["n_post"] == 3 and p.meta["n_pre"] == 3)
        sh = shuffle_ids(p.pid, p.records)
        key = lambda rs: sorted((r.source_id, r.upstream_id) for r in rs)
        assert [(r.order, r.direction, r.is_correction) for r in sh] == \
               [(r.order, r.direction, r.is_correction) for r in p.records]
        assert key(sh) == key(p.records)
        assert sh[p.records.index(p.correction)] == p.correction
        assert [(r.source_id, r.upstream_id) for r in sh] != [(r.source_id, r.upstream_id) for r in p.records]


class TestCorollaryComparators:
    def test_declared_view_has_no_upstream(self):
        dv = declared_view([R(0, "benign", "s", "u", True)])
        assert not hasattr(dv[0], "upstream_id")
        assert cor.c1_declared_origin(dv) == ACCEPT

    def test_comparator_module_never_references_upstream(self):
        tree = ast.parse((ROOT / "corollary.py").read_text())
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
                {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert not any("upstream" in str(x) for x in names)

    def D(self, o, d, s, corr=False):
        return DeclaredRecord(o, d, s, corr)

    def test_credit_rules(self):
        recs = [self.D(0, "benign", "S_c", True),
                self.D(1, "benign", "S_c"),        # repeat: no credit
                self.D(2, "benign", "S_a")]        # confirmation: credit S_c and S_a
        rel = cor.c2_reliabilities(recs)
        up = (0.95 * 10 + 1) / 11
        assert rel["S_c"] == pytest.approx(up) and rel["S_a"] == pytest.approx(up)
        assert cor.c2_reliabilities(recs[:2])["S_c"] == 0.95   # first assertion + repeat: none

    def test_aliases_inflate_c1_and_c2(self):
        aliases = [self.D(0, "threat", "S_p0"), self.D(1, "threat", "S_p1"), self.D(2, "benign", "S_c", True),
                   self.D(3, "benign", "S_q0"), self.D(4, "benign", "S_q1")]
        assert cor.c1_declared_origin(aliases) == ACCEPT      # 3 apparent origins vs 2
        assert cor.c2_agreement_credit(aliases) == ACCEPT

    def test_tie_goes_to_newest_value(self):
        recs = [self.D(0, "threat", "S_p0"), self.D(1, "benign", "S_c", True)]
        assert cor.c1_declared_origin(recs) == ACCEPT


class TestNoOracle:
    FORBIDDEN = {"x_pre", "drift", "adversarial", "q", "env", "family", "label", "ground_truth",
                 "posterior", "world", "meta"}

    @pytest.mark.parametrize("mod", ["policies.py", "corollary.py"])
    def test_policy_modules_cannot_see_truth(self, mod):
        tree = ast.parse((ROOT / mod).read_text())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
                {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
                {a.arg for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) for a in n.args.args}
        imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} | \
                  {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not names & self.FORBIDDEN
        assert "lineage_a.world" not in imports and "lineage_a.evaluate" not in imports
