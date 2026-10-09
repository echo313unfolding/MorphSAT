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
from lineage_b.b1_protocol import (LockstepBarrier, max_mismatch_sham, max_mismatches, refz_action,  # noqa: E402
                                   sham_validity_counts)

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


def _defer_from_counts(counts):
    acts = [a for a, n in zip(P.ACTIONS, counts) for _ in range(n)]
    order = np.random.default_rng(sum(c * 7 ** i for i, c in enumerate(counts))).permutation(len(acts))
    return [((k // 200, k % 200), acts[o]) for k, o in enumerate(order)]


def test_sham_exhaustive_counts_and_maximum_mismatch():
    import itertools
    checked = 0
    for counts in itertools.product(range(6), repeat=4):
        n = sum(counts)
        if n < 2:
            continue
        defer = _defer_from_counts(counts)
        sham = max_mismatch_sham("X:C2:0", defer)
        sv = sham_validity_counts(defer, sham)
        assert sv["sv1_marginals_equal"] and set(sham) == {k for k, _ in defer}
        assert sv["n_differ"] == max_mismatches(defer) == min(n, 2 * (n - max(counts)))
        assert sham == max_mismatch_sham("X:C2:0", defer)            # deterministic
        checked += 1
    assert checked == 6 ** 4 - 5


def test_sham_sv3_feasibility_boundary():
    # p_max <= 0.60 is exactly the condition under which >= 80% mismatch is attainable
    for counts, ok in (((6, 4, 0, 0), True), ((7, 3, 0, 0), False), ((3, 3, 2, 2), True)):
        defer = _defer_from_counts(counts)
        sv = sham_validity_counts(defer, max_mismatch_sham("X:C0:1", defer))
        assert (sv["n_differ"] / sv["n"] >= 0.80) == ok


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


# ---------------------------------------------------------------- v1.5.1 §2 order invariance
from lineage_b.agent.arms import B1Agent  # noqa: E402
from lineage_b.agent.sensor_model import SensorModel  # noqa: E402
from lineage_b.obs import Record  # noqa: E402
from lineage_b.params import DECLARED_UPSTREAM as DU  # noqa: E402
from lineage_b.receipts import ReceiptStore  # noqa: E402


def _batch(t):
    vals = {"L1": 1.02, "L2": 0.99, "L3": 1.05, "F": 0.051, "P": 9.70}
    out = [Record(s, 2 * t, t, t, v + 0.003 * t, DU[s]) for s, v in vals.items()]
    out.append(Record("L4", t, t, t, vals["L1"] + 0.003 * t, DU["L4"]))
    if t >= 2:
        out.append(Record("L3", 2 * t + 1, t - 2, t, 1.07, DU["L3"]))     # late record, same sensor in batch
    return out


def _run(updater, model, permute):
    ag = B1Agent(model, updater, arm="X")
    ag.begin_episode(0, 0, ReceiptStore())
    for t in range(6):
        b = _batch(t)
        if permute and t == 5:
            b = list(reversed(b))
        ag.observe(t, b)
        ag.commit_prediction(t, "hold")
    return ag


@pytest.mark.parametrize("updater,factory", [("consensus", SensorModel), ("receipt", SensorModel),
                                             ("receipt", DependencyModel)])
def test_batch_permutation_invariance(updater, factory):
    a, b = _run(updater, factory(), False), _run(updater, factory(), True)
    assert a.model.theta_hash() == b.model.theta_hash()
    if updater == "consensus":
        assert a.g1_refs == b.g1_refs and any(r is not None for _, r in a.g1_refs)


def test_g1_reference_uses_pre_batch_snapshot():
    ag = _run("consensus", SensorModel(), False)
    before = {s: tuple(ag.model.params(s, 0)) for s in ("L1", "L2", "L3", "F", "P", "L4")}
    n0 = len(ag.g1_refs)
    ag.observe(6, _batch(6))
    snap_refs = ag.g1_refs[n0:]
    # recompute every reference of that batch from the pre-batch parameters
    from lineage_b.agent.arms import consensus_reference
    seen = {**{r.key: r for r in ag.records.values()}}
    for key, ref in snap_refs:
        rec = seen[key]
        others = {x.sensor_id: x.value for x in seen.values() if x.measured_at == rec.measured_at
                  and x.sensor_id not in ("INSPECT", rec.sensor_id)}
        assert ref == consensus_reference(rec.sensor_id, others, lambda s: before[s], ag.u_hist[rec.measured_at])


# ---------------------------------------------------------------- v1.5.1 §9 precedence
def _o(p0=True, f1=True, f2=True, f3=True, f3v=True, f4=True, f5=True, f6=True, below=False):
    return {"P0": {"pass": p0}, "F1": {"pass": f1, "ci_upper_below_delta_star": below},
            "F2": {"pass": f2}, "F3": {"pass": f3 if f3v else None, "valid": f3v},
            "F4": {"pass": f4}, "F5": {"pass": f5}, "F6": {"pass": f6}}


def test_outcome_mapping_precedence():
    m = S.outcome_mapping
    assert m(_o(p0=False, f4=False)).startswith("Uninformative")
    assert m(_o(f1=False, below=True, f4=False)).startswith("The preregistered")
    assert m(_o(f1=False, below=False)).startswith("Inconclusive")
    assert m(_o(f3v=False, f4=False)).startswith("No positive claim")          # harm before sham-invalid
    assert m(_o(f3=False, f6=False)).startswith("No positive claim")           # harm before F3-not-isolated
    assert m(_o(f3v=False)).startswith("No ceiling claim; F1/F2 reported")
    assert m(_o(f3=False)).startswith("Observation-based")
    assert m(_o()).startswith("Claim at")
    assert m(_o(f2=False)).startswith("No ceiling claim; F1 holds but F2 fails")


# ---------------------------------------------------------------- v1.5.1 §7, §8 run control
from lineage_b import b1_runctl as rc  # noqa: E402

_FROZEN_OK = '''"""doc"""\nN = 812\nCONFIRMATORY_SEED_LIST_SHA256 = "abc"\nSIZING_RECEIPT = "receipts/x.json"\n'''


def test_post_sizing_freeze_verifier():
    files = {"lineage_b/a.py": "1", rc.FROZEN_FILE: "old"}
    ok = rc.verify_post_sizing_freeze(files, {**files, rc.FROZEN_FILE: "new"}, _FROZEN_OK, 812, "abc", "receipts/x.json")
    assert ok["pass"]
    bad = rc.verify_post_sizing_freeze(files, {**files, "lineage_b/a.py": "2"}, _FROZEN_OK, 812, "abc", "receipts/x.json")
    assert not bad["pass"]
    assert not rc.verify_post_sizing_freeze(files, files, _FROZEN_OK, 813, "abc", "receipts/x.json")["pass"]
    assert not rc.verify_post_sizing_freeze(files, files, _FROZEN_OK + "X = 1\n", 812, "abc", "receipts/x.json")["pass"]
    assert not rc.verify_post_sizing_freeze(files, {**files, "lineage_b/new.py": "3"}, _FROZEN_OK, 812, "abc",
                                            "receipts/x.json")["pass"]


def test_one_shot_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "RECEIPTS", tmp_path)
    rc.require_one_shot("b1_sizing")                          # nothing yet
    (tmp_path / "b1_sizing_STARTED_20261007T000000Z.json").write_text("{}")
    with pytest.raises(SystemExit):
        rc.require_one_shot("b1_sizing")


def test_protected_files_cover_runners_and_authority():
    names = {str(p.relative_to(rc.ROOT)) for p in rc.protected_files()}
    assert {"lineage_b/b1_frozen.py", "lineage_b/agent/predictor.py", "morphsat/terminal_authority.py",
            "tools/run_lineage_b1_sizing.py", "tools/run_lineage_b1_confirmatory.py"} <= names


# ---------------------------------------------------------------- v1.5.1 §5 provenance
def test_behavior_records_keep_proposal_and_logged_action_apart():
    from lineage_b.b1_events import BEHAVIOR_ARM, behavior_records
    evs, calls = _behavior_log(n=200, interlock_at=())
    recs = behavior_records("X:C0:0", evs, calls)
    assert all(r.behavior_arm == BEHAVIOR_ARM and r.controller_proposal == "hold" for r in recs)
    assert any(r.logged_action != r.controller_proposal for r in recs)
    assert all(r.logged_action == e.final_action for r, e in zip(recs, evs))


# ---------------------------------------------------------------- v1.5.2 §1 provenance
from types import SimpleNamespace  # noqa: E402

from lineage_b.b1_events import (BEHAVIOR_ARM, ProvenanceError, RecordingPolicy,  # noqa: E402
                                 behavior_records, verify_provenance)
from lineage_b.events import ControlDecisionEvent  # noqa: E402


def _behavior_log(n=60, interlock_at=(7, 8)):
    pol = RecordingPolicy(np.random.default_rng(5))
    evs = []
    for k in range(n):
        ep, t = divmod(k, 20)
        if k in interlock_at:
            act, p, rnd = pol.choose("hold", False)
            evs.append(ControlDecisionEvent("X", ep, t, BEHAVIOR_ARM, {}, "COMMIT", "open", True, "interlock",
                                            {}, None, "open", "none", "th", "rh", p, rnd, "v"))
        else:
            act, p, rnd = pol.choose("hold", True)
            evs.append(ControlDecisionEvent("X", ep, t, BEHAVIOR_ARM, {}, "DEFER", None, False, "arbitration",
                                            {}, act, act, "arbitration", "th", "rh", p, rnd, "v"))
    return evs, pol.calls


def test_behavior_records_accept_wellformed():
    evs, calls = _behavior_log()
    recs = behavior_records("X", evs, calls)
    assert len(recs) == len(evs)
    assert any(r.logged_action != r.controller_proposal for r in recs)


@pytest.mark.parametrize("mutate", ["arm", "order", "propensity", "randomized", "final", "nonarb_rnd", "count"])
def test_behavior_records_reject_malformed(mutate):
    import dataclasses
    evs, calls = _behavior_log()
    calls = list(calls)
    k = 10
    if mutate == "arm":
        evs[k] = dataclasses.replace(evs[k], arm="G2")
    elif mutate == "order":
        evs[k], evs[k + 1] = evs[k + 1], evs[k]
        calls[k], calls[k + 1] = calls[k + 1], calls[k]
    elif mutate == "propensity":
        evs[k] = dataclasses.replace(evs[k], propensity=0.5)
    elif mutate == "randomized":
        evs[k] = dataclasses.replace(evs[k], randomized=not evs[k].randomized)
    elif mutate == "final":
        other = "close" if evs[k].final_action != "close" else "open"
        evs[k] = dataclasses.replace(evs[k], final_action=other)
    elif mutate == "nonarb_rnd":
        calls[7] = (calls[7][0], calls[7][1], 0.8, True)
    elif mutate == "count":
        calls = calls[:-1]
    with pytest.raises(ProvenanceError):
        behavior_records("X", evs, calls)


def test_verify_provenance_links_and_detects_breaks():
    import dataclasses
    evs, calls = _behavior_log()
    recs = behavior_records("X", evs, calls)
    by_key = {(e.episode, e.t): e for e in evs}
    payloads = {(ep, t + 1): {"decision_key": [ep, t]} for (ep, t) in by_key}
    fb = [SimpleNamespace(receipt_key=(ep, t + 1), decision_ref=e.canonical_hash, sensor_id="L1", seq=t)
          for (ep, t), e in by_key.items()]
    assert verify_provenance(recs, by_key, fb, payloads.__getitem__)["pass"]
    bad_fb = fb[:5] + [SimpleNamespace(**{**vars(fb[5]), "decision_ref": "0" * 64})] + fb[6:]
    assert not verify_provenance(recs, by_key, bad_fb, payloads.__getitem__)["pass"]
    bad_recs = recs[:3] + [dataclasses.replace(recs[3], propensity=0.123)] + recs[4:]
    assert not verify_provenance(bad_recs, by_key, fb, payloads.__getitem__)["pass"]
    foreign = dict(by_key)
    k0 = next(iter(foreign))
    foreign[k0] = dataclasses.replace(foreign[k0], arm="G1")
    assert not verify_provenance(recs, foreign, fb, payloads.__getitem__)["pass"]


# ---------------------------------------------------------------- v1.5.2 §2 final G3 flush
def _g3_with_open_slot():
    ag = B1Agent(DependencyModel(), "receipt", arm="G3")
    ag.begin_episode(0, 0, ReceiptStore())
    for t in range(4):
        b = [r for r in _batch(t) if not (t == 3 and r.sensor_id == "L2")]     # L2 absent at the last step
        ag.observe(t, b)
        ag.commit_prediction(t, "hold")
    ag.observe(4, [r for r in _batch(4) if r.sensor_id == "L1" and r.measured_at == 4])   # L1 at 4, slot open
    return ag


def test_g3_final_flush_closes_open_slot_once():
    ag = _g3_with_open_slot()
    assert ag.pending_group
    before = ag.model.theta_hash()
    n = ag.finalize_learning()
    assert n >= 1 and not ag.pending_group and ag.model.theta_hash() != before
    assert any(e.get("at") == "end_of_learning" for e in ag.log)
    after = ag.model.theta_hash()
    with pytest.raises(RuntimeError):
        ag.finalize_learning()
    with pytest.raises(RuntimeError):
        ag.begin_episode(1, 200, ReceiptStore())
    assert ag.model.theta_hash() == after


@pytest.mark.parametrize("updater", ["consensus", "receipt", "sham"])
def test_finalize_is_noop_for_g1_g2_g2s(updater):
    ag = _run(updater if updater != "sham" else "receipt", SensorModel(), False) if updater != "sham" else None
    if ag is None:
        ag = B1Agent(SensorModel(), "sham", arm="G2-S")
        ag.begin_episode(0, 0, ReceiptStore())
        for t in range(4):
            ag.observe(t, _batch(t))
            ag.commit_prediction(t, "hold")
    h = ag.model.theta_hash()
    assert ag.finalize_learning() == 0 and ag.model.theta_hash() == h


# ---------------------------------------------------------------- v1.5.2 §3 record directory
import pickle  # noqa: E402


def test_require_empty_outdir(tmp_path):
    rc.require_empty_outdir(tmp_path / "new")
    rc.require_empty_outdir(tmp_path)
    (tmp_path / "x.txt").write_text("stale")
    with pytest.raises(SystemExit):
        rc.require_empty_outdir(tmp_path)


def test_verify_record_set(tmp_path):
    load = lambda f: pickle.loads(f.read_bytes())
    conds = ("C0", "C1")
    for c in conds:
        for d in range(2):
            (tmp_path / f"A_{c}_{d:05d}.pkl").write_bytes(pickle.dumps({"condition": c, "deployment": f"confirmatory:{c}:{d}"}))
    assert rc.verify_record_set(tmp_path, ("A",), conds, 2, load)["pass"]
    (tmp_path / "B_C0_00000.pkl").write_bytes(pickle.dumps({"condition": "C0", "deployment": "confirmatory:C0:0"}))
    assert not rc.verify_record_set(tmp_path, ("A",), conds, 2, load)["pass"]             # unexpected extra
    assert not rc.verify_record_set(tmp_path, ("A", "B"), conds, 2, load)["pass"]         # missing B files
    (tmp_path / "B_C0_00000.pkl").unlink()
    (tmp_path / "A_C1_00001.pkl").write_bytes(pickle.dumps({"condition": "C0", "deployment": "confirmatory:C0:1"}))
    assert not rc.verify_record_set(tmp_path, ("A",), conds, 2, load)["pass"]             # embedded mismatch


# ---------------------------------------------------------------- v1.5.3 seed immutability (B. tests)
from lineage_b.b1_seeds import b1_make_streams, fresh_seedsequence  # noqa: E402
from lineage_b.world import STREAMS  # noqa: E402


def _arbitrary_episode_seed(entropy=99999, spawn_idx=0):
    """An arbitrary, non-reserved SeedSequence for testing."""
    root = np.random.SeedSequence(entropy=entropy, spawn_key=(0, 0))
    world_ss, _ = root.spawn(2)
    return world_ss.spawn(10)[spawn_idx]


def test_b1_make_streams_identical_on_same_spec():
    """Two calls to b1_make_streams on the same episode seed produce
    byte/value-identical streams."""
    ss = _arbitrary_episode_seed()
    s1 = b1_make_streams(ss)
    s2 = b1_make_streams(ss)
    assert set(s1) == set(s2) == set(STREAMS)
    for name in STREAMS:
        v1 = s1[name].random(100)
        v2 = s2[name].random(100)
        assert np.array_equal(v1, v2), f"stream {name!r} differs"


def test_b1_make_streams_does_not_mutate_seed():
    """Calling b1_make_streams does not change the original SeedSequence's
    n_children_spawned."""
    ss = _arbitrary_episode_seed()
    before = ss.n_children_spawned
    b1_make_streams(ss)
    assert ss.n_children_spawned == before
    b1_make_streams(ss)
    assert ss.n_children_spawned == before


def test_distinct_episode_seeds_produce_distinct_streams():
    """Distinct episode seed specifications remain distinct."""
    ss_a = _arbitrary_episode_seed(entropy=99999, spawn_idx=0)
    ss_b = _arbitrary_episode_seed(entropy=99999, spawn_idx=1)
    s_a = b1_make_streams(ss_a)
    s_b = b1_make_streams(ss_b)
    assert not np.array_equal(s_a["process"].random(100), s_b["process"].random(100))


def test_pass1_pass2_materialization_identical():
    """Simulating the pass-1 then pass-2 pattern: both must get identical
    streams from the same episode seed spec."""
    ss = _arbitrary_episode_seed()
    # "pass 1" usage
    streams_pass1 = b1_make_streams(ss)
    vals_pass1 = {name: streams_pass1[name].random(50) for name in STREAMS}
    # "pass 2" usage on same spec
    streams_pass2 = b1_make_streams(ss)
    vals_pass2 = {name: streams_pass2[name].random(50) for name in STREAMS}
    for name in STREAMS:
        assert np.array_equal(vals_pass1[name], vals_pass2[name]), f"pass2 diverges on {name!r}"


def test_two_eval_arms_get_identical_streams():
    """Two evaluation arms materializing the same evaluation episode seed
    receive identical exogenous streams, independent of execution order."""
    ss = _arbitrary_episode_seed(spawn_idx=7)
    # arm A goes first, then arm B
    streams_a = b1_make_streams(ss)
    vals_a = {name: streams_a[name].random(50) for name in STREAMS}
    streams_b = b1_make_streams(ss)
    vals_b = {name: streams_b[name].random(50) for name in STREAMS}
    for name in STREAMS:
        assert np.array_equal(vals_a[name], vals_b[name])
    # reverse order: B first, then A
    streams_b2 = b1_make_streams(ss)
    vals_b2 = {name: streams_b2[name].random(50) for name in STREAMS}
    streams_a2 = b1_make_streams(ss)
    vals_a2 = {name: streams_a2[name].random(50) for name in STREAMS}
    for name in STREAMS:
        assert np.array_equal(vals_a[name], vals_a2[name])
        assert np.array_equal(vals_b[name], vals_b2[name])


def test_validation_replay_identical():
    """Validation replay materialization is identical for the same seed spec,
    even after multiple prior materializations."""
    ss = _arbitrary_episode_seed(spawn_idx=5)
    # simulate prior uses (pass1, pass2, G0 eval, G1 eval...)
    for _ in range(5):
        b1_make_streams(ss)
    replay = b1_make_streams(ss)
    reference = b1_make_streams(_arbitrary_episode_seed(spawn_idx=5))
    for name in STREAMS:
        assert np.array_equal(replay[name].random(50), reference[name].random(50))


def test_no_direct_make_streams_in_b1_code():
    """Mechanical source check: no B1 file imports or calls make_streams
    directly (outside b1_seeds.py where the helper wraps it)."""
    import re
    b1_files = sorted((ROOT / "lineage_b").glob("b1_*.py"))
    b1_files += [ROOT / "lineage_b" / "agent" / "arms.py"]
    b1_files += sorted((ROOT / "tools").glob("run_lineage_b1_*.py"))
    violations = []
    for f in b1_files:
        if f.name == "b1_seeds.py":
            continue
        src = f.read_text()
        # check for raw make_streams import (not b1_make_streams)
        if re.search(r'\bimport\b.*\bmake_streams\b', src) and 'b1_make_streams' not in src.split('import')[0]:
            # ensure any make_streams import is actually b1_make_streams
            for line in src.splitlines():
                if 'make_streams' in line and 'b1_make_streams' not in line and 'import' in line:
                    violations.append((f.name, line.strip()))
        # check for raw make_streams() call (not b1_make_streams)
        for match in re.finditer(r'(?<!\w)make_streams\s*\(', src):
            ctx = src[max(0, match.start() - 3):match.start()]
            if not ctx.endswith('b1_'):
                violations.append((f.name, src[match.start():match.start() + 40]))
    assert not violations, f"direct make_streams usage in B1 code: {violations}"


def test_fresh_seedsequence_resets_children():
    """fresh_seedsequence intentionally resets n_children_spawned."""
    ss = _arbitrary_episode_seed()
    ss.spawn(5)  # advance state
    assert ss.n_children_spawned == 5
    fresh = fresh_seedsequence(ss)
    assert fresh.n_children_spawned == 0
    assert fresh.entropy == ss.entropy
    assert fresh.spawn_key == ss.spawn_key
    assert fresh.pool_size == ss.pool_size
