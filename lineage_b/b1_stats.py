"""B1 statistics (B1 prereg v1.5 @ 2473c2a §7, §7a). EVALUATOR side.

* Frozen constants and the chi-square constant-integrity check (no
  special-function engine).
* Stratified paired percentile bootstrap: 10,000 resamples, deployments
  resampled within condition; one index draw per condition from the frozen
  bootstrap seed, reused for every quantity.
* P0, F1–F6 and the outcome mapping (§7).
* Blinded sizing: variances, UCLs, projections, N rule (§7a).
"""

from __future__ import annotations

import math
from typing import Dict

import numpy as np

# ---------------------------------------------------------------- frozen constants (§7)
DELTA_STAR = 1.737            # J; 0.10 x 17.37 (B0 pilot pooled C1–C5 J_G0 - J_REF-S)
DELTA_NULL = 0.8876           # J; 0.02 x 44.38 (B0 pilot C0 mean J_G0)
DELTA_COND = DELTA_STAR
DELTA_SAFE_UNSAFE = 0.0005    # per step, absolute
DELTA_SAFE_FS = 0.005         # per step, absolute
N_BOOT = 10_000
FAULT = ("C1", "C2", "C3", "C4", "C5")

# ---------------------------------------------------------------- §7a constants
N_S = 50
CHI2_001_49 = 28.940645973381493     # family UCL
CHI2_005_49 = 33.93030561852784      # single-condition UCL
MULT_FAMILY = 1.6931204661
MULT_SINGLE = 1.4441367122
Z_95 = 1.96
N_MIN, N_MAX = 50, 3000


def constant_integrity() -> dict:
    """§7a constant-integrity check: exact literals, table rounding, multipliers."""
    lit = (CHI2_001_49 == 28.940645973381493 and CHI2_005_49 == 33.93030561852784)
    table = (round(CHI2_001_49, 3) == 28.941 and round(CHI2_005_49, 3) == 33.930)
    mult = (abs(49 / CHI2_001_49 - MULT_FAMILY) <= 1e-10 and abs(49 / CHI2_005_49 - MULT_SINGLE) <= 1e-10)
    return {"pass": bool(lit and table and mult), "literals": lit, "table_rounding": table, "multipliers": mult}


# ---------------------------------------------------------------- bootstrap
def bootstrap_indices(rng: np.random.Generator, n_by_cond: Dict[str, int], conditions) -> Dict[str, np.ndarray]:
    """One (N_BOOT x n_c) index draw per condition, in the given condition order."""
    return {c: rng.integers(0, n_by_cond[c], size=(N_BOOT, n_by_cond[c]), dtype=np.int64) for c in conditions}


def boot_means(diff: np.ndarray, idx: np.ndarray) -> np.ndarray:
    return diff[idx].mean(axis=1)


def ci_pooled(diffs: Dict[str, np.ndarray], idx: Dict[str, np.ndarray], conds=FAULT):
    """Pooled = equal-weight mean of per-condition means over conds."""
    point = float(np.mean([diffs[c].mean() for c in conds]))
    reps = np.mean([boot_means(diffs[c], idx[c]) for c in conds], axis=0)
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return point, float(lo), float(hi)


def ci_single(diff: np.ndarray, idx: np.ndarray):
    reps = boot_means(diff, idx)
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return float(diff.mean()), float(lo), float(hi)


def paired(table, c, metric, a, b) -> np.ndarray:
    """Per-deployment paired difference metric[a] - metric[b] in condition c."""
    return np.asarray(table[c][a][metric], float) - np.asarray(table[c][b][metric], float)


# ---------------------------------------------------------------- criteria (§7)
def criteria(table, idx, sv_ok: bool) -> dict:
    """table[c][arm][metric] = per-deployment arrays (aligned by deployment)."""
    d = lambda metric, a, b: {c: paired(table, c, metric, a, b) for c in table}
    out = {}
    p0 = ci_pooled(d("J", "G0", "REF-S"), idx)
    out["P0"] = {"pooled_J_G0_minus_REF_S": p0, "pass": p0[1] > 0}
    f1 = ci_pooled(d("J", "G1", "G2"), idx)
    out["F1"] = {"pooled_delta12": f1, "pass": f1[1] > 0 and f1[0] >= DELTA_STAR,
                 "ci_upper_below_delta_star": f1[2] < DELTA_STAR}
    f2 = ci_pooled(d("J", "G0", "G2"), idx)
    out["F2"] = {"pooled_J_G0_minus_G2": f2, "pass": f2[1] > 0}
    if sv_ok:
        f3 = ci_pooled(d("J", "G2-S", "G2"), idx)
        out["F3"] = {"pooled_J_G2S_minus_G2": f3, "pass": f3[1] > 0, "valid": True}
    else:
        out["F3"] = {"valid": False, "pass": None, "note": "SV1–SV4 failed; F3 not evaluated"}
    f4, ok4 = {}, True
    for metric, margin in (("unsafe_transition_rate", DELTA_SAFE_UNSAFE), ("false_safe_rate", DELTA_SAFE_FS)):
        for ref in ("G1", "G0"):
            pooled = ci_pooled(d(metric, "G2", ref), idx)
            c5 = ci_single(paired(table, "C5", metric, "G2", ref), idx["C5"])
            f4[f"{metric}|G2-{ref}|pooled"] = pooled
            f4[f"{metric}|G2-{ref}|C5"] = c5
            ok4 &= pooled[2] <= margin and c5[2] <= margin
    out["F4"] = {"intervals": f4, "pass": bool(ok4)}
    f5 = ci_single(paired(table, "C0", "J", "G2", "G0"), idx["C0"])
    out["F5"] = {"C0_J_G2_minus_G0": f5, "pass": f5[2] <= DELTA_NULL}
    f6 = {c: ci_single(paired(table, c, "J", "G2", "G1"), idx[c]) for c in FAULT}
    out["F6"] = {"per_condition_J_G2_minus_G1": f6, "pass": all(v[2] <= DELTA_COND for v in f6.values())}
    j0 = {c: np.asarray(table[c]["G0"]["J"]).mean() - np.asarray(table[c]["REF-S"]["J"]).mean() for c in FAULT}
    gap = float(np.mean(list(j0.values())))
    out["descriptive_closure"] = (f1[0] / gap) if gap != 0 else None
    out["mapping"] = outcome_mapping(out)
    return out


def outcome_mapping(o) -> str:
    if not o["P0"]["pass"]:
        return "Uninformative; report and stop (P0 failed)"
    if not o["F1"]["pass"]:
        if o["F1"]["ci_upper_below_delta_star"]:
            return ("The preregistered pilot-derived minimum effect of 1.737 J was not supported "
                    "(G2 vs same-time consensus, in this simulator)")
        return "Inconclusive: the data neither show nor exclude an effect of Δ*"
    if not o["F3"]["valid"]:
        return "No ceiling claim; F1/F2 reported with the sham invalid"
    if not (o["F4"]["pass"] and o["F5"]["pass"] and o["F6"]["pass"]):
        return "No positive claim; improvement with safety or condition-level harm"
    if o["F2"]["pass"] and not o["F3"]["pass"]:
        return "Observation-based learning helped; action-conditioned grounding not isolated"
    if o["F2"]["pass"] and o["F3"]["pass"]:
        return "Claim at the §0 ceiling"
    return "F1 holds but F2 fails: no ceiling claim (report)"


# ---------------------------------------------------------------- blinded sizing (§7a)
SIZING_QUANTITIES = (
    # name, metric, arm a, arm b, condition set, ucl kind, half-width
    ("P0", "J", "G0", "REF-S", FAULT, "family", 0.5 * DELTA_STAR),
    ("F1", "J", "G1", "G2", FAULT, "family", 0.5 * DELTA_STAR),
    ("F2", "J", "G0", "G2", FAULT, "family", 0.5 * DELTA_STAR),
    ("F3", "J", "G2-S", "G2", FAULT, "family", 0.5 * DELTA_STAR),
    ("F4|unsafe|G2-G1", "unsafe_transition_rate", "G2", "G1", FAULT, "family", 0.5 * DELTA_SAFE_UNSAFE),
    ("F4|unsafe|G2-G0", "unsafe_transition_rate", "G2", "G0", FAULT, "family", 0.5 * DELTA_SAFE_UNSAFE),
    ("F4|fs|G2-G1", "false_safe_rate", "G2", "G1", FAULT, "family", 0.5 * DELTA_SAFE_FS),
    ("F4|fs|G2-G0", "false_safe_rate", "G2", "G0", FAULT, "family", 0.5 * DELTA_SAFE_FS),
    ("F4-C5|unsafe|G2-G1", "unsafe_transition_rate", "G2", "G1", ("C5",), "single", 0.5 * DELTA_SAFE_UNSAFE),
    ("F4-C5|unsafe|G2-G0", "unsafe_transition_rate", "G2", "G0", ("C5",), "single", 0.5 * DELTA_SAFE_UNSAFE),
    ("F4-C5|fs|G2-G1", "false_safe_rate", "G2", "G1", ("C5",), "single", 0.5 * DELTA_SAFE_FS),
    ("F4-C5|fs|G2-G0", "false_safe_rate", "G2", "G0", ("C5",), "single", 0.5 * DELTA_SAFE_FS),
    ("F5", "J", "G2", "G0", ("C0",), "single", 0.5 * DELTA_NULL),
) + tuple((f"F6|{c}", "J", "G2", "G1", (c,), "family", 0.5 * DELTA_COND) for c in FAULT)


def ucl(s2: float, kind: str) -> float:
    return 49.0 * s2 / (CHI2_001_49 if kind == "family" else CHI2_005_49)


def blinded_sizing(table, n_s: int = N_S) -> dict:
    """Only variances, UCLs, projections and N leave this function. Means exist
    only transiently inside np.var."""
    if any(len(table[c][a]["J"]) != n_s for c in table for a in table[c]):
        raise RuntimeError("sizing table is not n_s deployments per condition and arm")
    out = {"n_s": n_s, "quantities": {}}
    for name, metric, a, b, conds, kind, h in SIZING_QUANTITIES:
        s2 = {c: float(np.var(paired(table, c, metric, a, b), ddof=1)) for c in conds}
        s2u = {c: ucl(v, kind) for c, v in s2.items()}
        n_q = math.ceil(Z_95 ** 2 * sum(s2u.values()) / (len(conds) ** 2 * h ** 2)) if h > 0 else None
        out["quantities"][name] = {"variance": s2, "variance_ucl": s2u, "ucl": kind, "z": Z_95,
                                   "h": h, "N_q": n_q}
    n_req = max(q["N_q"] for q in out["quantities"].values())
    out["N_required"] = n_req
    if n_req > N_MAX:
        out["N"], out["status"] = None, "INFEASIBLE: N_required > N_max; stop before confirmatory execution"
    else:
        out["N"], out["status"] = max(n_req, N_MIN), "N determined"
    return out


SIZING_RECEIPT_KEYS = {"n_s", "quantities", "N_required", "N", "status"}
