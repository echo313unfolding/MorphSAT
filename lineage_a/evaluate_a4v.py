"""A4V evaluation (A4V prereg v1.1 §5–§9). Reuses the frozen Lineage A
generator, world, weights and aggregate unchanged; ground truth joined here only.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from typing import Dict, Optional

from lineage_a import a4v as v
from lineage_a.evaluate import EPS, aggregate, uniform_weights, weights
from lineage_a.generator import fam_g, fam_i, fam_t
from lineage_a.policies import ACCEPT, a4_corroboration
from lineage_a.world import ENVS, posterior

POLS = ["A4", "A4V", "A4V-S", "A4V-W", "A4V-corr", "A4V-oth"]
VETOES = ["A4V", "A4V-S", "A4V-W", "A4V-corr", "A4V-oth"]
NEED = 15                                    # 75% of 20 non-null envs
EXPECTED_COUNTS = {"FAM-G": (80, 32, 64, 20), "FAM-T": (18, 6, 12, 2), "FAM-I": (20, 8, 16, 4)}


def decide(p) -> Dict[str, str]:
    r = p.records
    return {"A4": a4_corroboration(r), "A4V": v.a4v(r), "A4V-S": v.a4v_shuffle_sham(r, p.pid),
            "A4V-W": v.a4v_wide(r), "A4V-corr": v.a4v_corr_alias(r),
            "A4V-oth": v.a4v_other_alias(r)}


def structural_counts(fams, decisions) -> Dict[str, list]:
    out = {}
    for name, ps in fams.items():
        acc = sum(decisions[p.pid]["A4"] == ACCEPT for p in ps)
        cnt = [sum(decisions[p.pid][k] != decisions[p.pid]["A4"] for p in ps)
               for k in ("A4V", "A4V-W", "A4V-S")]
        out[name] = [acc] + cnt
    return out


def _num(x: Optional[float]):
    if x is None:
        return None
    return "inf" if math.isinf(x) else x


def veto_stats(a4: Dict[str, float], x: Dict[str, float]) -> Dict[str, object]:
    d_ica, d_cca = a4["ICA"] - x["ICA"], a4["CCA"] - x["CCA"]
    noop = d_ica <= EPS and d_cca <= EPS
    if noop:
        r, bcr, prec = 1.0, None, None
    elif d_cca <= EPS:
        r, bcr, prec = math.inf, math.inf, 1.0
    else:
        r = (d_ica / a4["ICA"]) / (d_cca / a4["CCA"])
        bcr, prec = d_ica / d_cca, d_ica / (d_ica + d_cca)
    base = a4["ICA"] / (a4["ICA"] + a4["CCA"]) if a4["ICA"] + a4["CCA"] > EPS else None
    return {"R": r, "BCR": bcr, "precision": prec, "a4_accept_error_base_rate": base,
            "dICA": d_ica, "dCCA": d_cca, "d_coverage": a4["coverage"] - x["coverage"],
            "d_false_safe": a4["false_safe"] - x["false_safe"],
            "d_mc": a4["mc_failures"] - x["mc_failures"],
            "d_selective_risk": a4["selective_risk"] - x["selective_risk"], "noop": noop}


def bands(a4, x) -> Dict[str, bool]:
    dc = a4["coverage"] - x["coverage"]
    ok = (x["false_safe"] <= a4["false_safe"] + EPS and x["ICA"] <= a4["ICA"] + EPS
          and x["selective_risk"] <= a4["selective_risk"] + EPS)
    return {str(b): bool(dc <= b + EPS and ok) for b in (0.05, 0.10, 0.20)}


def _block(res) -> Dict[str, object]:
    return {"metrics": res, "veto": {k: veto_stats(res["A4"], res[k]) for k in VETOES}}


def stratum(env) -> str:
    if env["rho"] == 0 and env["alpha"] == 0:
        return "null"
    if env["alpha"] == 0:
        return "dependence"
    return "attack_rho0" if env["rho"] == 0 else "attack_rho>0"


def run() -> Dict[str, object]:
    g, t = fam_g(), fam_t()
    i_set = fam_i(g)
    all_p = g + t
    decisions = {p.pid: decide(p) for p in all_p}
    out = {"pattern_set_sha256": hashlib.sha256(json.dumps(
               [[p.pid, [list(r.__dict__.values()) for r in p.records]] for p in all_p]
           ).encode()).hexdigest(),
           "structural_counts": structural_counts({"FAM-G": g, "FAM-T": t, "FAM-I": i_set}, decisions),
           "veto_structures": {k: dict(Counter(p.meta["structure"] for p in all_p
                                               if decisions[p.pid][k] != decisions[p.pid]["A4"]))
                               for k in VETOES},
           "envs": {}}
    for env in ENVS:
        posts = {p.pid: posterior(p, env) for p in all_p}
        wmap = {"FAM-G": weights(g, posts), "FAM-T": weights(t, posts),
                "FAM-I": weights(i_set, posts)}
        umap = {"FAM-G": uniform_weights(g, posts), "FAM-T": uniform_weights(t, posts)}
        agg = lambda fams, wm: {k: aggregate(fams, decisions, posts, wm, k) for k in POLS}
        prim = agg({"FAM-G": g, "FAM-T": t}, wmap)
        e = {"env": env.__dict__, "stratum": stratum(env.__dict__),
             "primary": _block(prim),
             "bands_A4V_vs_A4": bands(prim["A4"], prim["A4V"]),
             "FAM-G": _block(agg({"FAM-G": g}, wmap)),
             "FAM-T": _block(agg({"FAM-T": t}, wmap)),
             "FAM-I": _block(agg({"FAM-I": i_set}, wmap)),
             "unweighted_secondary": _block(agg({"FAM-G": g, "FAM-T": t}, umap))}
        # A4V-W residual: A4 accepts with n_up < K left un-vetoed by A4V (weighted mass)
        res_mass = 0.0
        for fam, ps in (("FAM-G", g), ("FAM-T", t)):
            for p in ps:
                d = decisions[p.pid]
                if d["A4"] == ACCEPT and d["A4V-W"] != d["A4"] and d["A4V"] == d["A4"]:
                    res_mass += 0.5 * wmap[fam][p.pid]
        e["A4V_W_residual_mass_not_vetoed_by_A4V"] = res_mass
        out["envs"][env.key] = e
    out["claim"] = claim_v(out["envs"])
    out["strata_macro"] = strata_macro(out["envs"])
    return out


def claim_v(envs) -> Dict[str, object]:
    nb = [e for e in envs.values() if e["stratum"] != "null"]
    assert len(nb) == 20
    vt = lambda e, k: e["primary"]["veto"][k]
    m = lambda e, k: e["primary"]["metrics"][k]
    v1 = sum(vt(e, "A4V")["R"] >= 2 for e in nb)
    v2 = sum(vt(e, "A4V")["R"] > vt(e, "A4V-S")["R"] + EPS for e in nb)
    v3 = sum(m(e, "A4V")["selective_risk"] < m(e, "A4")["selective_risk"] - EPS for e in nb)
    band20_fail = sum(not e["bands_A4V_vs_A4"]["0.2"] for e in nb)
    mean = lambda k: sum(vt(e, "A4V")[k] for e in nb) / len(nb)
    macro_bcr = mean("dICA") / mean("dCCA") if mean("dCCA") > EPS else math.inf
    p1, p2, p3 = v1 >= NEED, v2 >= NEED, v3 >= NEED
    withheld = band20_fail > 5          # v1.2 A2: coverage condition only; BCR has no cutoff
    if not p1:
        verdict = "CLOSED: detector, not authority information (V1 fails)"
    elif not p2:
        verdict = "CLOSED: not specific to true upstream structure (V2 fails)"
    elif p3:
        verdict = ("CANDIDATE GUARD (specific; risk-lowering); operationally useful label "
                   + ("WITHHELD" if withheld else "not withheld"))
    else:
        verdict = "SPECIFIC BUT NOT RISK-LOWERING (V1, V2 pass; V3 fails)"
    return {"V1_R_ge_2": {"envs": v1, "of": 20, "pass": p1},
            "V2_R_gt_sham": {"envs": v2, "of": 20, "pass": p2},
            "V3_risk_lower": {"envs": v3, "of": 20, "pass": p3},
            "band_0.20_failures_in_nonnull": band20_fail,
            "macro_BCR_nonnull": _num(macro_bcr), "BCR_equal_cost_reference": 1.0,
            "operationally_useful_withheld": withheld,
            "specific_signal_in_generator": p1 and p2,
            "verdict": verdict}


def strata_macro(envs) -> Dict[str, object]:
    out = {}
    for s in ("null", "dependence", "attack_rho0", "attack_rho>0"):
        es = [e for e in envs.values() if e["stratum"] == s]
        row = {}
        for k in VETOES:
            st = [e["primary"]["veto"][k] for e in es]
            d_i = sum(x["dICA"] for x in st) / len(st)
            d_c = sum(x["dCCA"] for x in st) / len(st)
            rs = sorted(x["R"] for x in st)
            row[k] = {"R_min": _num(rs[0]), "R_max": _num(rs[-1]),
                      "macro_BCR": _num(d_i / d_c) if d_c > EPS else ("inf" if d_i > EPS else None),
                      "mean_d_coverage": sum(x["d_coverage"] for x in st) / len(st)}
        out[s] = {"n_envs": len(es), "veto": row}
    return out
