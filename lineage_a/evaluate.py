"""Evaluation (prereg v1.1 §6, v1.2 Amendment 1, v1.3 Amendments 1–2).

Ground truth (posterior quantities) is joined here only; policies never see it.
"""

from __future__ import annotations

import hashlib
import json
import random
from collections import defaultdict
from typing import Dict, List

from lineage_a import corollary as cor
from lineage_a.generator import fam_g, fam_i, fam_t
from lineage_a.policies import ABSTAIN, ACCEPT, POLICIES, REJECT, s2_shuffle_sham
from lineage_a.records import BENIGN, declared_view, opposite
from lineage_a.world import ENVS, Env, posterior, sample_directions

EPS = 1e-12
PRIMARY_C = ["A1", "A2", "A3a", "A3b", "A4", "A5n"]
ALL_POLICIES = ["A1", "A2", "A3a", "A3b", "A4", "A5", "A5n", "S1", "S2", "S3", "S4",
                "C1", "C2", "REF"]


def decide_all(p) -> Dict[str, str]:
    out = {name: fn(p.records) for name, fn in POLICIES.items()}
    out["S2"] = s2_shuffle_sham(p.records, p.pid)
    dv = declared_view(p.records)
    out["C1"] = cor.c1_declared_origin(dv)
    out["C2"] = cor.c2_agreement_credit(dv)
    return out


def _ref(q: float) -> str:
    return ACCEPT if q > 0.5 else REJECT if q < 0.5 else ABSTAIN


def pattern_outcome(decision: str, post: Dict[str, float], c: str) -> Dict[str, float]:
    q, t = post["q"], post["t_post"]
    acc, rej = decision == ACCEPT, decision == REJECT
    belief = c if acc else opposite(c) if rej else None
    return {
        "decided": 1.0 if (acc or rej) else 0.0,
        "err": (1 - q) if acc else q if rej else 0.0,
        "false_safe": t if belief == BENIGN else 0.0,
        "mc": post["mc"] if acc else 0.0,
        "CCA": q if acc else 0.0, "ICA": (1 - q) if acc else 0.0,
        "CCR": (1 - q) if rej else 0.0, "ICR": q if rej else 0.0,
    }


def weights(patterns, posts) -> Dict[str, float]:
    """v1.3 A2: within each structure cell, normalize Z over its direction
    variants; cells weighted equally within a family."""
    cells = defaultdict(list)
    for p in patterns:
        cells[p.cell].append(p)
    w = {}
    n_cells = len(cells)
    for cell, ps in cells.items():
        z = sum(posts[p.pid]["Z"] for p in ps)
        for p in ps:
            w[p.pid] = (posts[p.pid]["Z"] / z) / n_cells
    return w


def aggregate(fam_sets, decisions, posts, weight_maps, policy) -> Dict[str, float]:
    """Families weighted equally; returns weighted means and derived metrics."""
    keys = ["decided", "err", "false_safe", "mc", "CCA", "ICA", "CCR", "ICR"]
    acc = {k: 0.0 for k in keys}
    for fam, ps in fam_sets.items():
        fw = 1.0 / len(fam_sets)
        for p in ps:
            o = pattern_outcome(decisions[p.pid][policy], posts[p.pid], p.correction.direction)
            for k in keys:
                acc[k] += fw * weight_maps[fam][p.pid] * o[k]
    cov = acc["decided"]
    return {"coverage": cov, "selective_risk": (acc["err"] / cov) if cov > EPS else 0.0,
            "abstention": 1.0 - cov, "false_safe": acc["false_safe"],
            "mc_failures": acc["mc"], "CCA": acc["CCA"], "ICA": acc["ICA"],
            "CCR": acc["CCR"], "ICR": acc["ICR"]}


def dominates(x: Dict[str, float], y: Dict[str, float]) -> bool:
    le = x["selective_risk"] <= y["selective_risk"] + EPS
    ge = x["coverage"] >= y["coverage"] - EPS
    strict = (x["selective_risk"] < y["selective_risk"] - EPS
              or x["coverage"] > y["coverage"] + EPS)
    return le and ge and strict


def validate_posterior(n_draws: int = 10000, seed: int = 20261004) -> Dict[str, object]:
    """v1.3 A2 Monte-Carlo check of the exact posterior."""
    g = fam_g()
    cells = {}
    for p in g:
        if p.meta["n_pre"] == 2 and p.meta["n_post"] == 2 and p.meta["c"] == BENIGN:
            cells.setdefault(p.meta["structure"], p)
    t = [p for p in fam_t() if p.meta["b"] == 2 and p.meta["j"] == 1 and p.meta["c"] == BENIGN]
    probes = list(cells.values()) + t[:1]
    rng = random.Random(seed)
    worst, checks, failures = 0.0, 0, []
    for env in ENVS:
        for p in probes:
            counts = defaultdict(lambda: [0, 0])          # dirs-pattern -> [n, valid]
            c = p.correction.direction
            for _ in range(n_draws):
                dirs, x_post, adv = sample_directions(p, env, rng)
                key = tuple(c if dirs[r.order] == "ADV" else dirs[r.order]
                            for r in sorted(p.records, key=lambda r: r.order))
                counts[key][0] += 1
                counts[key][1] += x_post == c
            for key, (n, v) in counts.items():
                if n < 200:
                    continue
                recs = tuple(type(r)(r.order, d, r.source_id, r.upstream_id, r.is_correction)
                             for r, d in zip(sorted(p.records, key=lambda r: r.order), key))
                if recs[[r.is_correction for r in recs].index(True)].direction != c:
                    continue                               # correction claim must match
                q = posterior(type(p)(p.pid, p.family, p.cell, recs), env)["q"]
                emp = v / n
                se = (q * (1 - q) / n) ** 0.5
                checks += 1
                worst = max(worst, abs(emp - q))
                if abs(emp - q) > 3 * se + 0.005:
                    failures.append({"env": env.key, "pid": p.pid, "dirs": key,
                                     "n": n, "emp": emp, "exact": q})
    return {"checks": checks, "failures": failures, "max_abs_diff": worst,
            "passed": checks > 0 and not failures}


def run() -> Dict[str, object]:
    g, t = fam_g(), fam_t()
    i_set = fam_i(g)
    assert (len(g), len(t), len(i_set)) == (248, 54, 20)
    all_p = g + t
    decisions = {p.pid: decide_all(p) for p in all_p}
    out = {"pattern_counts": {"FAM-G": len(g), "FAM-T": len(t), "FAM-I": len(i_set)},
           "pattern_set_sha256": hashlib.sha256(json.dumps(
               [[p.pid, [list(r.__dict__.values()) for r in p.records]] for p in all_p]
           ).encode()).hexdigest(),
           "envs": {}}
    for env in ENVS:
        posts = {p.pid: posterior(p, env) for p in all_p}
        for p in all_p:
            decisions[p.pid]["REF"] = _ref(posts[p.pid]["q"])
        wmap = {"FAM-G": weights(g, posts), "FAM-T": weights(t, posts),
                "FAM-I": weights(i_set, posts)}
        primary = {"FAM-G": g, "FAM-T": t}
        res = {pol: aggregate(primary, decisions, posts, wmap, pol) for pol in ALL_POLICIES}
        famI = {pol: aggregate({"FAM-I": i_set}, decisions, posts, wmap, pol) for pol in ALL_POLICIES}
        famT = {pol: aggregate({"FAM-T": t}, decisions, posts, wmap, pol) for pol in ALL_POLICIES}
        # D1: manufactured-corroboration structures within FAM-G
        mc_set = [p for p in g if p.meta["structure"] in ("A-corr", "B-corr")]
        d1 = {pol: aggregate({"MC": mc_set}, decisions, posts, {"MC": weights(mc_set, posts)}, pol)
              for pol in ("A5", "A4", "A5n", "C1", "C2")}
        out["envs"][env.key] = {"env": env.__dict__, "primary": res, "FAM-I": famI,
                                "FAM-T": famT, "D1_mc_structures": d1}
    # D3 trust inflation (environment-independent: depends only on records)
    infl = defaultdict(list)
    for p in g:
        if p.meta["post_dir"] == "support" and p.meta["n_post"] >= 2 and p.meta["structure"] in ("B-corr", "C"):
            rel = cor.c2_reliabilities(declared_view(p.records))
            post_src = {r.source_id for r in p.records if r.order > p.correction.order}
            infl[p.meta["structure"]].append(sum(rel[s] for s in post_src | {"S_c"}) / len(post_src | {"S_c"}))
    out["D3_mean_C2_reliability"] = {k: sum(v) / len(v) for k, v in infl.items()}
    out["claim"] = claim(out["envs"])
    out["coverage_bands"] = coverage_bands(out["envs"])
    out["diagnostics"] = diagnostics(out["envs"])
    return out


def claim(envs) -> Dict[str, object]:
    """v1.2 Amendment 1 primary claim rule (unchanged by v1.3)."""
    n = len(envs)
    need = 18
    c1 = sum(not any(dominates(e["primary"][o], e["primary"]["A5"]) for o in PRIMARY_C)
             for e in envs.values())
    c2 = sum(any(dominates(e["primary"]["A5"], e["primary"][o]) for o in ("A1", "A2", "A3b"))
             for e in envs.values())
    mc_envs = [e for e in envs.values() if e["env"]["alpha"] == 0.3 and e["env"]["rho"] in (0.5, 1.0)]
    mc_vs_a4 = all(e["primary"]["A5"]["mc_failures"] < e["primary"]["A4"]["mc_failures"] - EPS for e in mc_envs)
    mc_vs_a5n = all(e["primary"]["A5"]["mc_failures"] < e["primary"]["A5n"]["mc_failures"] - EPS for e in mc_envs)
    mc_vs_s2 = sum(e["primary"]["A5"]["mc_failures"] < e["primary"]["S2"]["mc_failures"] - EPS for e in mc_envs)
    c4 = sum((not dominates(e["primary"]["S1"], e["primary"]["A5"]))
             and (not dominates(e["primary"]["S2"], e["primary"]["A5"]))
             and dominates(e["primary"]["A5"], e["primary"]["S2"]) for e in envs.values())
    crit = {
        "1_non_domination": {"envs": c1, "of": n, "pass": c1 >= need},
        "2_frequent_dominance": {"envs": c2, "of": n, "pass": c2 >= need},
        "3_mc": {"mc_envs": len(mc_envs), "fewer_than_A4_all": mc_vs_a4,
                 "fewer_than_A5n_all": mc_vs_a5n, "fewer_than_S2": mc_vs_s2,
                 "pass": mc_vs_a4 and mc_vs_a5n and mc_vs_s2 >= 0.75 * len(mc_envs)},
        "4_shams": {"envs": c4, "of": n, "pass": c4 >= need},
    }
    return {"criteria": crit, "supported": all(v["pass"] for v in crit.values())}


def coverage_bands(envs) -> Dict[str, object]:
    out = {}
    for comp in PRIMARY_C:
        bands = {}
        for band in (0.05, 0.10, 0.20):
            k = 0
            for e in envs.values():
                a, b = e["primary"]["A5"], e["primary"][comp]
                dc = b["coverage"] - a["coverage"]
                if dc <= band + EPS and a["false_safe"] <= b["false_safe"] + EPS \
                        and a["ICA"] <= b["ICA"] + EPS and a["selective_risk"] <= b["selective_risk"] + EPS:
                    k += 1
            bands[str(band)] = k
        out[comp] = bands
    return out


def diagnostics(envs) -> Dict[str, object]:
    a = [e["env"] for e in envs.values()]
    d2 = {k: [e["primary"]["C2"][k] - e["primary"]["C1"][k] for e in envs.values()]
          for k in ("ICA", "false_safe", "mc_failures", "selective_risk", "coverage")}
    return {"D2_C2_minus_C1_mean": {k: sum(v) / len(v) for k, v in d2.items()},
            "D2_C2_minus_C1_max": {k: max(v) for k, v in d2.items()},
            "n_envs": len(a)}
