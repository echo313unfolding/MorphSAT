"""B1 confirmatory analysis (prereg v1.5 @ 2473c2a §5–§7, §9). EVALUATOR side.
Runs only inside the confirmatory runner, after confirmatory execution."""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from lineage_b import b1_stats as S
from lineage_b.params import ACTIONS

METRICS = ("J", "unsafe_transition_rate", "false_safe_rate")


def build_table(records: List[dict]) -> Dict[str, Dict[str, Dict[str, np.ndarray]]]:
    """table[c][arm][metric] aligned by deployment index (sorted by deployment id)."""
    table: Dict[str, Dict[str, Dict[str, list]]] = {}
    for r in sorted(records, key=lambda r: (r["condition"], int(r["deployment"].rsplit(":", 1)[1]))):
        for arm, a in r["arms"].items():
            for m in METRICS:
                table.setdefault(r["condition"], {}).setdefault(arm, {}).setdefault(m, []).append(a["control"][m])
    return {c: {a: {m: np.asarray(v, float) for m, v in d.items()} for a, d in arms.items()}
            for c, arms in table.items()}


def sham_validity_aggregate(records: List[dict]) -> dict:
    sv = [r["sham_validity"] for r in records]
    n = sum(x["n"] for x in sv)
    differ = sum(x["n_differ"] for x in sv)
    kl_n = sum(x["kl_n"] for x in sv)
    out = {"SV1_all_deployments": all(x["sv1_marginals_equal"] for x in sv),
           "SV2_all_deployments": all(x["sv2_pairing_changed"] for x in sv),
           "SV3_fraction_differ": differ / n if n else 0.0,
           "SV4_mean_kl_nats": (sum(x["kl_sum"] for x in sv) / kl_n) if kl_n else 0.0,
           "SV3_min_deployment_fraction": min((x["n_differ"] / x["n"]) for x in sv if x["n"]) if n else 0.0}
    out["SV3"] = out["SV3_fraction_differ"] >= 0.80
    out["SV4"] = out["SV4_mean_kl_nats"] >= 0.05
    out["pass"] = out["SV1_all_deployments"] and out["SV2_all_deployments"] and out["SV3"] and out["SV4"]
    return out


def diagnostics(records, table, idx) -> dict:
    d = {"per_condition_means": {c: {a: {m: float(v.mean()) for m, v in ms.items()} for a, ms in arms.items()}
                                 for c, arms in table.items()}}
    d["G1_vs_G0_pooled_J"] = S.ci_pooled({c: S.paired(table, c, "J", "G0", "G1") for c in table}, idx)
    d["G2_minus_G3_J_per_condition"] = {c: S.ci_single(S.paired(table, c, "J", "G2", "G3"), idx[c]) for c in table}
    sec = {}
    for r in records:
        for a, rec in r["arms"].items():
            for k in ("action_error", "coverage", "selective_risk", "inspect_rate", "interlock_steps",
                      "terminal_abstain_steps"):
                v = rec["control"].get(k)
                if v is not None:
                    sec.setdefault(r["condition"], {}).setdefault(a, {}).setdefault(k, []).append(v)
            if a != "REF-Z":
                sec[r["condition"]][a].setdefault("regret", []).append(
                    rec["control"]["J"] - r["arms"]["REF-Z"]["control"]["J"])
    d["secondary_control_means"] = {c: {a: {k: float(np.mean(v)) for k, v in ks.items()} for a, ks in arms.items()}
                                    for c, arms in sec.items()}
    pred = {}
    for r in records:
        for a, rec in r["arms"].items():
            for key, v in rec.get("prediction", {}).items():
                pred.setdefault(r["condition"], {}).setdefault(a, {}).setdefault(key, []).append(v)
    d["prediction"] = {c: {a: {k: {m: float(np.mean([x[m] for x in vs])) for m in ("log_score", "brier", "cov90", "cov50")}
                               for k, vs in ks.items()} for a, ks in arms.items()} for c, arms in pred.items()}
    c0 = [r for r in records if r["condition"] == "C0"]
    d["C0_learned_noise"] = {a: {s: {"b_mean": float(np.mean([r["theta"][a][s][0] for r in c0])),
                                     "sigma_mean": float(np.mean([r["theta"][a][s][1] for r in c0]))}
                                 for s in ("L1", "L2", "L3", "F", "P")}
                             for a in (c0[0]["theta"] if c0 else {})}
    skips = {}
    for r in records:
        for a, rec in r["arms"].items():
            for k, v in rec.get("skips", {}).items():
                skips.setdefault(a, {}).setdefault(k, 0)
                skips[a][k] += v
    d["missing_pending_skips"] = skips
    return d


# ---------------------------------------------------------------- OPE (§5; secondary)
LAMBDA = 1.0


def _ridge(X, y, lam=LAMBDA):
    Xb = np.hstack([X, np.ones((len(X), 1))])
    A = Xb.T @ Xb + lam * np.eye(Xb.shape[1])
    return np.linalg.solve(A, Xb.T @ y)


def _pred(w, X):
    return np.hstack([X, np.ones((len(X), 1))]) @ w


def ope(ope_by_dep: Dict[str, List[dict]], arms) -> dict:
    """Per condition: 2 folds by deployment index parity; per-action ridge q-hat
    fitted on the other fold; IPS, DM, DR per deployment; truth = mean exact
    counterfactual reward. Reports bias, RMSE and 95% CI coverage."""
    out = {}
    for c, deps in ope_by_dep.items():
        res = {a: {"IPS": [], "DM": [], "DR": [], "DR_cover": [], "truth": []} for a in arms}
        for fold in (0, 1):
            train = [d for i, d in enumerate(deps) if i % 2 != fold]
            test = [d for i, d in enumerate(deps) if i % 2 == fold]
            if not train or not test:
                continue
            X = np.vstack([d["X"] for d in train])
            a_ = np.concatenate([d["a"] for d in train])
            r_ = np.concatenate([d["r"] for d in train])
            W = {k: _ridge(X[a_ == k], r_[a_ == k]) if (a_ == k).sum() > 0 else None for k in range(len(ACTIONS))}
            for d in test:
                n = len(d["r"])
                if n == 0:
                    continue
                Q = np.stack([_pred(W[k], d["X"]) if W[k] is not None else np.zeros(n)
                              for k in range(len(ACTIONS))])
                rows = np.arange(n)
                qa = Q[d["a"], rows]
                for arm in arms:
                    pi = d["pi"][arm]
                    qpi = Q[pi, rows]
                    match = (pi == d["a"]).astype(float)
                    ips = match / d["mu"] * d["r"]
                    dr = qpi + match / d["mu"] * (d["r"] - qa)
                    truth = float(d["r_pi"][arm].mean())
                    m, se = float(dr.mean()), float(dr.std(ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
                    res[arm]["IPS"].append(float(ips.mean()))
                    res[arm]["DM"].append(float(qpi.mean()))
                    res[arm]["DR"].append(m)
                    res[arm]["DR_cover"].append(abs(m - truth) <= 1.96 * se)
                    res[arm]["truth"].append(truth)
        out[c] = {}
        for arm, v in res.items():
            if not v["truth"]:
                continue
            t = np.array(v["truth"])
            out[c][arm] = {est: {"bias": float(np.mean(np.array(v[est]) - t)),
                                 "rmse": float(np.sqrt(np.mean((np.array(v[est]) - t) ** 2)))}
                           for est in ("IPS", "DM", "DR")}
            out[c][arm]["DR_ci95_coverage"] = float(np.mean(v["DR_cover"]))
    return out
