#!/usr/bin/env python3
"""B1 §7b pre-sizing implementation validation on the dedicated root
2026100517000 (prereg v1.5 @ 2473c2a). V0 + adapted gates 7, 11, 12 for
G1/G2/G3/G2-S. Stops at the first failure and writes a receipt either way.
Never touches the sizing or confirmatory roots."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lineage_b import b1_runctl as rc  # noqa: E402
from lineage_b.b1_seeds import ROOTS, TOKENS  # noqa: E402
from lineage_b.b1_validation import CHECKS  # noqa: E402

if __name__ == "__main__":
    rc.require_clean_tree()
    out = {"prereg": "docs/LINEAGE_B1_GROUNDED_FEEDBACK_PREREG_V1.md @ 2473c2a (§7b)", "refs": rc.PREREG_REFS,
           "root": ROOTS["validation"], "source": rc.source_fingerprint(), "checks": {}}
    status = "PASSED"
    for name, fn in CHECKS:
        t0 = time.time()
        try:
            r = fn(TOKENS["validation"])
        except Exception as e:                               # a crash is a failure, preserved as such
            r = {"pass": False, "exception": f"{type(e).__name__}: {e}"}
        r["seconds"] = round(time.time() - t0, 1)
        out["checks"][name] = r
        print(f"{name}: {'PASS' if r['pass'] else 'FAIL'} ({r['seconds']}s)", flush=True)
        if not r["pass"]:
            status = "FAILED"
            out["not_run"] = [n for n, _ in CHECKS][[n for n, _ in CHECKS].index(name) + 1:]
            break
    out["status"] = status
    path = rc.write_receipt(f"b1_validation_{status}", out)
    print("status:", status, "receipt:", path)
