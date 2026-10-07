#!/usr/bin/env python3
"""B1 confirmatory run on root 2026100514000 (prereg v1.5 @ 2473c2a; amended
pre-execution by v1.5.1 @ f4f5990).

Order (v1.5.1 §6–§8):
  0. refuse if any b1_confirmatory_* receipt exists; the confirmatory freeze
     must be done (b1_frozen.py), and every protected source must equal the
     sizing receipt's per-file hashes except b1_frozen.py, whose three fields
     are verified independently;
  1. write b1_confirmatory_STARTED;
  2. STAGE A — learning/logging only, all deployments; pooled SV; write
     b1_confirmatory_STAGE_A (SV) before any evaluation outcome exists;
  3. STAGE B — deterministic replay of the learning phase (must reproduce
     every stage-A theta hash) for OPE, then frozen-theta evaluation of all
     seven arms; per-deployment records outside the repository;
  4. frozen analysis (§7), diagnostics (§9), OPE (§5); b1_confirmatory_COMPLETED.
A crash after STARTED is preserved as b1_confirmatory_CRASHED."""
import argparse
import hashlib
import json
import pickle
import sys
import traceback
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lineage_b import b1_frozen as FZ, b1_runctl as rc, b1_stats as S  # noqa: E402
from lineage_b.b1_analysis import build_table, diagnostics, ope, sham_validity_aggregate  # noqa: E402
from lineage_b.b1_protocol import ALL_ARMS, stage_a, stage_b  # noqa: E402
from lineage_b.b1_seeds import ROOTS, TOKENS, bootstrap_rng, deployment_seeds, seed_list_sha256  # noqa: E402
from lineage_b.b1_validation import v0_static  # noqa: E402
from lineage_b.world import CONDITIONS  # noqa: E402


def _seeds(cond, dep):
    return deployment_seeds("confirmatory", TOKENS["confirmatory"], cond, dep)


def _stage_a(task):
    cond, dep, outdir = task
    eps, mu = _seeds(cond, dep)
    out, _ = stage_a(f"confirmatory:{cond}:{dep}", cond, eps, mu, ALL_ARMS)
    (Path(outdir) / f"A_{cond}_{dep:05d}.pkl").write_bytes(pickle.dumps(out))
    return cond, dep, out["sham_validity"]


def _stage_b(task):
    cond, dep, outdir = task
    eps, mu = _seeds(cond, dep)
    a_saved = pickle.loads((Path(outdir) / f"A_{cond}_{dep:05d}.pkl").read_bytes())
    a_replay, log = stage_a(f"confirmatory:{cond}:{dep}", cond, eps, mu, ALL_ARMS, ope=True)
    if a_replay["theta_hash"] != a_saved["theta_hash"] or a_replay["behavior_digest"] != a_saved["behavior_digest"]:
        raise RuntimeError(f"stage-B learning replay diverged from stage A at {(cond, dep)}")
    rec = stage_b(a_replay, eps, ALL_ARMS, ope_log=log)
    (Path(outdir) / f"B_{cond}_{dep:05d}.pkl").write_bytes(pickle.dumps(rec))
    return cond, dep


def preflight():
    if FZ.N is None or FZ.CONFIRMATORY_SEED_LIST_SHA256 is None or FZ.SIZING_RECEIPT is None:
        raise SystemExit("refusing to run: confirmatory freeze not performed (lineage_b/b1_frozen.py)")
    rc.require_clean_tree()
    rc.require_one_shot("b1_confirmatory")
    sizing_path = rc.ROOT / FZ.SIZING_RECEIPT
    sizing = json.loads(sizing_path.read_text())
    if not sizing.get("status", "").startswith("N determined"):
        raise SystemExit("refusing to run: sizing receipt does not determine N")
    fp = rc.source_fingerprint()
    freeze = rc.verify_post_sizing_freeze(sizing["source"]["files"], fp["files"],
                                          (rc.ROOT / rc.FROZEN_FILE).read_text(), sizing["sizing"]["N"],
                                          seed_list_sha256("confirmatory", FZ.N), FZ.SIZING_RECEIPT)
    if not freeze["pass"]:
        raise SystemExit(f"refusing to run: post-sizing code freeze violated: {freeze['problems']}")
    v0 = v0_static()
    if not v0["pass"]:
        raise SystemExit("refusing to run: V0 failed")
    return fp, freeze, v0, hashlib.sha256(sizing_path.read_bytes()).hexdigest()


def main(workers: int, outdir: Path):
    if rc.ROOT.resolve() in outdir.resolve().parents or outdir.resolve() == rc.ROOT.resolve():
        raise SystemExit("refusing to run: --outdir must be outside the repository")
    rc.require_empty_outdir(outdir)                                          # v1.5.2 §3
    fp, freeze, v0, sizing_sha = preflight()
    base = {"refs": rc.PREREG_REFS, "root": ROOTS["confirmatory"], "N": FZ.N,
            "seed_list_sha256": FZ.CONFIRMATORY_SEED_LIST_SHA256, "sizing_receipt": FZ.SIZING_RECEIPT,
            "sizing_receipt_sha256": sizing_sha, "source": fp, "post_sizing_freeze": freeze, "V0_static": v0}
    outdir.mkdir(parents=True, exist_ok=True)
    rc.write_receipt("b1_confirmatory_STARTED", {**base, "status": "STARTED"})
    try:
        tasks = [(c, d, str(outdir)) for c in CONDITIONS for d in range(FZ.N)]
        svs = []
        with Pool(workers) as pool:
            for k, (cond, dep, sv) in enumerate(pool.imap_unordered(_stage_a, tasks), 1):
                svs.append({"sham_validity": sv})
                print(f"stage A {k}/{len(tasks)}", flush=True)
        load = lambda f: pickle.loads(f.read_bytes())
        chk_a = rc.verify_record_set(outdir, ("A",), CONDITIONS, FZ.N, load)
        if not chk_a["pass"]:
            raise RuntimeError(f"stage-A record set invalid: {chk_a['problems']}")
        sv = sham_validity_aggregate(svs)
        rc.write_receipt("b1_confirmatory_STAGE_A", {**base, "status": "STAGE A complete", "sham_validity": sv})
        with Pool(workers) as pool:
            for k, _ in enumerate(pool.imap_unordered(_stage_b, tasks), 1):
                print(f"stage B {k}/{len(tasks)}", flush=True)
        chk_b = rc.verify_record_set(outdir, ("A", "B"), CONDITIONS, FZ.N, load)
        if not chk_b["pass"]:
            raise RuntimeError(f"stage-B record set invalid: {chk_b['problems']}")
        records = [pickle.loads(p.read_bytes()) for p in sorted(outdir.glob("B_*.pkl"))]
        table = build_table(records)
        n_by = {c: len(table[c]["G0"]["J"]) for c in CONDITIONS}
        idx = S.bootstrap_indices(bootstrap_rng("confirmatory", TOKENS["confirmatory"]), n_by, CONDITIONS)
        crit = S.criteria(table, idx, sv["pass"])
        out = {**base, "status": "COMPLETED", "sham_validity": sv, "criteria": crit,
               "diagnostics": diagnostics(records, table, idx),
               "ope": ope({c: [r["ope"] for r in records if r["condition"] == c] for c in CONDITIONS},
                          [a for a in ALL_ARMS if a != "REF-Z"])}
        print(json.dumps(rc.clean(crit["mapping"])))
        print("receipt:", rc.write_receipt("b1_confirmatory_COMPLETED", out))
        return 0
    except BaseException as e:
        rc.write_receipt("b1_confirmatory_CRASHED", {**base, "status": "CRASHED after STARTED",
                                                     "exception": f"{type(e).__name__}: {e}",
                                                     "traceback": traceback.format_exc()})
        raise


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--outdir", required=True, help="per-deployment records (outside the repository)")
    a = ap.parse_args()
    sys.exit(main(a.workers, Path(a.outdir)))
