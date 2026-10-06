"""B1 static / synthetic unit tests (no world simulation, no reserved seed root).

Pure-function checks on hand-made inputs only. World-level checks of the B1
arms are the §7b validation run (tools/run_lineage_b1_validation.py)."""

import ast
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lineage_b import b1_seeds, b1_stats as S  # noqa: E402
from lineage_b import params as P  # noqa: E402
from lineage_b.agent import predictor as pr  # noqa: E402
from lineage_b.agent.arms import (DependencyModel, consensus_reference, level_equivalent,  # noqa: E402
                                  to_sensor_units)
from lineage_b.b1_protocol import LockstepBarrier, derangement, refz_action, sham_validity_counts  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_constant_integrity():
    assert S.constant_integrity()["pass"]


def test_no_chi_square_engine():
    src = (ROOT / "lineage_b" / "b1_stats.py").read_text().lower()
    for word in ("lgamma", "gammainc", "incomplete", "bisect", "ppf"):
        assert word not in src


def test_seed_roots_and_tokens():
    assert b1_seeds.ROOTS == {"validation": 2026100517000, "sizing": 2026100516000,
                              "confirmatory": 2026100514000}
    with pytest.raises(b1_seeds.SeedFamilyError):
        b1_seeds.deployment_seeds("sizing", "wrong", "C0", 0)
    with pytest.raises(b1_seeds.SeedFamilyError):
        b1_seeds.bootstrap_rng("confirmatory", "wrong")


def test_derangement_properties():
    defer = [((0, t), a) for t, a in enumerate(["hold", "open", "close", "inspect", "hold", "hold"])]
    sham = derangement("X:0", defer)
    sv = sham_validity_counts(defer, sham)
    assert sv["sv1_marginals_equal"] and set(sham) == {k for k, _ in defer}
    # a cyclic shift in hash order moves every position
    order = sorted(defer, key=lambda it: __import__("hashlib").sha256(f"X:0|{it[0][1]}".encode()).hexdigest())
    for k, (key, _a) in enumerate(order):
        assert sham[key] == order[(k + 1) % len(order)][1]


def test_lockstep_barrier_requires_all_arms():
    b = LockstepBarrier(("G1", "G2"))
    b.register((0, 1), "G1", "a" * 64)
    assert b.hash_of((0, 1)) is None
    b.register((0, 1), "G2", "b" * 64)
    assert b.hash_of((0, 1)) is not None and b.clock_of((0, 1)) < b.tick()
    with pytest.raises(RuntimeError):
        b.register((0, 1), "G2", "c" * 64)


def test_level_equivalent_roundtrip():
    u, h = 0.5, 1.2
    for s, y in (("L3", h + 0.01), ("P", P.P_GAIN * h + 0.01), ("F", P.CV * u * math.sqrt(h))):
        he, v = level_equivalent(s, y, 0.0, P.NOMINAL_SIGMA[s], u)
        m, _ = to_sensor_units(s, he, v, u)
        assert abs(m - y) < 1e-12 and v > 0
    assert level_equivalent("F", 0.03, 0.0, 0.003, 0.0) is None


def test_consensus_is_leave_one_out_precision_weighted():
    params = lambda s: (0.0, {"L1": 0.01, "L2": 0.02}[s])
    m, v = consensus_reference("L3", {"L1": 1.0, "L2": 1.3, "L3": 9.0}, params, 0.5)
    w1, w2 = 1 / 0.01 ** 2, 1 / 0.02 ** 2
    assert abs(m - (w1 * 1.0 + w2 * 1.3) / (w1 + w2)) < 1e-12 and abs(v - 1 / (w1 + w2)) < 1e-15
    assert consensus_reference("L1", {"L1": 1.0}, params, 0.5) is None


def test_dependency_model_group_update_matches_g2_bias_when_both_present():
    m = DependencyModel()
    r = {"L1": 0.04, "L2": 0.02}
    m.update_group(r, 1e-4)
    # effective bias = b_g + d_i follows the per-sensor EWMA (b <- b + eta (r - b))
    for s in r:
        assert abs((m.b_g + m.d[s]) - P.ETA_B * r[s]) < 1e-15
    assert m.tau2 >= 0 and all(v > 0 for v in m.sig.values())


def test_dependency_model_relay_collapse():
    m = DependencyModel()
    m.note_relay("L4", "relay:L1")
    assert m.collapse({"L1": 1.0, "L4": 1.0}) == {"L1": 1.0}
    assert m.collapse({"L4": 1.1}) == {"L1": 1.1}
    assert m.params("L4", 0) == m.params("L1", 0)


def test_dependency_model_assimilate_shape_finite():
    m = DependencyModel()
    B, uf = m.assimilate(pr.initial_belief(), {"L1": 1.01, "L2": 0.99, "L3": 1.0}, 0.5, 0)
    assert not uf and np.isfinite(B.m).all() and abs(B.pi.sum() - 1) < 1e-12


def test_refz_action_valid_and_myopic():
    assert refz_action(1.7, 0.05, 0.5, "none") == "open"
    assert refz_action(0.3, 0.05, 0.5, "none") == "close"
    assert refz_action(1.0, 0.05, 0.5, "slow") in P.ACTIONS


def test_bootstrap_and_criteria_shapes():
    rng = np.random.default_rng(0)
    conds = ("C0",) + S.FAULT
    table = {c: {a: {m: rng.normal(1, 0.1, 8) for m in ("J", "unsafe_transition_rate", "false_safe_rate")}
                 for a in ("G0", "G1", "G2", "G2-S", "REF-S", "G3")} for c in conds}
    idx = S.bootstrap_indices(np.random.default_rng(1), {c: 8 for c in conds}, conds)
    out = S.criteria(table, idx, sv_ok=True)
    assert set(out) >= {"P0", "F1", "F2", "F3", "F4", "F5", "F6", "mapping"}
    for c in S.FAULT:
        p, lo, hi = out["F6"]["per_condition_J_G2_minus_G1"][c]
        assert lo <= hi


def test_blinded_sizing_emits_no_means():
    rng = np.random.default_rng(2)
    conds = ("C0",) + S.FAULT
    table = {c: {a: {m: list(rng.normal(5, 1, S.N_S)) for m in ("J", "unsafe_transition_rate", "false_safe_rate")}
                 for a in ("G0", "G1", "G2", "G2-S", "REF-S")} for c in conds}
    out = S.blinded_sizing(table)
    assert set(out) == S.SIZING_RECEIPT_KEYS
    for q in out["quantities"].values():
        assert set(q) == {"variance", "variance_ucl", "ucl", "z", "h", "N_q"}
    hp0 = [q["h"] for n, q in out["quantities"].items() if n == "P0"]
    assert hp0 == [0.5 * S.DELTA_STAR] and abs(hp0[0] - 0.8685) < 1e-12
    assert all(q["z"] == 1.96 for q in out["quantities"].values())


def test_frozen_placeholders_unset():
    from lineage_b import b1_frozen
    assert b1_frozen.N is None and b1_frozen.CONFIRMATORY_SEED_LIST_SHA256 is None


def test_arms_module_never_touches_authority_or_world():
    tree = ast.parse((ROOT / "lineage_b" / "agent" / "arms.py").read_text())
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(m and ("world" in m or "sensors" in m or "authority" in m or "harness" in m) for m in mods)
