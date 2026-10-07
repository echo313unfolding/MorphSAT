"""Run control shared by the B1 runners: clean tree, source fingerprint,
receipt writing. EVALUATOR side."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RECEIPTS = ROOT / "receipts" / "lineage_b1"
PREREG_REFS = {"sizing_design_freeze": "2473c2a", "pre_execution_amendment_v1_5_1": "f4f5990",
               "prereg": "docs/LINEAGE_B1_GROUNDED_FEEDBACK_PREREG_V1.md",
               "amendment": "docs/LINEAGE_B1_PREREG_V1_5_1_AMENDMENT.md"}
FROZEN_FILE = "lineage_b/b1_frozen.py"
FROZEN_FIELDS = ("N", "CONFIRMATORY_SEED_LIST_SHA256", "SIZING_RECEIPT")


def git(*args) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def require_clean_tree():
    dirty = git("status", "--porcelain", "--", "lineage_b", "tools", "morphsat")
    if dirty:
        raise SystemExit(f"refusing to run: uncommitted changes\n{dirty}")


def protected_files():
    """v1.5.1 §8: every protected executable source."""
    return (sorted((ROOT / "lineage_b").rglob("*.py")) + sorted((ROOT / "tools").glob("run_lineage_b1_*.py"))
            + [ROOT / "morphsat" / "terminal_authority.py"])


def source_fingerprint() -> dict:
    files = protected_files()
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


def existing_receipts(prefix: str):
    return sorted(RECEIPTS.glob(f"{prefix}_*.json")) if RECEIPTS.exists() else []


def require_one_shot(prefix: str):
    """v1.5.1 §7: any existing receipt of this family blocks a fresh invocation."""
    found = existing_receipts(prefix)
    if found:
        raise SystemExit(f"refusing to run: {prefix} receipt(s) already exist (one-shot): "
                         + ", ".join(p.name for p in found))


def frozen_fields(text: str) -> dict:
    """Parse b1_frozen.py: only a docstring and exactly the three frozen assignments."""
    tree = ast.parse(text)
    body = list(tree.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        body = body[1:]
    out = {}
    for node in body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)):
            raise ValueError("b1_frozen.py may contain only the three constant assignments")
        out[node.targets[0].id] = node.value.value
    if tuple(sorted(out)) != tuple(sorted(FROZEN_FIELDS)):
        raise ValueError(f"b1_frozen.py fields {sorted(out)} != {sorted(FROZEN_FIELDS)}")
    return out


def verify_post_sizing_freeze(sizing_files: dict, current_files: dict, frozen_text: str,
                              sizing_N: int, expected_seed_hash: str, sizing_receipt_path: str) -> dict:
    """v1.5.1 §8: every protected file identical to the sizing receipt except
    b1_frozen.py, whose three fields must be exactly the authorized values."""
    problems = []
    if set(sizing_files) != set(current_files):
        problems.append({"file_set_differs": sorted(set(sizing_files) ^ set(current_files))})
    for f in sorted(set(sizing_files) & set(current_files)):
        if f != FROZEN_FILE and sizing_files[f] != current_files[f]:
            problems.append({"changed": f})
    try:
        fz = frozen_fields(frozen_text)
        if fz["N"] != sizing_N:
            problems.append({"N": fz["N"], "sizing_N": sizing_N})
        if fz["CONFIRMATORY_SEED_LIST_SHA256"] != expected_seed_hash:
            problems.append({"seed_list_sha256": "mismatch"})
        if fz["SIZING_RECEIPT"] != sizing_receipt_path:
            problems.append({"SIZING_RECEIPT": fz["SIZING_RECEIPT"]})
    except ValueError as e:
        problems.append({"b1_frozen": str(e)})
    return {"pass": not problems, "problems": problems}
