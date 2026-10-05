#!/usr/bin/env python3
"""B0 v1.2 implementation-only test (prereg v1.2 Amendment 3 step 2). Uses no
B0, pilot or B1 seeds. Writes a receipt; a failure stops B0 v1.2."""
import json
import platform
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_lineage_b0_v12_impl import diffusion, equivalence  # noqa: E402

if __name__ == "__main__":
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out = {"prereg": "docs/LINEAGE_B0_SIMULATOR_VALIDITY_PREREG_V1_2.md @ 72e8925 (Amendment 3 step 2)",
           "runtime": {"python": sys.version, "numpy": np.__version__, "platform": platform.platform()},
           "equivalence": [equivalence(100), equivalence(400)]}
    print("equivalence:", out["equivalence"], flush=True)
    out["diffusion"] = diffusion()
    for k, v in out["diffusion"]["scenarios"].items():
        print(f"diffusion {k}: ratio {v['ratio']:.2f} pass {v['pass']}", flush=True)
    out["pass"] = all(e["pass"] for e in out["equivalence"]) and out["diffusion"]["pass"]
    d = ROOT / "receipts" / "lineage_b0"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"b0_v12_impl_{'PASS' if out['pass'] else 'FAIL'}_{ts}.json"
    path.write_text(json.dumps(out, indent=1, default=float))
    print("pass:", out["pass"], "receipt:", path)
