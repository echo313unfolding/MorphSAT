"""B0 validity gates (B0 prereg v1.1 §10). Each gate returns a dict with
"pass" plus details. EVALUATOR side."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np

from lineage_b import params as P
from lineage_b.agent import predictor as pr
from lineage_b.agent.authority import monitor, resolve
from lineage_b.agent.core import Agent
from lineage_b.agent.numerics import erf
from lineage_b.agent.sensor_model import SensorModel
from lineage_b.evaluate import episode_metrics
from lineage_b.events import AppendOnlyStore
from lineage_b.harness import episode_seeds, run_episode, run_world
from lineage_b.logging_policy import LoggingPolicy
from lineage_b.obs import MISSING, PENDING, VALUE, Record
from lineage_b.receipts import ReceiptError, ReceiptStore
from lineage_b.ref import RefSensorModel
from lineage_b.sensors import true_quantity
from lineage_b.world import CONDITIONS, STREAMS, FaultState, TransitionError, World, make_streams

ROOT = Path(__file__).resolve().parent.parent
# v1.3 roots (prereg v1.3 Amendment 2). v1.1 used 20261005/6/7 (gate 2's B0_SEED+1, +2
# hit the v1.1 pilot and B1 roots); v1.2's B0 root 2026100512000 was never used for gates.
# B0 offsets here span +0..+999; pilot and B1 roots are unchanged from v1.2 (never consumed).
B0_SEED, PILOT_SEED, B1_SEED = 2026100515000, 2026100513000, 2026100514000
_B0_RANGE = {B0_SEED + k for k in range(1000)}
assert not _B0_RANGE & {PILOT_SEED, B1_SEED}
assert not _B0_RANGE & ({20261005 + k for k in range(1000)} | {2026100512000 + k for k in range(1000)})


def streams(seed, dep=0, ep=0, n=1):
    eps, mu = episode_seeds(seed, dep, max(n, ep + 1))
    return make_streams(eps[ep]), mu


def _zhash(zs, delivered):
    h = hashlib.sha256()
    for z in zs:
        h.update(repr((z.h, z.q_in, z.u, z.leak, z.repair_at, z.t, z.g)).encode())
    for recs in delivered:
        for r in recs:
            h.update(repr(dataclasses.astuple(r)).encode())
    return h.hexdigest()


def full_run(seed, cond, dep=0, updater=None, mu_on=True, replay=None, poison=False,
             model=None, world_seed=None, n_steps=P.EP_LEN):
    s, mu = streams(seed if world_seed is None else world_seed, dep)
    _, mu_r = streams(seed, dep)                       # mu always from the agent-side seed
    st, ev, fb = ReceiptStore(), AppendOnlyStore(), AppendOnlyStore()
    ag = Agent(model or SensorModel(), updater=updater)
    traj, stream = run_episode(streams=s, faults=FaultState(cond), episode=0, g0=0, agent=ag,
                               store=st, events=ev, feedback=fb, deployment=f"b0-{cond}-{dep}",
                               mu=LoggingPolicy(mu_r, active=mu_on), replay=replay, poison=poison,
                               n_steps=n_steps)
    return {"traj": traj, "stream": stream, "store": st, "events": ev, "feedback": fb, "agent": ag}


# ---------------------------------------------------------------- gate 1
def g1_mass_balance():
    cases, worst = [], 0.0
    fixtures = {
        "closed_inflow": dict(h0=1.0, u0=0.0, acts=["hold"] * 20),
        "drain": dict(h0=1.5, u0=1.0, acts=["hold"] * 20, q0=0.0),
        "leak": dict(h0=1.0, u0=0.5, acts=["hold"] * 20, leak="fast"),
        "overflow": dict(h0=1.98, u0=0.0, acts=["hold"] * 5),
        "underflow": dict(h0=0.004, u0=1.0, acts=["hold"] * 5, q0=0.0, leak="fast"),
    }
    for name, f in fixtures.items():
        s, _ = streams(B0_SEED)
        w = World(s, FaultState("C0"), 0, 0, None, noise=False, h0=f["h0"], u0=f["u0"],
                  q0=f.get("q0", P.Q_BAR))
        if "leak" in f:
            w.z.leak = f["leak"]
        flags = {"spill": 0.0, "shortfall": 0.0}
        for a in f["acts"]:
            h, q, u, lk = w.z.h, w.z.q_in, w.z.u, w.z.leak
            w.step(a, None)
            fl = w.last_flows
            lhs = P.A * (w.z.h - h)
            rhs = P.DT * (fl["q_in"] - fl["q_out"] - fl["q_leak"] - fl["spill"] + fl["shortfall"])
            sq = math.sqrt(max(h, 0))
            indep = h + q - P.CV * u * sq - P.K_LEAK[lk] * sq          # independent recursion
            err = max(abs(lhs - rhs), abs(min(max(indep, 0), P.H_MAX) - w.z.h))
            worst = max(worst, err)
            flags["spill"] += fl["spill"]
            flags["shortfall"] += fl["shortfall"]
        cases.append({"fixture": name, **flags})
    branch = cases[3]["spill"] > 0 and cases[4]["shortfall"] > 0
    return {"pass": worst <= 1e-12 and branch, "max_err": worst, "cases": cases}


# ---------------------------------------------------------------- gate 2 / 2b
def _acts(seed, n=P.EP_LEN):
    r = np.random.default_rng(seed)
    return [str(x) for x in r.choice(["open", "hold", "close", "inspect"], size=n, p=[.2, .5, .2, .1])]


def g2_replay():
    out = []
    for seed in (1, 2, 3):
        for c in CONDITIONS:
            hs = []
            for _ in range(2):
                s, _m = streams(B0_SEED + seed)
                zs, _r, dl, _w = run_world(s, FaultState(c), _acts(seed))
                hs.append(_zhash(zs, dl))
            out.append(hs[0] == hs[1])
    return {"pass": all(out), "runs": len(out)}


def g2b_crn():
    res = {}
    for c in ("C0", "C5"):
        s1, _ = streams(B0_SEED + 7)
        s2, _ = streams(B0_SEED + 7)
        za, ra, da, _ = run_world(s1, FaultState(c), ["hold"] * P.EP_LEN)
        zb, rb, db, _ = run_world(s2, FaultState(c), [("open", "close")[i % 2] for i in range(P.EP_LEN)])
        qin = all(a.q_in == b.q_in for a, b in zip(za, zb))
        errs = all(abs((x[s] - true_quantity(s, za[i])) - (y[s] - true_quantity(s, zb[i]))) < 1e-12
                   for i, (x, y) in enumerate(zip(ra, rb)) for s in P.SENSORS)
        chan = [[(r.sensor_id, r.seq, r.measured_at, r.delivered_at) for r in d] for d in da] == \
               [[(r.sensor_id, r.seq, r.measured_at, r.delivered_at) for r in d] for d in db]
        res[c] = {"q_in_identical": qin, "sensor_errors_identical": errs, "channel_identical": chan}
    return {"pass": all(all(v.values()) for v in res.values()), "detail": res}


# ---------------------------------------------------------------- gate 3
def g3_actions_change_state():
    h = []
    for a in ("open", "close"):
        s, _ = streams(B0_SEED + 11)
        zs, _r, _d, w = run_world(s, FaultState("C0"), [a] * 10)
        h.append(w.z.h)
    return {"pass": abs(h[0] - h[1]) >= 0.05, "h_open": h[0], "h_close": h[1]}


# ---------------------------------------------------------------- gates 4, 5
def _long_errors(cond, n_eps=110):
    errs = {s: [] for s in P.SENSORS}
    l4_ok = True
    for ep in range(n_eps):
        s, _ = streams(B0_SEED + 100, ep=ep, n=n_eps)
        w = World(s, FaultState(cond), ep, 0, None)
        from lineage_b.sensors import measure
        from lineage_b.channel import Channel
        ch = Channel(s, cond)
        for t in range(P.EP_LEN):
            z = w.z
            r = measure(z, s, w.faults)
            ch.push(t, z.g, r)
            d = ch.deliver(t)
            if cond == "C3":
                l1 = {(x.measured_at): x.value for x in d if x.sensor_id == "L1"}
                for x in d:
                    if x.sensor_id == "L4":
                        l4_ok &= l1.get(x.measured_at) == x.value
            for k in P.SENSORS:
                errs[k].append(r[k] - true_quantity(k, z))
            a = "open" if z.h > 1.1 else "close" if z.h < 0.9 else "hold"
            w.step(a, None)
    return {k: np.array(v) for k, v in errs.items()}, l4_ok


def g4_shared_dependence():
    e, _ = _long_errors("C0")
    n = len(e["L1"])
    rho = float(np.corrcoef(e["L1"], e["L2"])[0, 1])
    target = P.SIGMA_A ** 2 / (P.SIGMA_A ** 2 + P.SIGMA_L12 ** 2)
    se = (1 - target ** 2) / math.sqrt(n)
    # C2 shift exact under CRN
    s1, _ = streams(B0_SEED + 12)
    s2, _ = streams(B0_SEED + 12)
    _z0, r0, _d0, _ = run_world(s1, FaultState("C0"), ["hold"] * P.EP_LEN)
    _z2, r2, _d2, _ = run_world(s2, FaultState("C2"), ["hold"] * P.EP_LEN)
    shift = all(abs((b[k] - a[k]) - (0.15 if t >= P.T_F else 0.0)) < 1e-12
                for t, (a, b) in enumerate(zip(r0, r2)) for k in ("L1", "L2"))
    return {"pass": abs(rho - target) <= 3 * se and shift and n >= 20000, "n": n, "corr": rho,
            "target": target, "se": se, "c2_shift_exact": shift}


def g5_no_shared_noise():
    e, _ = _long_errors("C0")
    n = len(e["L1"])
    lim = 3 / math.sqrt(n)
    pairs = {}
    ks = list(P.SENSORS)
    for i in range(len(ks)):
        for j in range(i + 1, len(ks)):
            if {ks[i], ks[j]} == {"L1", "L2"}:
                continue
            pairs[f"{ks[i]}-{ks[j]}"] = float(np.corrcoef(e[ks[i]], e[ks[j]])[0, 1])
    _e3, l4_ok = _long_errors("C3", n_eps=5)
    keys_distinct = len(set(STREAMS)) == len(STREAMS)
    return {"pass": all(abs(v) <= lim for v in pairs.values()) and l4_ok and keys_distinct,
            "limit": lim, "corr": pairs, "L4_copies_L1": l4_ok}


# ---------------------------------------------------------------- gate 6
def status(seen, sensor, measured_at, now):
    if any(r.sensor_id == sensor and r.measured_at == measured_at and r.delivered_at <= now for r in seen):
        return VALUE
    return PENDING if now - measured_at <= P.D_MAX else MISSING


def g6_missing_explicit():
    r = full_run(B0_SEED, "C5", updater="receipt")
    seen = [x for d in r["stream"] for x in d]
    statuses, consistent = set(), True
    for now in range(0, P.EP_LEN, 7):
        for s in ("L1", "L2", "L3", "P"):
            for m in range(max(0, now - 6), now + 1):
                st = status(seen, s, m, now)
                statuses.add(st)
                delivered = any(x.sensor_id == s and x.measured_at == m and x.delivered_at <= now for x in seen)
                consistent &= (st == VALUE) == delivered
    # all-MISSING stream: no updates, no feedback, terminal abstain
    empty = full_run(B0_SEED, "C0", updater="receipt", replay=[[] for _ in range(P.EP_LEN)])
    thetas = {e.theta_hash for e in empty["events"].items()}
    paths = {e.authority_path for e in empty["events"].items()}
    # accounting in the normal run: every delivered numeric record -> feedback or logged skip
    numeric = [x for x in seen if x.sensor_id != "INSPECT"]
    n_fb = len(r["feedback"].items())
    n_skip = len(r["agent"].log)
    ok = (statuses <= {VALUE, PENDING, MISSING} and MISSING in statuses and PENDING in statuses
          and consistent and len(thetas) == 1 and len(empty["feedback"].items()) == 0
          and paths == {"terminal_abstain"} and n_fb + n_skip == len(numeric))
    return {"pass": ok, "statuses": sorted(statuses), "consistent": consistent,
            "empty_stream_theta_versions": len(thetas), "empty_stream_paths": sorted(paths),
            "records": len(numeric), "feedback": n_fb, "logged_skips": n_skip}


# ---------------------------------------------------------------- gate 7
ALLOWED = ("lineage_b.params", "lineage_b.obs", "lineage_b.receipts", "lineage_b.events",
           "lineage_b.agent", "morphsat.terminal_authority", "numpy", "__future__", "math",
           "hashlib", "functools", "typing", "dataclasses", "json")


def _imports(path):
    tree = ast.parse(path.read_text())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom):
            mods.add(n.module)
    return mods


def g7_hidden_separation():
    bad = {}
    for f in sorted((ROOT / "lineage_b" / "agent").glob("*.py")):
        m = {x for x in _imports(f) if not any(x == a or x.startswith(a + ".") for a in ALLOWED)}
        if m:
            bad[f.name] = sorted(m)
    fields = {f.name for f in dataclasses.fields(Record)}
    fields_ok = fields == {"sensor_id", "seq", "measured_at", "delivered_at", "value", "declared_upstream"}
    a = full_run(B0_SEED, "C2", updater="receipt")
    b = full_run(B0_SEED, "C2", updater="receipt", replay=a["stream"], world_seed=B0_SEED + 999)
    c = full_run(B0_SEED, "C2", updater="receipt", replay=a["stream"], world_seed=B0_SEED + 999, poison=True)
    sig = lambda r: (r["events"].digest(), r["store"].hash_of((0, P.EP_LEN)), r["agent"].model.theta_hash())
    hidden_differs = any(x["h"] != y["h"] for x, y in zip(a["traj"], b["traj"]))
    return {"pass": not bad and fields_ok and sig(a) == sig(b) == sig(c) and hidden_differs,
            "import_violations": bad, "record_fields_ok": fields_ok,
            "replay_identical": sig(a) == sig(b), "poison_identical": sig(a) == sig(c),
            "hidden_worlds_differ": hidden_differs}


# ---------------------------------------------------------------- gate 8
def g8_receipts_before_transition():
    st = ReceiptStore()
    s, _ = streams(B0_SEED)
    w = World(s, FaultState("C0"), 0, 0, st)
    raises = []
    try:
        w.step("hold", None)
        raises.append(False)
    except TransitionError:
        raises.append(True)
    st.commit((0, 1), {"x": 1})
    try:
        w.step("hold", "deadbeef")
        raises.append(False)
    except TransitionError:
        raises.append(True)
    try:
        st.commit((0, 1), {"x": 2})
        raises.append(False)
    except ReceiptError:
        raises.append(True)
    r = full_run(B0_SEED, "C0", updater="receipt")
    chain_ok = len(r["store"]) == P.EP_LEN and r["store"].verify()
    order_ok = all(s["commit_clock"] < s["transition_clock"] for s in r["traj"])
    return {"pass": all(raises) and chain_ok and order_ok, "rejections": raises,
            "chain_verifies": chain_ok, "commit_before_transition": order_ok}


# ---------------------------------------------------------------- gate 9
def g9_events_immutable():
    r = full_run(B0_SEED, "C3", updater="receipt")
    ev = r["events"].items()[5]
    try:
        ev.final_action = "x"
        mutable = True
    except dataclasses.FrozenInstanceError:
        mutable = False
    no_delete = not any(hasattr(r["events"], m) for m in ("remove", "pop", "clear", "__setitem__", "__delitem__"))
    d1 = r["events"].digest()
    d2 = hashlib.sha256("".join(e.canonical_hash for e in r["events"].items()).encode()).hexdigest()
    return {"pass": (not mutable) and no_delete and r["events"].verify() and r["feedback"].verify() and d1 == d2,
            "mutation_blocked": not mutable, "append_only": no_delete, "events": len(r["events"].items())}


# ---------------------------------------------------------------- gate 10
def _chi2_sf3(x):
    return float(1 - erf(math.sqrt(x / 2))) + math.sqrt(2 * x / math.pi) * math.exp(-x / 2)


def g10_propensities():
    out = {}
    for prop in P.ACTIONS:
        mu = LoggingPolicy(np.random.default_rng(P.ACTIONS.index(prop) + 5))
        p = mu.propensities(prop)
        n = 100000
        cnt = {a: 0 for a in P.ACTIONS}
        recorded_ok = True
        for _ in range(n):
            a, pr_, rnd = mu.choose(prop, True)
            cnt[a] += 1
            recorded_ok &= abs(pr_ - p[a]) < 1e-15 and rnd
        x = sum((cnt[a] - n * p[a]) ** 2 / (n * p[a]) for a in P.ACTIONS)
        out[prop] = {"sum": sum(p.values()), "chi2": x, "p": _chi2_sf3(x), "recorded_ok": recorded_ok}
    nr = LoggingPolicy(np.random.default_rng(1)).choose("hold", False)
    r = full_run(B0_SEED, "C5")
    nonrand = all(e.propensity == 1.0 and not e.randomized for e in r["events"].items()
                  if e.authority_path != "arbitration")
    ok = all(abs(v["sum"] - 1) < 1e-12 and v["p"] >= 0.001 and v["recorded_ok"] for v in out.values()) \
        and nr == ("hold", 1.0, False) and nonrand
    return {"pass": ok, "classes": out, "non_randomized_ok": nonrand}


# ---------------------------------------------------------------- gate 11
def _synthetic_stream(stream):
    """Force interlock (t 60-69) and terminal-abstain (t 120-129) windows."""
    out = []
    for t, d in enumerate(stream):
        nd = []
        for r in d:
            if 60 <= r.measured_at < 70 and r.sensor_id in ("L1", "L2"):
                r = dataclasses.replace(r, value=1.75)
            if 120 <= r.measured_at < 130 and r.sensor_id in ("L1", "L2"):
                continue
            nd.append(r)
        out.append(nd)
    return out


def g11_future_only():
    base = full_run(B0_SEED, "C2", updater="receipt")
    t_star = 100
    pert = [d if t <= t_star else [dataclasses.replace(r, value=r.value + 0.3) if isinstance(r.value, float) else r
                                   for r in d] for t, d in enumerate(base["stream"])]
    a = full_run(B0_SEED, "C2", updater="receipt", replay=base["stream"])
    b = full_run(B0_SEED, "C2", updater="receipt", replay=pert)
    ea, eb = a["events"].items(), b["events"].items()
    past_same = all(x.canonical_hash == y.canonical_hash for x, y in zip(ea[:t_star + 1], eb[:t_star + 1]))
    future_differs = any(x.canonical_hash != y.canonical_hash for x, y in zip(ea[t_star + 1:], eb[t_star + 1:]))
    syn = _synthetic_stream(base["stream"])
    m1, m2 = SensorModel(), SensorModel()
    rng = np.random.default_rng(3)
    for s in ("L1", "L2", "L3", "F", "P"):
        m2.b[s] = float(rng.normal(0, 0.1)); m2.sigma[s] = float(P.NOMINAL_SIGMA[s] * rng.uniform(0.3, 3)); m2.v[s] = None
        m1.params(s, 0)
    x = full_run(B0_SEED, "C2", replay=syn, model=m1)
    y = full_run(B0_SEED, "C2", replay=syn, model=m2)
    mon = lambda r: [(e.monitor_action, e.monitor_direction, e.authority_path) for e in r["events"].items()]
    paths = {p for _, _, p in mon(x)}
    tree = ast.parse((ROOT / "lineage_b" / "agent" / "authority.py").read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "monitor")
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}
    blind = not names & {"model", "theta", "B", "belief", "sigma", "b"}
    ok = past_same and future_differs and mon(x) == mon(y) and {"interlock", "terminal_abstain"} <= paths and blind
    return {"pass": ok, "past_identical": past_same, "future_differs": future_differs,
            "monitor_identical_under_random_theta": mon(x) == mon(y), "paths_exercised": sorted(paths),
            "monitor_theta_blind_ast": blind}


# ---------------------------------------------------------------- gate 12
def g12_terminal_authority():
    d = subprocess.run(["git", "diff", "--stat", "eb3f6d3", "--", "morphsat/terminal_authority.py"],
                       cwd=ROOT, capture_output=True, text=True)
    unchanged = d.returncode == 0 and not d.stdout.strip()
    r = full_run(B0_SEED, "C5")
    consistent = True
    for e in r["events"].items():
        if e.authority_path == "interlock":
            consistent &= e.final_action == e.monitor_direction and e.resolved_by == "none"
        elif e.authority_path == "terminal_abstain":
            consistent &= e.final_action == "inspect" and e.resolved_by == "none"
        else:
            consistent &= e.resolved_by == "arbitration" and e.final_action == e.proposal
    ignored = resolve(("COMMIT", "open", True, "interlock"), "close") == ("open", "none")
    from morphsat.terminal_authority import resolve_terminal_authority
    try:
        resolve_terminal_authority("COMMIT", "open", True, "COMMIT", "close", "arbitration")
        forced_raises = False
    except ValueError:
        forced_raises = True
    src = (ROOT / "lineage_b" / "agent" / "authority.py").read_text()
    single_path = src.count("resolve_terminal_authority(") == 3      # import excluded: 2 DEFER + 1 terminal
    return {"pass": unchanged and consistent and ignored and forced_raises and single_path,
            "file_unchanged_vs_eb3f6d3": unchanged, "events_consistent": consistent,
            "proposal_ignored_on_terminal": ignored, "forced_arbitration_raises": forced_raises,
            "adapter_calls": src.count("resolve_terminal_authority(")}


# ---------------------------------------------------------------- gate 13
def gate13_belief(h0: float) -> "pr.Belief":
    """v1.3 §1.6: pi = q_stationary on leak none, m = h0, v = 0.05^2 (placeholders elsewhere)."""
    pi = pr.q_stationary()[:, None] * np.array([1.0, 0.0, 0.0])[None, :]
    on = pi > 0
    return pr.Belief(pi, np.where(on, h0, 0.0), np.where(on, 0.05 ** 2, 0.0))


def g13_action_sensitivity():
    out, ok = {}, True
    m = SensorModel()
    for h0 in (0.5, 1.0, 1.5):
        B = gate13_belief(h0)
        for s in ("L3", "F"):
            dist = {}
            for a, u in (("open", 0.75), ("close", 0.25)):
                p = pr.predict(B, u, False)
                dist[a] = pr.categorical(s, p, u, *m.params(s, 0))[0]
            po, pc = np.maximum(dist["open"], 1e-300), np.maximum(dist["close"], 1e-300)
            kl = float((po * np.log(po / pc)).sum())
            out[f"h={h0}|{s}"] = kl
            ok &= kl >= 0.05
    return {"pass": ok, "kl_nats": out}


# ---------------------------------------------------------------- gate 14
def g14_transport_duplicates():
    r = full_run(B0_SEED, "C0", updater="receipt")
    keys = [x.key for d in r["stream"] for x in d]
    dups = len(keys) - len(set(keys))
    fb_keys = [(f.sensor_id, f.seq) for f in r["feedback"].items()]
    skips = sum(1 for e in r["agent"].log if e.get("skip") == "redelivery")
    return {"pass": dups > 0 and skips == dups and len(fb_keys) == len(set(fb_keys)),
            "redeliveries": dups, "logged": skips, "feedback_unique": len(fb_keys) == len(set(fb_keys))}


# ---------------------------------------------------------------- gate 15
def g15_fault_semantics():
    def run(c):
        s, _ = streams(B0_SEED + 21)
        return run_world(s, FaultState(c), ["hold"] * P.EP_LEN)
    z0, r0, d0, _ = run("C0")
    res = {}
    _, r1, _, _ = run("C1")
    stuck = r1[P.T_F]["L3"]
    res["C1"] = all(r1[t]["L3"] == (stuck if t >= P.T_F else r0[t]["L3"]) for t in range(P.EP_LEN))
    _, r2, _, _ = run("C2")
    res["C2"] = all(abs(r2[t][k] - r0[t][k] - (0.15 if t >= P.T_F and k in ("L1", "L2") else 0)) < 1e-12
                    for t in range(P.EP_LEN) for k in P.SENSORS)
    _, r3, d3, _ = run("C3")
    l4 = [x for d in d3 for x in d if x.sensor_id == "L4"]
    l1 = {x.measured_at: x.value for d in d3 for x in d if x.sensor_id == "L1"}
    res["C3"] = all(abs(r3[t]["L1"] - r0[t]["L1"] - (min(0.002 * (t - P.T_F), 0.3) if t >= P.T_F else 0)) < 1e-12
                    for t in range(P.EP_LEN)) and bool(l4) and all(x.measured_at >= P.T_F and l1[x.measured_at] == x.value for x in l4)
    _, r4, _, _ = run("C4")
    res["C4"] = all(abs((r4[t]["P"] - true_quantity("P", z0[t])) - (5 if t >= P.T_F else 1) * (r0[t]["P"] - true_quantity("P", z0[t]))) < 1e-9
                    and abs(r4[t]["F"] - r0[t]["F"] - (0.02 if t >= P.T_F else 0)) < 1e-12 for t in range(P.EP_LEN))
    # C5 over many episodes
    delays, drops, n = [], {"L1": 0, "L2": 0, "P": 0}, 0
    values_ok = True
    for ep in range(30):
        s, _ = streams(B0_SEED + 22, ep=ep, n=30)
        s0, _ = streams(B0_SEED + 22, ep=ep, n=30)
        zc, rc, dc, _ = run_world(s, FaultState("C5"), ["hold"] * P.EP_LEN)
        _z, rr, _d, _ = run_world(s0, FaultState("C0"), ["hold"] * P.EP_LEN)
        got = {(x.sensor_id, x.measured_at) for d in dc for x in d}
        for x in (x for d in dc for x in d):
            if x.sensor_id in P.SENSORS:
                values_ok &= x.value == rr[x.measured_at][x.sensor_id]
            if x.sensor_id == "L3" and x.measured_at >= P.T_F:
                delays.append(x.delivered_at - x.measured_at)
        for t in range(P.T_F, P.EP_LEN - 5):
            n += 1
            for k in drops:
                drops[k] += (k, t) not in got
    md = float(np.mean(delays)) if delays else 0
    pdrop = {k: v / n for k, v in drops.items()}
    res["C5"] = (min(delays) >= 1 and abs(md - 2) < 0.15 and abs(pdrop["L1"] - .10) < 0.02
                 and abs(pdrop["L2"] - .10) < 0.02 and abs(pdrop["P"] - .30) < 0.03 and values_ok)
    return {"pass": all(res.values()), "conditions": res, "C5_mean_delay": md, "C5_drop": pdrop}


# ---------------------------------------------------------------- gate 16
def g16_metrics():
    base = dict(q_in=0.05, u=0.5, u_new=0.5, q_leak=0.0, spill=0.0, q_out=0.05, shortfall=0.0, h_raw=1.0)
    traj = [dict(base, h=1.0, h_next=1.7, leak="none", action="hold"),
            dict(base, h=1.7, h_next=1.85, leak="none", action="hold"),         # hazard high, hold -> false-safe; transition
            dict(base, h=1.85, h_next=1.7, leak="slow", action="open", u_new=0.75, q_leak=0.01),
            dict(base, h=1.7, h_next=1.6, leak="slow", action="inspect", spill=0.1)]
    m = episode_metrics(traj)
    J = (10 * 0.0) + (10 * 0.49) + (100 + 10 * 0.85 ** 2 + 0.1 + 200 * 0.01) + (10 * 0.49 + 2 + 200 * 0.1)
    ok = (abs(m["J"] - J) < 1e-9 and m["unsafe_transitions"] == 1 and m["false_safe"] == 1
          and m["unsafe_steps"] == 1 and m["inspect_rate"] == 0.25)
    return {"pass": ok, "metrics": m, "expected_J": J}


# ---------------------------------------------------------------- gate 18
def g18_calibration(n_dep=20):
    pits = {s: [] for s in P.SENSORS}
    for dep in range(n_dep):
        r = full_run(B0_SEED, "C0", dep=dep)
        for f in r["feedback"].items():
            pay = r["store"].payload(tuple(f.receipt_key))["sensors"][f.sensor_id]
            pits[f.sensor_id].append(pr.pit(f.sensor_id, pay["probs"], f.observed))
    out, ok = {}, True
    for s, v in pits.items():
        v = np.array(v)
        c90 = float(np.mean((v >= 0.05) & (v <= 0.95)))
        c50 = float(np.mean((v >= 0.25) & (v <= 0.75)))
        out[s] = {"n": len(v), "cov90": c90, "cov50": c50, "mean_pit": float(v.mean())}
        ok &= 0.85 <= c90 <= 0.95 and 0.40 <= c50 <= 0.60
    return {"pass": ok, "sensors": out, "deployments": n_dep}


# ---------------------------------------------------------------- gate 19
def g19_feedback_integrity():
    r = full_run(B0_SEED, "C3", updater="receipt")
    ok, n = True, 0
    ev_hashes = {e.canonical_hash for e in r["events"].items()}
    for f in r["feedback"].items():
        n += 1
        key = tuple(f.receipt_key)
        pay = r["store"].payload(key)
        sp = pay["sensors"][f.sensor_id]
        ls, br = pr.score(f.sensor_id, sp["probs"], f.observed)
        ok &= (r["store"].hash_of(key) == f.receipt_hash and key[1] == f.measured_at
               and pay["decision_key"][1] < f.delivered_at + 1 and pay["decision_key"][1] == f.measured_at - 1
               and f.decision_ref in ev_hashes and ls == f.log_score and br == f.brier
               and f.residual == f.observed - sp["latent_mean"])
    agent_src = "".join(p.read_text() for p in (ROOT / "lineage_b" / "agent").glob("*.py"))
    agent_cannot_write = "FeedbackRecord" not in agent_src and "AppendOnlyStore" not in agent_src
    return {"pass": ok and n > 0 and agent_cannot_write and r["feedback"].verify(), "records": n,
            "agent_cannot_write": agent_cannot_write}


# ---------------------------------------------------------------- gate 17 (pilot)
def g17_pilot(n_dep=20, n_max=200):
    per = {}
    for c in CONDITIONS:
        jg0, jref = [], []
        for dep in range(n_dep):
            eps, mu = episode_seeds(PILOT_SEED, dep * 10 + CONDITIONS.index(c), P.E_L + P.E_E)
            faults = FaultState(c)
            st, ev, fb = ReceiptStore(), AppendOnlyStore(), AppendOnlyStore()
            ag = Agent(SensorModel())
            for ep in range(P.E_L):                          # learning phase under mu (fault timing only)
                run_episode(streams=make_streams(eps[ep]), faults=faults, episode=ep, g0=ep * P.EP_LEN,
                            agent=ag, store=st, events=ev, feedback=fb, deployment=f"pilot-{c}-{dep}",
                            mu=LoggingPolicy(mu))
            for arm, model in (("G0", SensorModel()), ("REF-S", RefSensorModel(c))):
                js = []
                fs_copy = FaultState(c, faults.stuck_value)
                for ep in range(P.E_L, P.E_L + P.E_E):
                    st2 = ReceiptStore()
                    traj, _ = run_episode(streams=make_streams(eps[ep]), faults=fs_copy, episode=ep,
                                          g0=ep * P.EP_LEN, agent=Agent(model, arm=arm), store=st2,
                                          events=AppendOnlyStore(), feedback=AppendOnlyStore(),
                                          deployment=f"pilot-{c}-{dep}", arm=arm)
                    js.append(episode_metrics(traj)["J"])
                (jg0 if arm == "G0" else jref).append(float(np.mean(js)))
        per[c] = {"mean_J_G0": float(np.mean(jg0)), "var_J_G0": float(np.var(jg0, ddof=1)),
                  "mean_J_REF_S": float(np.mean(jref)), "gap": float(np.mean(jg0) - np.mean(jref))}
    fault = [c for c in CONDITIONS if c != "C0"]
    gap = float(np.mean([per[c]["gap"] for c in fault]))
    var_term = sum(2 * per[c]["var_J_G0"] for c in fault) / len(fault) ** 2
    if gap > 0:
        n = math.ceil((1.96 / (0.5 * 0.10 * gap)) ** 2 * var_term)
        n_frozen = min(max(n, 2), n_max)
    else:
        n, n_frozen = None, None
    return {"pass": True, "per_condition": per, "pooled_gap_G0_minus_REF_S": gap,
            "N_required": n, "N_frozen_for_B1": n_frozen, "N_max": n_max, "pilot_deployments": n_dep,
            "note": "sizes N only; no G1/G2/G3/G2-S code exists or ran"}


FAST = [("1", g1_mass_balance), ("2", g2_replay), ("2b", g2b_crn), ("3", g3_actions_change_state),
        ("4", g4_shared_dependence), ("5", g5_no_shared_noise), ("6", g6_missing_explicit),
        ("7", g7_hidden_separation), ("8", g8_receipts_before_transition), ("9", g9_events_immutable),
        ("10", g10_propensities), ("11", g11_future_only), ("12", g12_terminal_authority),
        ("13", g13_action_sensitivity), ("14", g14_transport_duplicates), ("15", g15_fault_semantics),
        ("16", g16_metrics), ("18", g18_calibration), ("19", g19_feedback_integrity)]
