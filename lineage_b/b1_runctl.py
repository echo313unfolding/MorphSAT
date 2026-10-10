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
               "pre_validation_amendment_v1_5_2": "1e8bd91",
               "validation_failure_amendment_v1_5_3": "39313b6",
               "exploration_policy_amendment_v1_6": "58653eb",
               "run_control_amendment_v1_6_1": "4ca95b6",
               "run_control_hardening_v1_6_2": "b06cb48",
               "corrective_amendment_v1_6_3": "c4280f0",
               "prereg": "docs/LINEAGE_B1_GROUNDED_FEEDBACK_PREREG_V1.md",
               "amendments": ["docs/LINEAGE_B1_PREREG_V1_5_1_AMENDMENT.md",
                              "docs/LINEAGE_B1_PREREG_V1_5_2_AMENDMENT.md",
                              "docs/LINEAGE_B1_PREREG_V1_5_3_AMENDMENT.md",
                              "docs/LINEAGE_B1_PREREG_V1_6_AMENDMENT.md",
                              "docs/LINEAGE_B1_PREREG_V1_6_1_AMENDMENT.md",
                              "docs/LINEAGE_B1_PREREG_V1_6_2_AMENDMENT.md",
                              "docs/LINEAGE_B1_PREREG_V1_6_3_AMENDMENT.md"]}
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


def require_one_shot(prefix: str, root: int):
    """v1.6.1/v1.6.2: one-shot identity is (receipt family, seed root). Historical
    receipts from a permanently disjoint root remain visible evidence but do
    not consume a newly preregistered root. Fail closed on unreadable receipts
    or missing/invalid root provenance (v1.6.2)."""
    found = []
    for p in existing_receipts(prefix):
        try:
            payload = json.loads(p.read_text())
        except Exception as e:
            raise SystemExit(
                f"refusing to run: cannot verify historical {prefix} receipt {p.name}: {e}"
            )
        receipt_root = payload.get("root")
        if type(receipt_root) is not int:
            raise SystemExit(
                f"refusing to run: historical {prefix} receipt {p.name} "
                f"has missing/invalid root provenance"
            )
        if receipt_root == root:
            found.append(p)
    if found:
        raise SystemExit(f"refusing to run: {prefix} receipt(s) already exist "
                         f"for root {root} (one-shot): "
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


def require_empty_outdir(outdir: Path):
    """v1.5.2 §3: the record directory must not exist or be completely empty."""
    if outdir.exists() and (not outdir.is_dir() or any(outdir.iterdir())):
        raise SystemExit(f"refusing to run: --outdir {outdir} exists and is not empty")


def verify_record_set(outdir: Path, prefixes, conditions, n: int, load) -> dict:
    """v1.5.2 §3: exactly the expected <prefix>_<cond>_<dep:05d>.pkl files, no
    extras, embedded (condition, deployment) matching each file name."""
    expected = {f"{p}_{c}_{d:05d}.pkl" for p in prefixes for c in conditions for d in range(n)}
    present = {f.name for f in outdir.iterdir()}
    problems = []
    if present - expected:
        problems.append({"unexpected": sorted(present - expected)[:20]})
    if expected - present:
        problems.append({"missing": sorted(expected - present)[:20]})
    seen = set()
    for name in sorted(present & expected):
        p, c, d = name[:-4].split("_")
        rec = load(outdir / name)
        dep = rec["deployment"].rsplit(":", 2)
        logical = (p, rec["condition"], int(dep[2]))
        if rec["condition"] != c or dep[1] != c or int(dep[2]) != int(d):
            problems.append({"mismatch": name})
        if logical in seen:
            problems.append({"duplicate": logical})
        seen.add(logical)
    return {"pass": not problems, "problems": problems, "files": len(present)}
