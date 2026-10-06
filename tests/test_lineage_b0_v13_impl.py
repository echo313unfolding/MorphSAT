"""B0 v1.3 implementation-only tests: T1-T8 (prereg v1.3 @ 701c4c2, Amendment 3)
with T6 as superseded by v1.3.1 @ ebdb0f1, and the v1.3.1 reference-engine checks
R1-R5. Not validity gates and not tuning instruments. Receipt:
tools/run_lineage_b0_v13_impl.py (R1-R5 first; T1-T8 only if all R pass)."""

import heapq
import math
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lineage_b import params as P  # noqa: E402
from lineage_b.agent import predictor as pr  # noqa: E402
from lineage_b.agent.sensor_model import SensorModel  # noqa: E402
from lineage_b.world import FaultState, World, make_streams  # noqa: E402

FIXTURE_SEED = 130515            # v1.3 Amendment 2: evaluator-side fixture seed only
Q_BAR_IDX = 5
SENSORS = ("L1", "L2", "L3", "F", "P")


def _rng(i):
    return np.random.default_rng(np.random.SeedSequence(FIXTURE_SEED, spawn_key=(i,)))


# ================================================================ reference engine (v1.3.1)
# QUADPACK dqk15 constants (published values, parsed to double).
_XGK = np.array([0.991455371120812639206854697526329, 0.949107912342758524526189684047851,
                 0.864864423359769072789712788640926, 0.741531185599394439863864773280788,
                 0.586087235467691130294144845693013, 0.405845151377397166906606412076961,
                 0.207784955007898467600689403773245, 0.000000000000000000000000000000000])
_WGK = np.array([0.022935322010529224963732008058970, 0.063092092629978553290700663189204,
                 0.104790010322250183839876322541518, 0.140653259715525918745189590510238,
                 0.169004726639267902826583426598550, 0.190350578064785409913256402421014,
                 0.204432940075298892414161999234649, 0.209482141084727828012999174891714])
_WG = np.array([0.129484966168869693270611432679082, 0.279705391489276667901467771423780,
                0.381830050505118944950369775488975, 0.417959183673469387755102040816327])
Z_LIM, MAX_DEPTH, MAX_SUB = 12.0, 50, 2000
TAU_E, TAU_V = 1e-14, 1e-16


def _qk15(fn, a, b):
    c, hl = 0.5 * (a + b), 0.5 * (b - a)
    x = np.concatenate([c - hl * _XGK[:7], [c], c + hl * _XGK[6::-1]])
    fx = np.asarray(fn(x), float)
    fl, fc, fr = fx[:7], fx[7], fx[8:][::-1]
    k = _WGK[7] * fc + float((_WGK[:7] * (fl + fr)).sum())
    g = _WG[3] * fc + float((_WG[:3] * (fl[1::2] + fr[1::2])).sum())
    return k * hl, abs((k - g) * hl)


def pieces(z0):
    """[-12, 12], split at the kink z0 when it lies strictly inside."""
    return [(-Z_LIM, z0), (z0, Z_LIM)] if -Z_LIM < z0 < Z_LIM else [(-Z_LIM, Z_LIM)]


def adaptive(fn, parts, tau):
    """Global adaptive GK15: bisect the largest-error subinterval until the summed
    |K15 - G7| estimate is <= tau; depth <= 50, <= 2000 subintervals."""
    heap, n = [], 0
    for a, b in parts:
        r, e = _qk15(fn, a, b)
        heapq.heappush(heap, (-e, n, a, b, r, 0))
        n += 1
    tot = sum(-h[0] for h in heap)
    maxd = 0
    while True:
        if tot <= tau:
            exact_tot = math.fsum(-h[0] for h in heap)
            if exact_tot <= tau:
                return {"ok": True, "value": math.fsum(h[4] for h in heap), "err": exact_tot,
                        "n_sub": len(heap), "depth": maxd}
            tot = exact_tot
        if len(heap) + 1 > MAX_SUB:
            return {"ok": False, "reason": "max_subintervals", "err": tot, "n_sub": len(heap), "depth": maxd}
        e, _, a, b, r, d = heap[0]
        if d + 1 > MAX_DEPTH:
            return {"ok": False, "reason": "max_depth", "err": tot, "n_sub": len(heap), "depth": maxd}
        heapq.heappop(heap)
        mid = 0.5 * (a + b)
        tot += e                                   # e is -err
        for lo, hi in ((a, mid), (mid, b)):
            r2, e2 = _qk15(fn, lo, hi)
            heapq.heappush(heap, (-e2, n, lo, hi, r2, d + 1))
            n += 1
            tot += e2
        maxd = max(maxd, d + 1)


def _phi(z):
    return np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


def _Phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ---------------------------------------------------------------- R1-R5
R_FIXTURES = ((0.3, 0.05), (1.0, 0.05), (1.9, 1e-4), (0.3, 1e-4))


def _rcheck(name, fn, parts, exact):
    scale = max(1.0, abs(exact))
    res = adaptive(fn, parts, 1e-15 * scale)
    err = abs(res["value"] - exact) if res["ok"] else float("inf")
    return {"check": name, "exact": exact, "value": res.get("value"), "abs_err": err,
            "limit": 1e-14 * scale, "engine": {k: v for k, v in res.items() if k != "value"},
            "pass": bool(res["ok"] and err <= 1e-14 * scale)}


def r_checks():
    out = []
    for m, s in R_FIXTURES:
        parts = pieces(-m / s)
        a = m / s
        fx = f"m={m},sd={s}"
        out.append(_rcheck(f"R1 {fx}", lambda z: z * _phi(z), parts, 0.0))
        out.append(_rcheck(f"R2 {fx}", lambda z: z * z * _phi(z), parts, 1.0))
        out.append(_rcheck(f"R3 {fx}", lambda z, m=m, s=s: np.maximum(m + s * z, 0.0) * _phi(z), parts,
                           m * _Phi(a) + s * math.exp(-0.5 * a * a) / math.sqrt(2 * math.pi)))
        out.append(_rcheck(f"R4 {fx}", lambda z, m=m, s=s: np.maximum(m + s * z, 0.0) ** 2 * _phi(z), parts,
                           (m * m + s * s) * _Phi(a) + m * s * math.exp(-0.5 * a * a) / math.sqrt(2 * math.pi)))
    s = 0.05
    out.append(_rcheck("R5 m=0,sd=0.05", lambda z: np.sqrt(np.maximum(s * z, 0.0)) * _phi(z), pieces(0.0),
                       math.sqrt(s) * math.gamma(0.75) / (2 ** 0.75 * math.sqrt(math.pi))))
    return {"pass": all(c["pass"] for c in out), "checks": out}


# ================================================================ T1
def t1():
    q = float(pr.QG[Q_BAR_IDX])
    res, worst_all = [], 0.0
    for u, h0 in ((0.5, 1.0), (0.25, 0.5), (0.75, 1.5)):
        w = World(make_streams(np.random.SeedSequence(FIXTURE_SEED)), FaultState("C0"), 0, 0, None,
                  noise=False, h0=h0, u0=u)
        m, v, worst, leaks, q_const = h0, 0.0, 0.0, set(), True
        for _ in range(200):
            lk = w.z.leak
            leaks.add(lk)
            m, v = pr.level_step(m, v, q, u, P.K_LEAK[lk], sigma_w=0.0)
            w.step("hold", None)
            q_const &= w.z.q_in == q
            worst = max(worst, abs(float(m) - w.z.h))
        res.append({"fixture": f"world u={u} h0={h0}", "max_abs_err": worst, "world_leaks_seen": sorted(leaks),
                    "world_q_constant": q_const, "h_final": w.z.h})
        worst_all = max(worst_all, worst)
    h, m, v, worst = 0.004, 0.004, 0.0, 0.0
    k = P.K_LEAK["fast"]
    for _ in range(5):
        sq = math.sqrt(max(h, 0.0))
        h = min(max(h + (P.DT / P.A) * (0.0 - P.CV * 1.0 * sq - k * sq), 0.0), P.H_MAX)
        m, v = pr.level_step(m, v, 0.0, 1.0, k, sigma_w=0.0)
        worst = max(worst, abs(float(m) - h))
    res.append({"fixture": "map q=0 u=1 fast h0=0.004", "max_abs_err": worst, "h_final": h})
    worst_all = max(worst_all, worst)
    return {"pass": worst_all <= 1e-11 and all(r.get("world_q_constant", True) for r in res),
            "limit": 1e-11, "max_abs_err": worst_all, "fixtures": res}


# ================================================================ T2
def t2():
    q = float(pr.QG[Q_BAR_IDX])
    a = 1 - (P.DT / P.A) * P.CV * 0.5 / (2 * 1.0)
    vstar = P.SIGMA_W ** 2 / (1 - a * a)
    out = {}
    for name, v0 in (("from_0", 0.0), ("from_vstar", vstar)):
        m, v, rel, mdev = 1.0, v0, 0.0, 0.0
        for n in range(1, 201):
            m, v = pr.level_step(m, v, q, 0.5, 0.0)
            vref = vstar if v0 else P.SIGMA_W ** 2 * (1 - a ** (2 * n)) / (1 - a * a)
            rel, mdev = max(rel, abs(float(v) / vref - 1)), max(mdev, abs(float(m) - 1.0))
        out[name] = {"max_rel_var_err": rel, "max_mean_dev_m": mdev, "v_final": float(v)}
    ok = all(r["max_rel_var_err"] <= 1e-4 and r["max_mean_dev_m"] <= 1e-4 for r in out.values())
    return {"pass": ok, "a": a, "v_star": vstar, "limits": {"rel_var": 1e-4, "mean_m": 1e-4}, "cases": out}


# ================================================================ T3
def t3():
    B = pr.Belief(np.full((P.NQ, 3), 1 / (3 * P.NQ)), np.full((P.NQ, 3), 1.0), np.zeros((P.NQ, 3)))
    maxv = 0.0
    for _ in range(200):
        B = pr.predict(B, 0.5, False, sigma_w=0.0, Q=np.eye(P.NQ), hazard=0.0)
        maxv = max(maxv, float(B.v.max()))
    part1 = {"max_v": maxv, "limit": 1e-26, "pass": maxv <= 1e-26}
    q = float(pr.QG[Q_BAR_IDX])
    part2 = []
    for u, h0 in ((0.5, 1.0), (0.25, 0.5), (0.75, 1.5)):
        m, v, viol, worst_inc = h0, 0.05 ** 2, 0, 0.0
        for _ in range(200):
            m2, v2 = pr.level_step(m, v, q, u, 0.0, sigma_w=0.0)
            if float(v2) > float(v):
                viol += 1
                worst_inc = max(worst_inc, float(v2) - float(v))
            m, v = m2, v2
        part2.append({"fixture": f"u={u} h0={h0}", "violations": viol, "worst_increase": worst_inc,
                      "v_final": float(v)})
    ok2 = all(p["violations"] == 0 for p in part2)
    return {"pass": part1["pass"] and ok2, "point_masses": part1, "monotone": part2}


# ================================================================ T4
def _single(B, s, y, u, b, sig):
    kind = P.KIND[s]
    if kind == "level":
        return pr.update_linear(B, y, b, sig, 1.0)
    if kind == "pressure":
        return pr.update_linear(B, y, b, sig, P.P_GAIN)
    return pr.update_flow(B, y, u, b, sig)


def t4():
    rng = _rng(4)
    model = SensorModel()
    stats = {"updates": 0, "underflows": 0, "underflow_unchanged": 0, "norm_max": 0.0, "nonfinite": 0,
             "neg_var": 0, "var_increase_linear": 0}
    fails = []

    def check(B0, s, y, u):
        b, sig = model.params(s, 0)
        B1, uf = _single(B0, s, y, u, b, sig)
        stats["updates"] += 1
        if uf:
            stats["underflows"] += 1
            same = B1 is B0 or (np.array_equal(B1.pi, B0.pi) and np.array_equal(B1.m, B0.m)
                                and np.array_equal(B1.v, B0.v))
            stats["underflow_unchanged"] += int(same)
            if not same:
                fails.append(("underflow_changed", s, y))
            return B1
        nerr = abs(float(B1.pi.sum()) - 1.0)
        stats["norm_max"] = max(stats["norm_max"], nerr)
        finite = bool(np.isfinite(B1.pi).all() and np.isfinite(B1.m).all() and np.isfinite(B1.v).all())
        stats["nonfinite"] += int(not finite)
        stats["neg_var"] += int((B1.v < 0).any())
        if P.KIND[s] != "flow":
            inc = bool((B1.v > B0.v * (1 + 1e-12)).any())
            stats["var_increase_linear"] += int(inc)
        if nerr > 1e-12 or not finite or (B1.v < 0).any():
            fails.append(("invalid", s, y))
        return B1

    for _ in range(1000):
        pi = rng.dirichlet(np.ones(3 * P.NQ)).reshape(P.NQ, 3)
        m = rng.uniform(0.2, 1.8, (P.NQ, 3))
        v = 10 ** rng.uniform(-6, -2, (P.NQ, 3))
        B = pr.Belief(pi, m, v)
        u = float(rng.choice(P.U_LEVELS))
        subset = [s for s in SENSORS if rng.random() < 0.5] or [SENSORS[int(rng.integers(5))]]
        c = int(rng.choice(3 * P.NQ, p=pi.ravel()))
        h = rng.normal(m.ravel()[c], math.sqrt(v.ravel()[c]))
        ys = {"L1": h + P.NOMINAL_SIGMA["L1"] * rng.normal(), "L2": h + P.NOMINAL_SIGMA["L2"] * rng.normal(),
              "L3": h + P.SIGMA_L3 * rng.normal(), "F": P.CV * u * math.sqrt(max(h, 0)) + P.SIGMA_F * rng.normal(),
              "P": P.P_GAIN * h + P.SIGMA_P * rng.normal()}
        Bs = B
        for s in pr.ORDER:
            if s in subset:
                Bs = check(Bs, s, ys[s], u)
        for s in SENSORS:
            for y in (-100.0, 100.0):
                check(B, s, y, u)
        check(B, "F", P.SIGMA_F * rng.normal(), 0.0)
    ok = (not fails and stats["norm_max"] <= 1e-12 and stats["nonfinite"] == 0 and stats["neg_var"] == 0
          and stats["var_increase_linear"] == 0 and stats["underflow_unchanged"] == stats["underflows"])
    return {"pass": ok, "stats": stats, "failures": fails[:20], "limits": {"norm": 1e-12, "var_rel": 1e-12}}


# ================================================================ T5
def t5():
    from lineage_b.gates import gate13_belief
    model = SensorModel()
    out, ok = {}, True
    for h0 in (0.5, 1.0, 1.5):
        B = gate13_belief(h0)
        Bo, Bc = pr.predict(B, 0.75, False), pr.predict(B, 0.25, False)
        diff = float((Bo.pi * Bo.m).sum()) - float((Bc.pi * Bc.m).sum())
        ehat = float((pr.GH_W * np.sqrt(np.maximum(pr.gh_nodes(h0, 0.05 ** 2), 0.0))).sum())
        expect = -(P.DT / P.A) * P.CV * 0.5 * float(B.pi.sum()) * ehat
        rel = abs(diff - expect) / abs(expect)
        cat = {s: float(np.abs(pr.categorical(s, Bo, 0.75, *model.params(s, 0))[0]
                                - pr.categorical(s, Bc, 0.25, *model.params(s, 0))[0]).max())
               for s in ("L3", "F")}
        good = rel <= 1e-12 and diff != 0 and all(x > 0 for x in cat.values())
        ok &= good
        out[f"h0={h0}"] = {"mean_diff": diff, "expected": expect, "rel_err": rel, "categorical_max_abs_diff": cat,
                           "pass": good}
    return {"pass": ok, "limit_rel": 1e-12, "fixtures": out}


# ================================================================ T6 (v1.3.1)
RHO = 1e-3
T6_M = tuple(round(0.30 + 0.05 * i, 2) for i in range(33))
T6_SD = (1e-4, 2e-4, 5e-4, 1e-3, 2e-3, 5e-3, 1e-2, 2e-2, 5e-2)


def _f_spec(h, q, c):
    """Frozen f(h) = h + (dt/A)(q - c sqrt(max(h,0))), written from the spec (independent of the predictor)."""
    return h + (P.DT / P.A) * (q - c * np.sqrt(np.maximum(h, 0.0)))


def t6(progress=None):
    alpha = P.DT / P.A
    cases = [(u, lk) for u in P.U_LEVELS for lk in P.LEAKS]
    n, fails, ref_fail = 0, [], []
    worst = {"mean_ratio": 0.0, "var_ratio": 0.0, "mean_abs": 0.0, "var_abs": 0.0}
    eng = {"max_sub": 0, "max_depth": 0}
    var_lim = RHO * P.SIGMA_W ** 2 + 1e-15
    for m in T6_M:
        for sd in T6_SD:
            parts = pieces(-m / sd)
            nodes = pr.gh_nodes(m, sd * sd)
            for u, lk in cases:
                c = P.CV * u + P.K_LEAK[lk]
                mean_lim = RHO * P.SIGMA_W * alpha * c / (2 * math.sqrt(m)) + 1e-13
                for q in pr.QG:
                    q = float(q)
                    mu = pr.det_map(nodes, q, u, P.K_LEAK[lk])
                    gm, gv = pr.combine(mu, np.zeros_like(mu))
                    gm, gv = float(gm), float(gv)
                    rE = adaptive(lambda z: _f_spec(m + sd * z, q, c) * _phi(z), parts, TAU_E)
                    if rE["ok"]:
                        Er = rE["value"]
                        rV = adaptive(lambda z: (_f_spec(m + sd * z, q, c) - Er) ** 2 * _phi(z), parts, TAU_V)
                    else:
                        rV = {"ok": False, "reason": "mean_failed"}
                    n += 1
                    for r in (rE, rV):
                        if r.get("n_sub"):
                            eng["max_sub"] = max(eng["max_sub"], r["n_sub"])
                            eng["max_depth"] = max(eng["max_depth"], r["depth"])
                    if not (rE["ok"] and rV["ok"]):
                        ref_fail.append({"m": m, "sd": sd, "u": u, "leak": lk, "q": q,
                                         "E": rE.get("reason"), "V": rV.get("reason")})
                        continue
                    dE, dV = abs(gm - Er), abs(gv - rV["value"])
                    worst["mean_abs"] = max(worst["mean_abs"], dE)
                    worst["var_abs"] = max(worst["var_abs"], dV)
                    worst["mean_ratio"] = max(worst["mean_ratio"], dE / mean_lim)
                    worst["var_ratio"] = max(worst["var_ratio"], dV / var_lim)
                    if dE > mean_lim or dV > var_lim:
                        fails.append({"m": m, "sd": sd, "u": u, "leak": lk, "q": q, "dE": dE, "mean_lim": mean_lim,
                                      "dV": dV, "var_lim": var_lim})
            if progress:
                progress(m, sd, n)
    return {"pass": n == 49005 and not fails and not ref_fail, "n_points": n, "rho": RHO,
            "var_limit": var_lim, "worst": worst, "engine": eng, "reference_failures": ref_fail[:50],
            "n_reference_failures": len(ref_fail), "n_fail": len(fails), "failures": fails[:50]}


# ================================================================ T7
def t7():
    rng = _rng(7)
    worst_m, worst_v = 0.0, 0.0
    for n in (2, 11):
        for _ in range(500):
            a = rng.dirichlet(np.ones(n)) * rng.uniform(0.01, 1.0)
            m = rng.uniform(0.2, 1.8, n)
            v = 10 ** rng.uniform(-8, -2, n)
            _, mm, vv = pr.collapse(a, m, v)
            A = [Fraction(float(x)) for x in a]
            M = [Fraction(float(x)) for x in m]
            V = [Fraction(float(x)) for x in v]
            S = sum(A)
            mean = sum(x * y for x, y in zip(A, M)) / S
            var = sum(x * (y + (z - mean) ** 2) for x, y, z in zip(A, V, M)) / S
            worst_m = max(worst_m, abs(float(Fraction(float(mm)) - mean) / mean))
            worst_v = max(worst_v, abs(float(Fraction(float(vv)) - var) / var))
    return {"pass": worst_m <= 1e-12 and worst_v <= 1e-12, "limit_rel": 1e-12,
            "max_rel_mean_err": worst_m, "max_rel_var_err": worst_v, "mixtures": 1000}


# ================================================================ T8
def t8():
    s = P.SIGMA_W
    out, ok = [], True
    for mu in (-0.004, 0.0, 0.001, 1.0, 1.999, 2.0, 2.003):
        E, V = pr.censored(np.array(mu), s)
        E, V = float(E), float(V)
        a, b = 0.0, P.H_MAX
        za, zb = (a - mu) / s, (b - mu) / s
        Pa, Pb = _Phi(za), _Phi(zb)
        pa, pb = math.exp(-0.5 * za * za) / math.sqrt(2 * math.pi), math.exp(-0.5 * zb * zb) / math.sqrt(2 * math.pi)
        Er = mu + (a - mu) * Pa + (b - mu) * (1 - Pb) + s * (pa - pb)
        M2 = (a - mu) ** 2 * Pa + (b - mu) ** 2 * (1 - Pb) + s * s * (Pb - Pa) + s * ((a - mu) * pa - (b - mu) * pb)
        Vr = max(M2 - (Er - mu) ** 2, 0.0)
        good = abs(E - Er) <= 1e-9 and abs(V - Vr) <= 1e-11
        if mu == 1.0:
            good &= E == 1.0 and V == s * s
        ok &= good
        out.append({"mu": mu, "E": E, "E_ref": Er, "dE": abs(E - Er), "V": V, "V_ref": Vr, "dV": abs(V - Vr),
                    "pass": good})
    return {"pass": ok, "limits": {"E": 1e-9, "V": 1e-11}, "cases": out}


TESTS = [("T1", t1), ("T2", t2), ("T3", t3), ("T4", t4), ("T5", t5), ("T6", t6), ("T7", t7), ("T8", t8)]
