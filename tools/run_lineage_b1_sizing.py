#!/usr/bin/env python3
"""B1 §7a one-shot blinded sizing on root 2026100516000 (prereg v1.5 @ 2473c2a).

Order: chi-square constant-integrity check; V0 static re-assertion; the
sizing set (C0–C5 x n_s = 50; arms G0, G1, G2, G2-S, REF-S through the full
§1 protocol); SV1–SV4 before any variance is accepted; blinded variances and
N. Per-deployment metrics stay in memory and are never written, printed or
logged; the receipt carries only the §7a whitelist.

Refuses to start unless a PASSED §7b validation receipt exists for exactly
this source fingerprint."""
import argparse
import json
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lineage_b import b1_runctl as rc, b1_stats as S  # noqa: E402
from lineage_b.b1_analysis import sham_validity_aggregate  # noqa: E402
from lineage_b.b1_protocol import SIZING_ARMS, run_deployment  # noqa: E402
from lineage_b.b1_seeds import ROOTS, TOKENS, deployment_seeds  # noqa: E402
from lineage_b.b1_validation import v0_static  # noqa: E402
from lineage_b.world import CONDITIONS  # noqa: E402

METRICS = ("J", "unsafe_transition_rate", "false_safe_rate")


def _one(task):
    cond, dep = task
    eps, mu = deployment_seeds("sizing", TOKENS["sizing"], cond, dep)
    rec = run_deployment(f"siz:{cond}:{dep}", cond, eps, mu, arms=SIZING_ARMS)
    return cond, dep, {a: {m: rec["arms"][a]["control"][m] for m in METRICS} for a in SIZING_ARMS}, \
        rec["sham_validity"]


def _validation_passed(fp) -> bool:
    for p in sorted(rc.RECEIPTS.glob("b1_validation_PASSED_*.json")):
        r = json.loads(p.read_text())
        if r["source"]["combined"] == fp["combined"]:
            return True
    return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()
    rc.require_clean_tree()
    fp = rc.source_fingerprint()
    if not _validation_passed(fp):
        raise SystemExit("refusing to run: no PASSED §7b validation receipt for this source fingerprint")
    if list(rc.RECEIPTS.glob("b1_sizing_*.json")):
        raise SystemExit("refusing to run: a sizing receipt already exists (one-shot)")
    out = {"prereg": "docs/LINEAGE_B1_GROUNDED_FEEDBACK_PREREG_V1.md @ 2473c2a (§7a)",
           "root": ROOTS["sizing"], "source": fp}
    ci = S.constant_integrity()
    out["chi2_constant_integrity"] = ci
    v0 = v0_static()
    out["V0_static"] = v0
    if not (ci["pass"] and v0["pass"]):
        out["status"] = "STOPPED: constant-integrity or V0 failed"
        print(out["status"], "receipt:", rc.write_receipt("b1_sizing_STOPPED", out))
        raise SystemExit(1)
    tasks = [(c, d) for c in CONDITIONS for d in range(S.N_S)]
    table = {c: {a: {m: [None] * S.N_S for m in METRICS} for a in SIZING_ARMS} for c in CONDITIONS}
    svs = []
    with Pool(args.workers) as pool:
        for k, (cond, dep, metrics, sv) in enumerate(pool.imap_unordered(_one, tasks), 1):
            for a in SIZING_ARMS:
                for m in METRICS:
                    table[cond][a][m][dep] = metrics[a][m]
            svs.append({"sham_validity": sv})
            print(f"sizing progress {k}/{len(tasks)}", flush=True)       # counts only
    sv = sham_validity_aggregate(svs)
    out["sham_validity"] = sv
    if not sv["pass"]:
        out["status"] = "STOPPED: sham-design failure (SV1–SV4); sizing set not reused"
        del table
        print(out["status"], "receipt:", rc.write_receipt("b1_sizing_STOPPED", out))
        raise SystemExit(1)
    sizing = S.blinded_sizing(table)
    del table
    out["sizing"] = {k: sizing[k] for k in S.SIZING_RECEIPT_KEYS}
    out["status"] = sizing["status"]
    print("N_required:", sizing["N_required"], "N:", sizing["N"], "status:", sizing["status"])
    print("receipt:", rc.write_receipt("b1_sizing", out))
