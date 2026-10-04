#!/usr/bin/env python3
"""P3 held-out generator — exact realization of
docs/P3_HELDOUT_CONSTRUCTION_PROCEDURE.md @ ca394ff (no free parameters).

Generates all 600 runs (2 strata x 5 patterns x 60 probe sequences), applies
the label-free, arbitration-free admission filter (frozen P3 monitor,
enable_defer=True, baseline B0) in every bench mode, and writes the dataset
JSON once. The dataset hash must be committed before any B1/B2/B2M/B3 run.

Audit: docs/P3_HELDOUT_GENERATOR_AUDIT.md.
"""

import argparse
import hashlib
import itertools
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import bench_memory_stress as B  # noqa: E402

# --- §3 Entities (frozen) ---------------------------------------------------
ENTITIES = ["zephyrhost", "quillnode", "marrowbox", "tundraweb", "cobaltgate",
            "lumenrack", "vesperdb", "orchidmq", "basaltapi", "fernlogic"]
ENTITY_PAIRS = list(itertools.combinations(sorted(ENTITIES), 2))   # 45, lexicographic
ALERT = "Alert {e1} {e2} activity flagged for review"
CORRECTION_ALERT = "CORRECTION {e1} {e2} prior alert reassessed by analyst"

# --- §2 Building blocks (frozen, from bench_memory_stress) ------------------
T_TOOLS = ["check_ports", "scan_file", "check_process"]
B_TOOLS = ["check_hash", "check_process", "check_ports"]
C_TOOLS = ["check_hash", "check_process", "scan_file"]
FILLER = ("check_process",
          "Process check: Process running but context is ambiguous. No known-bad signatures.")

# --- §4 Patterns (frozen) ---------------------------------------------------
PATTERNS = {
    "P1": (["T", "T", "T", "T"], "escalate"),
    "P2": (["B", "B", "B", "B"], "benign"),
    "P3": (["T", "T", "C", "B"], "benign"),
    "P4": (["T", "T", "C", "T"], "escalate"),
    "P5": (["T", "B", "T", "B"], "suspicious"),
}
# History-episode categories: evaluation-only, never inputs (audit U3).
HISTORY_CATEGORY = {"T": "escalate", "B": "benign", "C": "benign"}

STRATA = {"A": {"filler": 0, "admit": {"HARNESS_END"}},
          "B": {"filler": 7, "admit": {"STAGNATION", "TOOL_BUDGET_EXHAUSTED", "MAX_TOOLS"}}}
MODES = ["A", "B", "C", "D", "H", "J", "K", "L", "M"]


def block_tools(kind):
    if kind == "T":
        return [(t, B.CANONICAL_RESPONSES["escalate"][t]) for t in T_TOOLS]
    if kind == "B":
        return [(t, B.CANONICAL_RESPONSES["benign"][t]) for t in B_TOOLS]
    if kind == "C":
        return [(t, B.CORRECTION_RESPONSES[t]) for t in C_TOOLS]
    raise ValueError(kind)


def probe_sequences():
    """§5: ordered 3-sequences of distinct M tools, lexicographic tool order."""
    return list(itertools.permutations(sorted(B.TOOL_NAMES), 3))   # 60


def build_runs():
    seqs = probe_sequences()
    assert len(seqs) == 60
    pilot_tags = set()
    for fam in B.STRESS_FAMILIES.values():
        for s in fam:
            pilot_tags |= {w.lower() for w in s["alert"].split() if len(w) > 3 and w.isalpha()}
    assert not set(ENTITIES) & pilot_tags, "entity vocabulary collides with pilot tags"
    runs, k = [], 0
    for stratum in ("A", "B"):
        for pat in ("P1", "P2", "P3", "P4", "P5"):
            hist, gt = PATTERNS[pat]
            for si, seq in enumerate(seqs):
                e1, e2 = ENTITY_PAIRS[k % len(ENTITY_PAIRS)]
                k += 1
                run_id = f"ho_{stratum}_{pat}_{si:02d}"
                eps = []
                for j, kind in enumerate(hist):
                    alert = (CORRECTION_ALERT if kind == "C" else ALERT).format(e1=e1, e2=e2)
                    eps.append({"id": f"{run_id}_h{j}", "alert": alert,
                                "category": HISTORY_CATEGORY[kind],
                                "custom_tools": block_tools(kind), "kind": kind})
                probe = [(t, B.CANONICAL_RESPONSES["suspicious"][t]) for t in seq]
                probe += [FILLER] * STRATA[stratum]["filler"]
                eps.append({"id": f"{run_id}_probe", "alert": ALERT.format(e1=e1, e2=e2),
                            "category": gt, "custom_tools": probe, "kind": "probe"})
                runs.append({"run_id": run_id, "stratum": stratum, "pattern": pat,
                             "seq_index": si, "probe_sequence": list(seq),
                             "entity_pair": [e1, e2], "ground_truth_eval_only": gt,
                             "episodes": eps})
    return runs


def scenarios(run):
    """Bench scenario dicts (only fields the bench reads; no oracle fields)."""
    return [{"id": e["id"], "alert": e["alert"], "category": e["category"],
             "custom_tools": [tuple(x) for x in e["custom_tools"]]} for e in run["episodes"]]


def admit(runs, modes):
    from run_p3_pilot import isolate
    import tempfile
    isolate(tempfile.mkdtemp(prefix="p3_ho_admit_"))
    for run in runs:
        run["admission"] = {}
        for mode in modes:
            r = B.run_stress_mode(mode, {run["run_id"]: scenarios(run)},
                                  enable_defer=True, arbitration_baseline="B0")
            probe = r.decision_events[-1]
            ok = (probe.monitor_action == "DEFER"
                  and probe.reason_for_defer in STRATA[run["stratum"]]["admit"])
            run["admission"][mode] = {
                "admitted": ok, "probe_monitor_action": probe.monitor_action,
                "reason_for_defer": probe.reason_for_defer,
                "history_monitor_actions": [e.monitor_action for e in r.decision_events[:-1]],
            }
    return runs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="receipts/p3_heldout/heldout_dataset.json")
    a = ap.parse_args()
    runs = admit(build_runs(), MODES)
    blob = json.dumps({"procedure": "docs/P3_HELDOUT_CONSTRUCTION_PROCEDURE.md@ca394ff",
                       "generator": "tools/gen_p3_heldout.py", "modes": MODES,
                       "runs": runs}, indent=1, sort_keys=True)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(blob)
    print(out, hashlib.sha256(blob.encode()).hexdigest())
