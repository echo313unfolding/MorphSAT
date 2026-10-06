"""Run control shared by the B1 runners: clean tree, source fingerprint,
receipt writing. EVALUATOR side."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECEIPTS = ROOT / "receipts" / "lineage_b1"


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def require_clean_tree():
    dirty = git("status", "--porcelain", "--", "lineage_b", "tools", "morphsat")
    if dirty:
        raise SystemExit(f"refusing to run: uncommitted changes\n{dirty}")


def source_fingerprint() -> dict:
    files = sorted((ROOT / "lineage_b").rglob("*.py")) + [ROOT / "morphsat" / "terminal_authority.py"]
    per = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    return {"head": git("rev-parse", "HEAD"), "files": per,
            "combined": hashlib.sha256(json.dumps(per, sort_keys=True).encode()).hexdigest()}


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


def write_receipt(name: str, payload: dict) -> Path:
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = RECEIPTS / f"{name}_{ts}.json"
    path.write_text(json.dumps(clean(payload), indent=1, default=str))
    return path
