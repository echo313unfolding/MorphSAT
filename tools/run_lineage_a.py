#!/usr/bin/env python3
"""Lineage A runner (prereg v1.3). Order is enforced:
1) Monte-Carlo posterior validation must pass;
2) only then are policy outcomes computed and the claim rule applied.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lineage_a.evaluate import run, validate_posterior  # noqa: E402

if __name__ == "__main__":
    out_dir = Path("receipts/lineage_a"); out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    v = validate_posterior()
    (out_dir / f"posterior_validation_{ts}.json").write_text(json.dumps(v, indent=1, default=str))
    print("posterior validation:", {k: v[k] for k in ("checks", "max_abs_diff", "passed")}, "failures:", len(v["failures"]))
    if not v["passed"]:
        sys.exit("posterior validation FAILED — primary results not computed")
    res = run()
    res["posterior_validation"] = {k: v[k] for k in ("checks", "max_abs_diff", "passed")}
    path = out_dir / f"lineage_a_results_{ts}.json"
    path.write_text(json.dumps(res, indent=1, default=str))
    print(json.dumps(res["claim"], indent=1)); print("receipt:", path)
