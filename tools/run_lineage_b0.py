#!/usr/bin/env python3
"""Lineage B0 validity run (B0 prereg v1.1 §8, §10; v1.3 + v1.3.1 amendments). Runs
gates 1–16, 18, 19; only if all pass, runs the gate-17 G0/REF-S variance
pilot. Writes a receipt either way; a failing run is recorded as ABORTED."""
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from lineage_b import gates, params  # noqa: E402


def clean(x):
    if isinstance(x, float) and (math.isinf(x) or math.isnan(x)):
        return str(x)
    if isinstance(x, dict):
        return {str(k): clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if hasattr(x, "item"):
        return x.item()
    return x


if __name__ == "__main__":
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = {"prereg": "docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_3.md @ 701c4c2 + "
                     "docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_3_1.md @ ebdb0f1 "
                     "(amend docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1.md @ 642d3fd)",
           "seeds": {"B0": gates.B0_SEED, "pilot": gates.PILOT_SEED, "B1": gates.B1_SEED},
           "runtime": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform()},
           "config_sha256": hashlib.sha256(json.dumps(
               {k: repr(v) for k, v in vars(params).items() if k.isupper()}, sort_keys=True).encode()).hexdigest(),
           "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted((ROOT / "lineage_b").rglob("*.py"))},
           "gates": {}}
    for name, fn in gates.FAST:
        t0 = time.time()
        r = fn()
        r["seconds"] = round(time.time() - t0, 1)
        out["gates"][name] = r
        print(f"gate {name}: {'PASS' if r['pass'] else 'FAIL'} ({r['seconds']}s)", flush=True)
    failed = [n for n, r in out["gates"].items() if not r["pass"]]
    if failed:
        out["status"] = "ABORTED"
        out["failed_gates"] = failed
        out["gates"]["17"] = {"pass": None, "note": "not run: earlier gate(s) failed"}
    else:
        out["gates"]["17"] = gates.g17_pilot()
        out["status"] = "PASSED"
    d = ROOT / "receipts" / "lineage_b0"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"b0_validity_{out['status']}_{ts}.json"
    path.write_text(json.dumps(clean(out), indent=1, default=str))
    print("status:", out["status"], "failed:", failed, "receipt:", path)
