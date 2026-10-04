#!/usr/bin/env python3
"""P3 held-out evaluation (closure experiment).

Runs the frozen dataset (receipts/p3_heldout/heldout_dataset.json, hash
checked) through the frozen P3 arbitration for B0, B1, B2, B2M, B3 in every
mode, on each mode's admitted runs. Computes the frozen closure statistic
(docs/P3_HELDOUT_GENERATOR_AUDIT.md §3) and v2 §9 metrics per stratum x
pattern on PROBE episodes. Ground truth joined at evaluation only.
"""

import collections
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import bench_memory_stress as B  # noqa: E402
from gen_p3_heldout import scenarios  # noqa: E402
from run_p3_pilot import isolate  # noqa: E402

DATASET = Path("receipts/p3_heldout/heldout_dataset.json")
FROZEN_SHA = "e05703486384c76ff1a60b5a80498f49322def10a683f3a194471bf0700a52bc"
BASELINES = ["B0", "B1", "B2", "B2M", "B3"]
SCORE = {("COMMIT", "benign"): -1, ("ABSTAIN", None): 0,
         ("COMMIT", "suspicious"): 1, ("COMMIT", "escalate"): 1}


def cell_metrics(rows):
    commits = [r for r in rows if r["final"][0] == "COMMIT"]
    correct = [r for r in commits if r["final"][1] == r["gt"]]
    wrong = [r for r in commits if r["final"][1] != r["gt"]]
    return {"n": len(rows), "deferred": sum(r["deferred"] for r in rows),
            "commits": len(commits), "correct": len(correct), "wrong": len(wrong),
            "net": len(correct) - len(wrong),
            "selective_risk": len(wrong) / len(commits) if commits else None,
            "coverage": len(commits) / len(rows) if rows else None,
            "false_safe": sum(1 for r in commits if r["gt"] == "escalate" and r["final"][1] == "benign"),
            "outcomes": dict(collections.Counter(f"{a}:{d}" for a, d in (r["final"] for r in rows)))}


def main():
    blob = DATASET.read_text()
    sha = hashlib.sha256(blob.encode()).hexdigest()
    assert sha == FROZEN_SHA, f"dataset hash mismatch {sha}"
    data = json.loads(blob)
    isolate(tempfile.mkdtemp(prefix="p3_ho_eval_"))
    t0 = time.time()
    out = {"dataset_sha256": sha, "results": {}, "closure": {}, "u7": {}, "observables": {}}
    for mode in data["modes"]:
        out["results"][mode], out["closure"][mode], out["u7"][mode] = {}, {}, {}
        runs = [r for r in data["runs"] if r["admission"][mode]["admitted"]]
        for bl in BASELINES:
            rows = []
            for run in runs:
                res = B.run_stress_mode(mode, {run["run_id"]: scenarios(run)},
                                        enable_defer=True, arbitration_baseline=bl)
                p = res.decision_events[-1]
                rows.append({
                    "run": run["run_id"], "stratum": run["stratum"], "pattern": run["pattern"],
                    "seq": run["seq_index"], "gt": run["ground_truth_eval_only"],
                    "deferred": p.monitor_action == "DEFER",
                    "final": (p.final_action, p.final_direction),
                    "votes": dict(p.arbitration_result["votes"]) if p.arbitration_result else None,
                    "n_uncertain": p.arbitration_result["n_uncertain"] if p.arbitration_result else None,
                    "excluded": [e[1] for e in p.arbitration_result["records_excluded"]] if p.arbitration_result else None,
                    "arb_reason": p.arbitration_result["reason"] if p.arbitration_result else None,
                })
            out["u7"][mode][bl] = sum(not r["deferred"] for r in rows)
            out["results"][mode][bl] = {
                f"{s}{pt}": cell_metrics([r for r in rows if r["stratum"] == s and r["pattern"] == pt])
                for s in "AB" for pt in ["P1", "P2", "P3", "P4", "P5"]}
            # frozen closure statistic: matched P3/P4 pairs per stratum
            cl = {}
            for s in "AB":
                p3 = {r["seq"]: r for r in rows if r["stratum"] == s and r["pattern"] == "P3"}
                p4 = {r["seq"]: r for r in rows if r["stratum"] == s and r["pattern"] == "P4"}
                pairs = sorted(set(p3) & set(p4))
                c = sum(SCORE[tuple(p4[i]["final"])] > SCORE[tuple(p3[i]["final"])] for i in pairs)
                w = sum(SCORE[tuple(p4[i]["final"])] < SCORE[tuple(p3[i]["final"])] for i in pairs)
                cl[s] = {"pairs": len(pairs), "correct_direction": c, "wrong_direction": w,
                         "ties": len(pairs) - c - w, "discriminates": c >= 1 and w == 0}
                if mode == "A":
                    out["observables"].setdefault(bl, {})[s] = {
                        "P3_example": {k: p3[pairs[0]][k] for k in ("votes", "n_uncertain", "excluded", "final", "arb_reason")},
                        "P4_example": {k: p4[pairs[0]][k] for k in ("votes", "n_uncertain", "excluded", "final", "arb_reason")},
                        "P3_vote_patterns": dict(collections.Counter(json.dumps([p3[i]["votes"], p3[i]["excluded"], list(p3[i]["final"])]) for i in pairs)),
                        "P4_vote_patterns": dict(collections.Counter(json.dumps([p4[i]["votes"], p4[i]["excluded"], list(p4[i]["final"])]) for i in pairs)),
                    }
            out["closure"][mode][bl] = cl
    out["wall_time_s"] = round(time.time() - t0, 1)
    b3 = out["closure"]["A"]["B3"]
    out["verdict_primary_mode_A"] = {
        "B3_discriminates": {s: b3[s]["discriminates"] for s in "AB"},
        "any_baseline_discriminates": {bl: {s: out["closure"]["A"][bl][s]["discriminates"] for s in "AB"} for bl in BASELINES},
        "close_causal_history_line": not any(b3[s]["discriminates"] for s in "AB"),
        "modes_agree": all(out["closure"][m] == out["closure"]["A"] for m in data["modes"]),
    }
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = Path(f"receipts/p3_heldout/p3_heldout_results_{ts}.json")
    path.write_text(json.dumps(out, indent=1, default=str))
    print(json.dumps(out["verdict_primary_mode_A"], indent=1)); print("receipt:", path)


if __name__ == "__main__":
    main()
