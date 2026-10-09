"""B1 §7b pre-sizing implementation validation (prereg v1.5 @ 2473c2a).
EVALUATOR side. Implementation-validity checks only: V0 plus B0 gates 7, 11
and 12 adapted to each new arm (G1, G2, G3, G2-S). Every comparison here is
of hashes or structure; no cost, safety or prediction metric is computed and
no arm is compared with another.

Seeds come only from the validation family (root 2026100517000), opened with
its runner token.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import hashlib
import subprocess
from pathlib import Path

import numpy as np

from lineage_b import b1_seeds, params as P
from lineage_b.agent import predictor as pr
from lineage_b.agent.arms import B1Agent, DependencyModel
from lineage_b.agent.authority import resolve
from lineage_b.b1_events import verify_provenance
from lineage_b.b1_protocol import LEARNERS, make_learner, pass1, pass2
from lineage_b.events import AppendOnlyStore
from lineage_b.gates import ALLOWED, _imports, _synthetic_stream
from lineage_b.harness import run_episode
from lineage_b.receipts import ReceiptStore
from lineage_b.b1_seeds import b1_make_streams
from lineage_b.world import FaultState

ROOT = Path(__file__).resolve().parent.parent
PREDICTOR_REF = "94f4f11"
AUTHORITY_REF = "eb3f6d3"
VALIDATION_CONDITIONS = ("C2", "C3", "C5")


def _git_blob_sha(ref, path):
    out = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True)
    return hashlib.sha256(out.stdout).hexdigest() if out.returncode == 0 else None


def v0_static() -> dict:
    """predictor.py byte-identical to 94f4f11 (seed-free; also re-asserted at sizing)."""
    path = "lineage_b/agent/predictor.py"
    ref = _git_blob_sha(PREDICTOR_REF, path)
    cur = hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
    others = []
    for f in sorted((ROOT / "lineage_b" / "agent").glob("*.py")):
        if f.name == "predictor.py":
            continue
        tree = ast.parse(f.read_text())
        defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        if defs & {"categorical", "predict", "level_step", "assimilate_inspection"}:
            others.append(f.name)
    return {"pass": ref is not None and ref == cur and not others, "predictor_sha256": cur,
            "ref_sha256": ref, "ref": PREDICTOR_REF, "foreign_predictive_defs": others}


def _seeds(token, cond, dep=0):
    return b1_seeds.deployment_seeds("validation", token, cond, dep)


def _learn(token, cond, arms=LEARNERS, **kw):
    eps, mu = _seeds(token, cond)
    log = pass1(f"val:{cond}:0", cond, eps, mu)
    learners = {a: make_learner(a) for a in arms}
    out = pass2(log, eps, learners, **kw)
    return log, learners, out, eps


def _sig(out, learners, a):
    st = out["stores"][a]
    last = max(k for k in st._index)
    return (st.hash_of(last), learners[a].model.theta_hash(), out["feedback"][a].digest())


def v0_runtime(token) -> dict:
    """Every arm's receipts are built by predictor.categorical: count calls."""
    calls = {"n": 0}
    orig = pr.categorical

    def counting(*a, **k):
        calls["n"] += 1
        return orig(*a, **k)
    eps, mu = _seeds(token, "C3")
    log = pass1("val:C3:0", "C3", eps, mu)                 # pass-1 (G0 log) receipts not counted
    learners = {a: make_learner(a) for a in LEARNERS}
    pr.categorical = counting
    try:
        out = pass2(log, eps, learners)
    finally:
        pr.categorical = orig
    expected = 0
    for a in LEARNERS:
        st = out["stores"][a]
        for k in st._index:
            pay = st.payload(k)
            expected += len(pay["sensors"]) + len(pay.get("sham", {}))
    return {"pass": calls["n"] == expected and all(out["stores"][a].verify() for a in LEARNERS),
            "categorical_calls": calls["n"], "receipt_sensor_blocks": expected}


# ---------------------------------------------------------------- gate 7
def g7(token) -> dict:
    bad = {}
    for f in sorted((ROOT / "lineage_b" / "agent").glob("*.py")):
        m = {x for x in _imports(f) if not any(x == a or x.startswith(a + ".") for a in ALLOWED)}
        if m:
            bad[f.name] = sorted(m)
    res = {}
    for cond in VALIDATION_CONDITIONS:
        log, learners, out, eps = _learn(token, cond)
        stream = [e["stream"] for e in log["episodes"]]
        other_eps, _ = _seeds(token, cond, dep=1)
        l2 = {a: make_learner(a) for a in LEARNERS}
        o2 = pass2(log, eps, l2, world_eps=other_eps, stream_override=stream)
        l3 = {a: make_learner(a) for a in LEARNERS}
        o3 = pass2(log, eps, l3, stream_override=stream, poison=True)
        for a in LEARNERS:
            s1, s2, s3 = _sig(out, learners, a), _sig(o2, l2, a), _sig(o3, l3, a)
            # decision path: frozen model, replayed stream, different / poisoned hidden world
            e1 = _eval_replay(a, learners[a].model, cond, eps, None, None)
            e2 = _eval_replay(a, learners[a].model, cond, other_eps, e1["stream"], None)
            e3 = _eval_replay(a, learners[a].model, cond, other_eps, e1["stream"], True)
            res[f"{cond}|{a}"] = {"learning_replay_identical": s1 == s2, "learning_poison_identical": s1 == s3,
                                  "decision_replay_identical": e1["digest"] == e2["digest"],
                                  "decision_poison_identical": e1["digest"] == e3["digest"],
                                  "hidden_worlds_differ": e1["h"] != e2["h"]}
    ok = not bad and all(all(v.values()) for v in res.values())
    return {"pass": ok, "import_violations": bad, "per_arm": res}


def _eval_replay(arm, model, cond, eps, replay, poison):
    st, ev = ReceiptStore(), AppendOnlyStore()
    ag = B1Agent(copy.deepcopy(model), None, arm=arm)
    tr, stream = run_episode(streams=b1_make_streams(eps[P.E_L]), faults=FaultState(cond, None), episode=P.E_L,
                             g0=P.E_L * P.EP_LEN, agent=ag, store=st, events=ev, feedback=AppendOnlyStore(),
                             deployment=f"val:{cond}", arm=arm, replay=replay, poison=bool(poison))
    return {"digest": (ev.digest(), st.hash_of((P.E_L, P.EP_LEN)), ag.model.theta_hash()),
            "stream": stream, "h": [s["h"] for s in tr]}


# ---------------------------------------------------------------- gate 11
def _perturb(stream, t_star):
    return [[d if t <= t_star else [dataclasses.replace(r, value=r.value + 0.3) if isinstance(r.value, float) else r
                                    for r in d] for t, d in enumerate(ep)] for ep in stream]


def _randomize(model, rng):
    m = copy.deepcopy(model)
    base = m.base if isinstance(m, DependencyModel) else m
    for s in ("L1", "L2", "L3", "F", "P"):
        base.b[s] = float(rng.normal(0, 0.1))
        base.sigma[s] = float(P.NOMINAL_SIGMA[s] * rng.uniform(0.3, 3))
    if isinstance(m, DependencyModel):
        m.b_g, m.tau2 = float(rng.normal(0, 0.1)), float(rng.uniform(0, 4e-4))
        for s in m.GROUP:
            m.sig[s] = float(P.NOMINAL_SIGMA[s] * rng.uniform(0.3, 3))
            m.d[s] = float(rng.normal(0, 0.05))
    return m


def g11(token) -> dict:
    res = {}
    t_star = 100
    for cond in ("C2", "C3"):
        log, learners, out, eps = _learn(token, cond)
        stream = [e["stream"] for e in log["episodes"]]
        pert = [stream[0][:]] + stream[1:]
        pert[0] = _perturb([stream[0]], t_star)[0]
        la = {a: make_learner(a) for a in LEARNERS}
        oa = pass2(log, eps, la, stream_override=stream)
        lb = {a: make_learner(a) for a in LEARNERS}
        ob = pass2(log, eps, lb, stream_override=pert)
        for a in LEARNERS:
            ra = [oa["stores"][a].hash_of((0, t + 1)) for t in range(P.EP_LEN)]
            rb = [ob["stores"][a].hash_of((0, t + 1)) for t in range(P.EP_LEN)]
            ta = [h for (ep, t, h) in la[a].theta_trace if ep == 0]
            tb = [h for (ep, t, h) in lb[a].theta_trace if ep == 0]
            past = ra[:t_star + 1] == rb[:t_star + 1] and ta[:t_star + 1] == tb[:t_star + 1]
            future = ra[t_star + 1:] != rb[t_star + 1:]
            # decision path, frozen model
            e1 = _eval_replay(a, learners[a].model, cond, eps, None, None)
            ep_stream = e1["stream"]
            dp = _eval_events(a, learners[a].model, cond, eps, ep_stream)
            dq = _eval_events(a, learners[a].model, cond, eps, _perturb([ep_stream], t_star)[0])
            dpast = dp[:t_star + 1] == dq[:t_star + 1]
            # randomized theta: interlock / terminal-abstain outputs identical
            syn = _synthetic_stream(ep_stream)
            rng = np.random.default_rng(3)
            m1 = _mon(a, learners[a].model, cond, eps, syn)
            m2 = _mon(a, _randomize(learners[a].model, rng), cond, eps, syn)
            paths = {p for _, _, p in m1}
            res[f"{cond}|{a}"] = {"learning_past_identical": past, "learning_future_differs": future,
                                  "decision_past_identical": dpast,
                                  "monitor_identical_under_random_theta": m1 == m2,
                                  "interlock_and_terminal_exercised": {"interlock", "terminal_abstain"} <= paths}
    return {"pass": all(all(v.values()) for v in res.values()), "t_star": t_star, "per_arm": res}


def _eval_events(arm, model, cond, eps, replay):
    st, ev = ReceiptStore(), AppendOnlyStore()
    run_episode(streams=b1_make_streams(eps[P.E_L]), faults=FaultState(cond, None), episode=P.E_L,
                g0=P.E_L * P.EP_LEN, agent=B1Agent(copy.deepcopy(model), None, arm=arm), store=st, events=ev,
                feedback=AppendOnlyStore(), deployment=f"val:{cond}", arm=arm, replay=replay)
    return [e.canonical_hash for e in ev.items()]


def _mon(arm, model, cond, eps, replay):
    st, ev = ReceiptStore(), AppendOnlyStore()
    run_episode(streams=b1_make_streams(eps[P.E_L]), faults=FaultState(cond, None), episode=P.E_L,
                g0=P.E_L * P.EP_LEN, agent=B1Agent(model, None, arm=arm), store=st, events=ev,
                feedback=AppendOnlyStore(), deployment=f"val:{cond}", arm=arm, replay=replay)
    return [(e.monitor_action, e.monitor_direction, e.authority_path) for e in ev.items()]


# ---------------------------------------------------------------- gate 12
def g12(token) -> dict:
    d = subprocess.run(["git", "diff", "--stat", AUTHORITY_REF, "--", "morphsat/terminal_authority.py"],
                       cwd=ROOT, capture_output=True, text=True)
    unchanged = d.returncode == 0 and not d.stdout.strip()
    res, provenance = {}, {}
    for cond in ("C3", "C5"):
        log, learners, out, eps = _learn(token, cond)
        logged = [s["action"] for e in log["episodes"] for s in e["traj"]]
        exec_ok = out["executed"] == logged
        for a in LEARNERS:
            st = out["stores"][a]
            rec_ok, sham_steps = True, 0
            for (ep, t1) in st._index:
                pay = st.payload((ep, t1))
                rec_ok &= pay["action"] == log["episodes"][ep]["traj"][t1 - 1]["action"]
                if a == "G2-S" and pay.get("sham_action") not in (None, pay["action"]):
                    sham_steps += 1
            # decision path: every final action from resolve_terminal_authority
            e1 = _eval_replay(a, learners[a].model, cond, eps, None, None)
            ev_ok = _events_consistent(a, learners[a].model, cond, eps, _synthetic_stream(e1["stream"]))
            prov = verify_provenance(log["behavior"], log["events"], out["feedback"][a].items(), st.payload)
            entry = {"executed_equals_log": exec_ok, "receipt_action_is_logged_action": rec_ok,
                     "events_consistent": ev_ok, "behavior_provenance": prov["pass"],
                     "no_pending_group_after_learning": not getattr(learners[a], "pending_group", {})}
            provenance[f"{cond}|{a}"] = {k: prov[k] for k in ("n_problems", "problems", "steps", "feedback_checked")}
            if a == "G2-S":
                entry["sham_actions_differ_somewhere"] = sham_steps > 0
            res[f"{cond}|{a}"] = entry
    src = (ROOT / "lineage_b" / "agent" / "arms.py").read_text()
    tree = ast.parse(src)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    arms_no_authority = not ({"resolve", "monitor", "resolve_terminal_authority"} & names) and \
        not any("authority" in (m or "") for m in _imports(ROOT / "lineage_b" / "agent" / "arms.py"))
    ignored = resolve(("COMMIT", "open", True, "interlock"), "close") == ("open", "none")
    from morphsat.terminal_authority import resolve_terminal_authority
    try:
        resolve_terminal_authority("COMMIT", "open", True, "COMMIT", "close", "arbitration")
        forced_raises = False
    except ValueError:
        forced_raises = True
    ok = unchanged and arms_no_authority and ignored and forced_raises and \
        all(all(v.values()) for v in res.values())
    return {"pass": ok, "terminal_authority_unchanged_vs_eb3f6d3": unchanged,
            "arms_module_has_no_authority_path": arms_no_authority,
            "proposal_ignored_on_terminal": ignored, "forced_arbitration_raises": forced_raises,
            "per_arm": res, "provenance": provenance}


def _events_consistent(arm, model, cond, eps, replay):
    st, ev = ReceiptStore(), AppendOnlyStore()
    run_episode(streams=b1_make_streams(eps[P.E_L]), faults=FaultState(cond, None), episode=P.E_L,
                g0=P.E_L * P.EP_LEN, agent=B1Agent(copy.deepcopy(model), None, arm=arm), store=st, events=ev,
                feedback=AppendOnlyStore(), deployment=f"val:{cond}", arm=arm, replay=replay)
    ok, paths = True, set()
    for e in ev.items():
        paths.add(e.authority_path)
        if e.authority_path == "interlock":
            ok &= e.final_action == e.monitor_direction and e.resolved_by == "none"
        elif e.authority_path == "terminal_abstain":
            ok &= e.final_action == "inspect" and e.resolved_by == "none"
        else:
            ok &= e.resolved_by == "arbitration" and e.final_action == e.proposal
    return ok and {"interlock", "terminal_abstain", "arbitration"} <= paths


CHECKS = (("V0-static", lambda tok: v0_static()), ("V0-runtime", v0_runtime),
          ("gate7", g7), ("gate11", g11), ("gate12", g12))
