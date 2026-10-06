#!/usr/bin/env python3
"""B0 v1.3 implementation-only run (prereg v1.3 @ 701c4c2 Amendment 3; T6 and R1-R5
per v1.3.1 @ ebdb0f1). R1-R5 run first; if any fails, STOP (the reference does not
judge GH20 and T1-T8 do not run). Otherwise T1-T8 run once. Writes a receipt either way."""
import hashlib
import json
import platform
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import test_lineage_b0_v13_impl as T  # noqa: E402


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if hasattr(x, "item"):
        return x.item()
    if isinstance(x, float) and x != x:
        return "nan"
    return x


def _run(fn, **kw):
    t0 = time.time()
    try:
        r = fn(**kw)
    except Exception:
        r = {"pass": False, "exception": traceback.format_exc()}
    r["seconds"] = round(time.time() - t0, 1)
    return r


if __name__ == "__main__":
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = {"prereg": "docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_3.md @ 701c4c2 (Amendment 3) + "
                     "docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_3_1.md @ ebdb0f1 (T6, R1-R5)",
           "runtime": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform()},
           "fixture_seed": T.FIXTURE_SEED,
           "source_sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in sorted(list((ROOT / "lineage_b").rglob("*.py"))
                                             + [ROOT / "tests" / "test_lineage_b0_v13_impl.py"])}}
    out["R"] = _run(T.r_checks)
    print(f"R1-R5: {'PASS' if out['R']['pass'] else 'FAIL'} ({out['R']['seconds']}s)", flush=True)
    for c in out["R"].get("checks", []):
        print(f"  {c['check']}: err {c['abs_err']:.3g} limit {c['limit']:.0e} {'ok' if c['pass'] else 'FAIL'}",
              flush=True)
    out["T"] = {}
    if not out["R"]["pass"]:
        out["status"] = "STOPPED_AT_R"
    else:
        for name, fn in T.TESTS:
            kw = {"progress": (lambda m, sd, n: print(f"  T6 m={m} sd={sd} n={n}", flush=True)
                               if sd == T.T6_SD[-1] else None)} if name == "T6" else {}
            out["T"][name] = _run(fn, **kw)
            print(f"{name}: {'PASS' if out['T'][name]['pass'] else 'FAIL'} ({out['T'][name]['seconds']}s)", flush=True)
        failed = [n for n, r in out["T"].items() if not r["pass"]]
        out["failed"] = failed
        out["status"] = "PASS" if not failed else "FAIL"
    d = ROOT / "receipts" / "lineage_b0"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"b0_v13_impl_{out['status']}_{ts}.json"
    path.write_text(json.dumps(_clean(out), indent=1, default=str))
    print("status:", out["status"], "receipt:", path, flush=True)
