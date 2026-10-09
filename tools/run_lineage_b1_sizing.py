#!/usr/bin/env python3
"""B1 §7a one-shot blinded sizing on root 2026100519000 (prereg v1.6 @ 58653eb,
run-control v1.6.1).

Order (v1.5.1 §6, §7; v1.6.1 root-scoped one-shot):
  0. refuse if any b1_sizing_* receipt exists for the current root, or if no
     PASSED §7b validation receipt matches this exact source fingerprint;
  1. chi-square constant-integrity check; V0 static re-assertion;
  2. write b1_sizing_STARTED (refs, per-file protected-source hashes, root, n_s);
  3. STAGE A — learning/logging only for C0–C5 x n_s (arms G0, G1, G2, G2-S,
     REF-S): SV1–SV4 inputs, no control outcome;
  4. pooled SV; on failure write b1_sizing_STOPPED and stop (no evaluation);
  5. STAGE B — frozen-theta evaluation of the stage-A models; blinded
     variances and N; write b1_sizing_COMPLETED.
Per-deployment metrics never leave memory; progress prints counts only. A
crash after STARTED is preserved as b1_sizing_CRASHED."""
import argparse
import json
import pickle
import sys
import traceback
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lineage_b import b1_runctl as rc, b1_stats as S  # noqa: E402
from lineage_b.b1_analysis import sham_validity_aggregate  # noqa: E402
from lineage_b.b1_protocol import SIZING_ARMS, stage_a, stage_b  # noqa: E402
from lineage_b.b1_seeds import ROOTS, TOKENS, deployment_seeds  # noqa: E402
from lineage_b.b1_validation import v0_static  # noqa: E402
from lineage_b.world import CONDITIONS  # noqa: E402

METRICS = ("J", "unsafe_transition_rate", "false_safe_rate")


def _seeds(cond, dep):
    return deployment_seeds("sizing", TOKENS["sizing"], cond, dep)


def _stage_a(task):
    cond, dep = task
    eps, mu = _seeds(cond, dep)
    out, _ = stage_a(f"sizing:{cond}:{dep}", cond, eps, mu, SIZING_ARMS)
    return cond, dep, out["sham_validity"], pickle.dumps(out)


def _stage_b(task):
    cond, dep, a_blob = task
    eps, _ = _seeds(cond, dep)
    rec = stage_b(pickle.loads(a_blob), eps, SIZING_ARMS)
    return cond, dep, {a: {m: rec["arms"][a]["control"][m] for m in METRICS} for a in SIZING_ARMS}


def _validation_passed(fp) -> bool:
    for p in rc.existing_receipts("b1_validation_PASSED"):
        if json.loads(p.read_text())["source"]["combined"] == fp["combined"]:
            return True
    return False


def main(workers: int):
    rc.require_clean_tree()
    rc.require_one_shot("b1_sizing", ROOTS["sizing"])
    fp = rc.source_fingerprint()
    if not _validation_passed(fp):
        raise SystemExit("refusing to run: no PASSED §7b validation receipt for this source fingerprint")
    base = {"refs": rc.PREREG_REFS, "root": ROOTS["sizing"], "n_s": S.N_S, "source": fp}
    ci, v0 = S.constant_integrity(), v0_static()
    if not (ci["pass"] and v0["pass"]):
        raise SystemExit(f"refusing to run: constant integrity {ci['pass']}, V0 {v0['pass']} (no seed opened)")
    rc.write_receipt("b1_sizing_STARTED", {**base, "status": "STARTED", "chi2_constant_integrity": ci,
                                           "V0_static": v0})
    try:
        tasks = [(c, d) for c in CONDITIONS for d in range(S.N_S)]
        blobs, svs = {}, []
        with Pool(workers) as pool:
            for k, (cond, dep, sv, blob) in enumerate(pool.imap_unordered(_stage_a, tasks), 1):
                blobs[(cond, dep)] = blob
                svs.append({"sham_validity": sv})
                print(f"stage A {k}/{len(tasks)}", flush=True)
        sv = sham_validity_aggregate(svs)
        if not sv["pass"]:
            path = rc.write_receipt("b1_sizing_STOPPED", {**base, "status": "STOPPED: sham-design failure "
                                    "(SV1–SV4); no evaluation outcome generated; sizing set not reused",
                                    "sham_validity": sv})
            print("STOPPED (SV) receipt:", path)
            return 1
        table = {c: {a: {m: [None] * S.N_S for m in METRICS} for a in SIZING_ARMS} for c in CONDITIONS}
        with Pool(workers) as pool:
            for k, (cond, dep, metrics) in enumerate(
                    pool.imap_unordered(_stage_b, [(c, d, blobs[(c, d)]) for c, d in tasks]), 1):
                for a in SIZING_ARMS:
                    for m in METRICS:
                        table[cond][a][m][dep] = metrics[a][m]
                print(f"stage B {k}/{len(tasks)}", flush=True)
        sizing = S.blinded_sizing(table)
        del table
        path = rc.write_receipt("b1_sizing_COMPLETED", {**base, "status": sizing["status"], "sham_validity": sv,
                                                        "sizing": {k: sizing[k] for k in S.SIZING_RECEIPT_KEYS}})
        print("N_required:", sizing["N_required"], "N:", sizing["N"], "status:", sizing["status"])
        print("receipt:", path)
        return 0
    except BaseException as e:
        rc.write_receipt("b1_sizing_CRASHED", {**base, "status": "CRASHED after STARTED; sizing set not reused",
                                               "exception": f"{type(e).__name__}: {e}",
                                               "traceback": traceback.format_exc()})
        raise


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    sys.exit(main(ap.parse_args().workers))
