#!/usr/bin/env python3
"""B1 confirmatory run (prereg v1.5 @ 2473c2a §15 h). Refuses to start until
the confirmatory freeze has filled lineage_b/b1_frozen.py (N, seed-list
hash, sizing receipt). Runs all seven arms on root 2026100514000, then the
frozen analysis (§7), diagnostics (§9) and OPE (§5)."""
import argparse
import json
import pickle
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lineage_b import b1_frozen as FZ, b1_runctl as rc, b1_stats as S  # noqa: E402
from lineage_b.b1_analysis import build_table, diagnostics, ope, sham_validity_aggregate  # noqa: E402
from lineage_b.b1_protocol import ALL_ARMS, run_deployment  # noqa: E402
from lineage_b.b1_seeds import ROOTS, TOKENS, bootstrap_rng, deployment_seeds, seed_list_sha256  # noqa: E402
from lineage_b.b1_validation import v0_static  # noqa: E402
from lineage_b.world import CONDITIONS  # noqa: E402


def _one(task):
    cond, dep, outdir = task
    eps, mu = deployment_seeds("confirmatory", TOKENS["confirmatory"], cond, dep)
    rec = run_deployment(f"conf:{cond}:{dep}", cond, eps, mu, arms=ALL_ARMS, ope=True)
    (Path(outdir) / f"{cond}_{dep:05d}.pkl").write_bytes(pickle.dumps(rec))
    return cond, dep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--outdir", required=True, help="per-deployment records (not committed)")
    args = ap.parse_args()
    if FZ.N is None or FZ.CONFIRMATORY_SEED_LIST_SHA256 is None or FZ.SIZING_RECEIPT is None:
        raise SystemExit("refusing to run: confirmatory freeze not performed (lineage_b/b1_frozen.py)")
    if seed_list_sha256("confirmatory", FZ.N) != FZ.CONFIRMATORY_SEED_LIST_SHA256:
        raise SystemExit("refusing to run: confirmatory seed-list hash mismatch")
    rc.require_clean_tree()
    v0 = v0_static()
    if not v0["pass"]:
        raise SystemExit("refusing to run: V0 failed")
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    tasks = [(c, d, str(outdir)) for c in CONDITIONS for d in range(FZ.N)]
    with Pool(args.workers) as pool:
        for k, _ in enumerate(pool.imap_unordered(_one, tasks), 1):
            print(f"confirmatory progress {k}/{len(tasks)}", flush=True)
    records = [pickle.loads(p.read_bytes()) for p in sorted(outdir.glob("*.pkl"))]
    sv = sham_validity_aggregate(records)
    table = build_table(records)
    n_by = {c: len(table[c]["G0"]["J"]) for c in CONDITIONS}
    idx = S.bootstrap_indices(bootstrap_rng("confirmatory", TOKENS["confirmatory"]), n_by, CONDITIONS)
    crit = S.criteria(table, idx, sv["pass"])
    diag = diagnostics(records, table, idx)
    ope_in = {c: [r["ope"] for r in records if r["condition"] == c] for c in CONDITIONS}
    out = {"prereg": "docs/LINEAGE_B1_GROUNDED_FEEDBACK_PREREG_V1.md @ 2473c2a",
           "root": ROOTS["confirmatory"], "N": FZ.N, "seed_list_sha256": FZ.CONFIRMATORY_SEED_LIST_SHA256,
           "sizing_receipt": FZ.SIZING_RECEIPT, "source": rc.source_fingerprint(), "V0_static": v0,
           "sham_validity": sv, "criteria": crit, "diagnostics": diag,
           "ope": ope(ope_in, [a for a in ALL_ARMS if a != "REF-Z"])}
    print(json.dumps(rc.clean(crit["mapping"])))
    print("receipt:", rc.write_receipt("b1_confirmatory", out))
