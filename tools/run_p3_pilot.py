#!/usr/bin/env python3
"""P3 pilot runner — DEFER -> ARBITRATION (prereg v2 + v2.1, frozen).

Runs the memory-stress benchmark with enable_defer=True for each baseline
(B0, B1, B2, B2M, B3), computes the preregistered metrics and H0/H1/H2
verdicts mechanically, and writes a receipt. Ground truth is joined ONLY here,
at evaluation time.

Usage: python3 tools/run_p3_pilot.py [--out DIR] [--modes A,...]
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import bench_memory_stress as B  # noqa: E402
from morphsat.commit_gate import THREAT_SIGNALS  # noqa: E402
from morphsat.decision_event import SEVERITY, events_digest  # noqa: E402
from morphsat.receipt_chain import canonical_hash  # noqa: E402

BASELINES = ["B0", "B1", "B2", "B2M", "B3"]
PRIMARY_MODE = "A"


def isolate(tmpdir):
    base = B.SplitMemoryStore

    class Iso(base):
        def __init__(self, store_path="commit_gate_memory.json"):
            p = str(store_path)
            if p.startswith("/tmp/"):
                p = os.path.join(tmpdir, os.path.basename(p))
            super().__init__(p)

    n = {"i": 0}

    def mk(suffix):
        n["i"] += 1
        return os.path.join(tmpdir, f"bench_{suffix}_{n['i']}")

    B.SplitMemoryStore = Iso
    B._make_tmp = mk


def metrics(events, subset=None):
    d = [e for e in events if e.monitor_action == "DEFER"
         and (subset is None or subset(e))]
    res = [e for e in d if e.arbitration_result is not None]
    elig = [e for e in res if len(e.arbitration_request["slot_refs"]) >= 2]
    commits = [e for e in res if e.final_action == "COMMIT"]
    gt = lambda e: e.evaluation["ground_truth"]
    correct = [e for e in commits if e.final_direction == gt(e)]
    wrong = [e for e in commits if e.final_direction != gt(e)]

    def lean(e):
        b = e.threat_score - e.safety_score
        return "threat" if b > 0 else "safe" if b < 0 else "zero"

    against = [e for e in commits
               if (lean(e) == "threat" and e.final_direction == "benign")
               or (lean(e) == "safe" and e.final_direction in ("suspicious", "escalate"))]
    unsafe = [e for e in commits if e.final_direction == "benign" and (
        e.threat_score - e.safety_score > 0.0
        or any(c in THREAT_SIGNALS for _, c in e.evidence_signature))]
    by_reason = {}
    for e in d:
        by_reason[e.reason_for_defer] = by_reason.get(e.reason_for_defer, 0) + 1
    return {
        "defer_count": len(d),
        "defer_by_reason": by_reason,
        "history_eligible": len(elig),
        "defer_to_commit": len(commits),
        "defer_to_abstain": len(d) - len(commits),
        "history_resolved": len(commits),
        "correct_resolutions": len(correct),
        "wrong_resolutions": len(wrong),
        "wrong_history_resolutions": len(wrong),
        "net": len(correct) - len(wrong),
        "selective_risk": (len(wrong) / len(commits)) if commits else None,
        "arbitration_coverage": (len(commits) / len(elig)) if elig else None,
        "abstention_rate": ((len(d) - len(commits)) / len(d)) if d else None,
        "false_safe": sum(1 for e in commits if gt(e) == "escalate" and e.final_direction == "benign"),
        "unsafe_resolutions": len(unsafe),
        "against_live_lean": len(against),
        "severity_vs_scored_suspicious": {
            "up": sum(1 for e in commits if SEVERITY[e.final_direction] > 1),
            "down": sum(1 for e in commits if SEVERITY[e.final_direction] < 1),
            "same": sum(1 for e in commits if SEVERITY[e.final_direction] == 1)},
    }


def run(modes, out_dir):
    tmp = tempfile.mkdtemp(prefix="p3_pilot_")
    isolate(tmp)
    t0 = time.time()
    results, tables, validity = {}, {}, {}
    for mode in modes:
        results[mode], tables[mode] = {}, {}
        ref = B.run_stress_mode(mode, B.STRESS_FAMILIES)          # defer off (= P2D)
        for bl in BASELINES:
            r = B.run_stress_mode(mode, B.STRESS_FAMILIES, enable_defer=True,
                                  arbitration_baseline=bl)
            ev = r.decision_events
            term_viol = sum(1 for e in ev if e.monitor_action in ("COMMIT", "ABSTAIN")
                            and (e.final_action, e.final_direction)
                            != (e.monitor_action, e.monitor_direction))
            final_defer = sum(1 for e in ev if e.final_action == "DEFER")
            blocked = sum(1 for e in ev if e.monitor_action == "DEFER"
                          and e.override_blocked_by_terminal)
            results[mode][bl] = {
                "all": metrics(ev),
                "HARNESS_END": metrics(ev, lambda e: e.reason_for_defer == "HARNESS_END"),
                "OTHER_REASONS": metrics(ev, lambda e: e.reason_for_defer != "HARNESS_END"),
                "terminal_invariant_violations": term_viol,
                "final_defer": final_defer,
                "blocked_non_arbitration_proposals_on_defer": blocked,
                "legacy_accuracy_82": f"{r.correct}/82",
                "events_digest": events_digest(ev),
            }
            if bl == "B0":
                validity[mode] = {
                    "B0_finals_equal_P2D": [(e.scenario_id, e.final_verdict) for e in r.episodes]
                    == [(e.scenario_id, e.final_verdict) for e in ref.episodes],
                    "B0_metrics_equal_P2D": r.to_dict() == ref.to_dict(),
                }
            tables[mode][bl] = [{
                "episode": e.scenario_id, "family": e.family,
                "reason_for_defer": e.reason_for_defer,
                "balance": e.threat_score - e.safety_score,
                "slots": e.arbitration_request["slot_refs"],
                "excluded": e.arbitration_result["records_excluded"],
                "votes": e.arbitration_result["votes"],
                "n_uncertain": e.arbitration_result["n_uncertain"],
                "result": [e.final_action, e.final_direction],
                "arb_reason": e.arbitration_result["reason"],
                "result_hash": e.arbitration_result["result_hash"],
                "ground_truth_eval_only": e.evaluation["ground_truth"],
            } for e in ev if e.monitor_action == "DEFER"]

    p = results[PRIMARY_MODE]
    n = {bl: p[bl]["all"]["net"] for bl in BASELINES}
    w = {bl: p[bl]["all"]["wrong_resolutions"] for bl in BASELINES}
    valid = (all(v["B0_finals_equal_P2D"] for v in validity.values())
             and all(p[bl]["terminal_invariant_violations"] == 0 and p[bl]["final_defer"] == 0
                     for bl in BASELINES))
    h2 = (n["B3"] >= n["B1"] + 2 and n["B3"] >= n["B2"] + 1
          and w["B3"] <= min(w["B1"], w["B2"])
          and p["B3"]["all"]["false_safe"] == 0 and p["B3"]["all"]["unsafe_resolutions"] == 0
          and p["B3"]["terminal_invariant_violations"] == 0)
    verdicts = {
        "primary_mode": PRIMARY_MODE,
        "run_valid": valid,
        "net": n, "wrong": w,
        "H0_history_irrelevant": n["B3"] <= 0,
        "H1_generic_memory": n["B1"] > 0 and n["B3"] - n["B1"] < 2,
        "H2_causal_history": h2,
        "ladder": {"B1>B0": n["B1"] > n["B0"], "B2>B1": n["B2"] > n["B1"],
                   "B3>B2": n["B3"] > n["B2"]},
        "B2M_diagnostic": {"net_B2M": n["B2M"], "B3>B2M": n["B3"] > n["B2M"],
                           "B3==B2M": n["B3"] == n["B2M"]},
        "critical_falsifier_triggered": not h2,
    }
    receipt = {
        "work_order": "P3_PILOT_DEFER_ARBITRATION",
        "preregistration": ["docs/P3_DEFER_ARBITRATION_PREREG_V2.md@e4bc7d9",
                            "docs/P3_DEFER_ARBITRATION_PREREG_V2_1.md@d89837a",
                            "docs/P3_HELDOUT_CONSTRUCTION_PROCEDURE.md@ca394ff"],
        "scope": "public GitHub lineage of 14689b7",
        "modes": modes, "validity": validity, "verdicts": verdicts,
        "results": results, "per_request": tables,
        "wall_time_s": round(time.time() - t0, 2),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = out_dir / f"p3_pilot_{ts}.json"
    path.write_text(json.dumps(receipt, indent=2, default=str))
    return path, receipt


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="receipts/p3_pilot")
    ap.add_argument("--modes", default="A,B,C,D,H,J,K,L,M")
    a = ap.parse_args()
    path, rec = run(a.modes.split(","), Path(a.out))
    print(json.dumps(rec["verdicts"], indent=1))
    print("receipt:", path)
