#!/usr/bin/env python3
"""A4V runner (A4V prereg v1.1 §9, v1.2 A1). Validity checks in order; any failure
stops the run before the claim is printed or a results receipt is written."""
import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lineage_a.evaluate import validate_posterior  # noqa: E402
from lineage_a.evaluate_a4v import EXPECTED_COUNTS, run  # noqa: E402

FROZEN_REF = "39766cc"
FROZEN = [f"lineage_a/{f}.py" for f in ("records", "generator", "world", "policies", "corollary", "evaluate")]
LA_RESULTS = ROOT / "receipts/lineage_a/lineage_a_results_20261004T215503Z.json"
LA_VALID = ROOT / "receipts/lineage_a/posterior_validation_20261004T215503Z.json"
OUT = ROOT / "receipts/lineage_a4v"


def clean(x):
    if isinstance(x, float) and math.isinf(x):
        return "inf"
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    return x


def stop(ts, checks, msg):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"a4v_ABORTED_{ts}.json").write_text(json.dumps(clean(checks), indent=1, default=str))
    sys.exit(f"A4V run stopped: {msg}")


if __name__ == "__main__":
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    checks = {}
    # 1. posterior validation reproduces Lineage A's
    val = validate_posterior()
    la_val = json.loads(LA_VALID.read_text())
    checks["1_posterior_validation"] = {
        k: val[k] for k in ("checks", "max_abs_diff", "passed")} | {"n_failures": len(val["failures"]),
        "matches_lineage_a": (val["checks"], len(val["failures"]), val["max_abs_diff"])
        == (la_val["checks"], len(la_val["failures"]), la_val["max_abs_diff"])}
    if not (val["passed"] and checks["1_posterior_validation"]["matches_lineage_a"]):
        stop(ts, checks, "posterior validation failed or did not reproduce")
    # 2. frozen files byte-identical
    diff = subprocess.run(["git", "diff", "--stat", FROZEN_REF, "--", *FROZEN], cwd=ROOT,
                          capture_output=True, text=True)
    checks["2_frozen_files"] = {"ref": FROZEN_REF, "diff_empty": diff.returncode == 0 and not diff.stdout.strip(),
                                "sha256": {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in FROZEN}}
    if not checks["2_frozen_files"]["diff_empty"]:
        stop(ts, checks, "frozen Lineage A files changed")
    # 3. invariants (unit tests)
    t = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_lineage_a4v.py",
                        "tests/test_lineage_a.py"], cwd=ROOT, capture_output=True, text=True)
    checks["3_tests"] = {"returncode": t.returncode, "tail": t.stdout.strip().splitlines()[-1:]}
    if t.returncode != 0:
        stop(ts, checks, "unit tests failed")
    res = run()
    la = json.loads(LA_RESULTS.read_text())
    checks["2b_pattern_set_sha256_match"] = res["pattern_set_sha256"] == la["pattern_set_sha256"]
    # 4. structural counts
    checks["4_structural_counts"] = {"got": res["structural_counts"],
                                     "match": {k: tuple(v) for k, v in res["structural_counts"].items()} == EXPECTED_COUNTS}
    # 5. E2 null identity (v1.2 A1): R(A4V) = 1 within each family; sham and pooled reported only
    nulls = [e for e in res["envs"].values() if e["stratum"] == "null"]
    fams = ("FAM-G", "FAM-T", "FAM-I")
    dev = max(abs(e[f]["veto"]["A4V"]["R"] - 1.0) for e in nulls for f in fams)
    checks["5_null_identity"] = {
        "n_null": len(nulls), "max_abs_R_minus_1_within_family": dev,
        "pass": len(nulls) == 4 and dev <= 1e-9,
        "diagnostic_pooled_R_A4V": [e["primary"]["veto"]["A4V"]["R"] for e in nulls],
        "diagnostic_sham_R": {f: [e[f]["veto"]["A4V-S"]["R"] for e in nulls] for f in fams + ("primary",)}}
    # 6. A4 reproduces Lineage A receipt
    worst = max(abs(e["primary"]["metrics"]["A4"][m] - la["envs"][k]["primary"]["A4"][m])
                for k, e in res["envs"].items() for m in e["primary"]["metrics"]["A4"])
    checks["6_a4_reproduces"] = {"max_abs_diff": worst, "pass": worst <= 1e-12}
    if not (checks["2b_pattern_set_sha256_match"] and checks["4_structural_counts"]["match"]
            and checks["5_null_identity"]["pass"] and checks["6_a4_reproduces"]["pass"]):
        stop(ts, checks, "post-evaluation validity check failed (claim not reported)")
    res["validity_checks"] = checks
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"posterior_validation_{ts}.json").write_text(json.dumps(val, indent=1, default=str))
    path = OUT / f"a4v_results_{ts}.json"
    path.write_text(json.dumps(clean(res), indent=1, default=str))
    print(json.dumps(clean(checks), indent=1))
    print(json.dumps(clean(res["claim"]), indent=1))
    print("receipt:", path)
