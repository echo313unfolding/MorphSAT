#!/usr/bin/env python3
"""MorphSAT Phase 1.6 — Decay Sensitivity Map.

Sweeps evidence_decay from 0.50 to 1.00 and measures:
  - delayed_correction_recovery
  - false_escalation_rate
  - benign_recovery
  - overall_accuracy

Answers: Is 0.85 a true optimum? Is there a plateau? Does performance
collapse outside a narrow band? Is the response smooth or cliff-edge?

Steven Jones (Plan 4): "prove your intermediate values span the space
in a decision theoretic sense — performance should degrade smoothly,
not cliff-edge, as parameters shift."

Usage:
    python3 tools/bench_decay_sensitivity.py
    python3 tools/bench_decay_sensitivity.py --steps 0.02  # finer grain
    python3 tools/bench_decay_sensitivity.py --verbose

WO-RECEIPT-COST-01 compliant.
"""

import argparse
import json
import platform
import random
import resource
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.bench_adversarial_robustness import (
    ADVERSARIAL_SCENARIOS,
    ALL_CONDITIONS,
    run_condition,
    summarize_results,
    check_gates,
)
from morphsat.commit_gate import classify_tool_result

RECEIPTS_DIR = Path.home() / "receipts" / "morphsat_adversarial"


def sweep_decay(decay_values: List[float],
                conditions: Optional[List[str]] = None,
                seed: int = 42,
                verbose: bool = False,
                enable_dual_boundary: bool = False,
                commit_threat_boundary: float = 0.55,
                commit_safe_boundary: float = 0.40) -> Dict:
    """Run the full sweep. Returns structured results."""

    if conditions is None:
        conditions = ALL_CONDITIONS

    scenarios = ADVERSARIAL_SCENARIOS

    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    t_start = time.time()
    cpu_start = time.process_time()

    sweep_results = {}

    for decay in decay_values:
        rng = random.Random(seed)
        all_summaries = {}

        for condition in conditions:
            results = run_condition(
                scenarios, condition,
                classifier_fn=classify_tool_result,
                classifier_name="keyword",
                rng=random.Random(rng.randint(0, 100000)),
                verbose=False,
                evidence_decay=decay,
                enable_correction=True,
                enable_dual_boundary=enable_dual_boundary,
                commit_threat_boundary=commit_threat_boundary,
                commit_safe_boundary=commit_safe_boundary,
            )
            all_summaries[condition] = summarize_results(results)

        gates = check_gates(all_summaries)

        # Compute per-condition-group metrics
        noise_conds = [c for c in conditions if c.startswith("A_")]
        contra_conds = [c for c in conditions if c.startswith("B_")]
        adv_conds = [c for c in conditions if c.startswith("C_")]
        delay_conds = [c for c in conditions if c.startswith("D_")]

        def avg_metric(conds, key, default=0.0):
            if not conds:
                return default
            vals = [all_summaries[c].get(key, default) for c in conds]
            return sum(vals) / len(vals)

        # Overall across all non-control conditions
        non_control = [c for c in conditions if c != "control"]

        row = {
            "decay": decay,
            # Gate metrics
            "delayed_correction_recovery": gates.get("delayed_correction_recovery", {}).get("actual", 0.0),
            "delayed_correction_pass": gates.get("delayed_correction_recovery", {}).get("pass", False),
            "false_escalation_rate": gates.get("false_escalation_rate", {}).get("actual", 0.0),
            "false_escalation_pass": gates.get("false_escalation_rate", {}).get("pass", True),
            "benign_recovery_noise": gates.get("benign_recovery_under_noise", {}).get("actual", 0.0),
            "benign_recovery_noise_pass": gates.get("benign_recovery_under_noise", {}).get("pass", True),
            "all_gates_pass": gates.get("overall_pass", False),
            # Per-group accuracy
            "overall_accuracy": avg_metric(non_control, "accuracy_pct"),
            "control_accuracy": all_summaries.get("control", {}).get("accuracy_pct", 0.0),
            "noise_accuracy": avg_metric(noise_conds, "accuracy_pct"),
            "contradiction_accuracy": avg_metric(contra_conds, "accuracy_pct"),
            "adversarial_accuracy": avg_metric(adv_conds, "accuracy_pct"),
            "delayed_accuracy": avg_metric(delay_conds, "accuracy_pct"),
            # Per-group benign recovery
            "overall_benign_recovery": avg_metric(non_control, "benign_recovery_pct"),
            "noise_benign_recovery": avg_metric(noise_conds, "benign_recovery_pct"),
            "delayed_benign_recovery": avg_metric(delay_conds, "benign_recovery_pct"),
            # Per-group false escalation
            "overall_false_escalation": avg_metric(non_control, "false_escalation_pct"),
            # Per-group false safe
            "overall_false_safe": avg_metric(non_control, "false_safe_pct"),
            # ABSTAIN metrics
            "overall_abstain_pct": avg_metric(non_control, "abstain_pct"),
            "overall_abstain_uncertainty_pct": avg_metric(non_control, "abstain_uncertainty_pct"),
            "total_abstain": sum(all_summaries[c].get("n_abstain", 0) for c in non_control),
            "total_abstain_uncertainty": sum(all_summaries[c].get("n_abstain_uncertainty", 0) for c in non_control),
            "abstain_on_benign": sum(all_summaries[c].get("abstain_on_benign", 0) for c in non_control),
            "abstain_on_suspicious": sum(all_summaries[c].get("abstain_on_suspicious", 0) for c in non_control),
            "abstain_on_escalate": sum(all_summaries[c].get("abstain_on_escalate", 0) for c in non_control),
            # Raw scores
            "avg_threat": avg_metric(non_control, "avg_threat_score"),
            "avg_safety": avg_metric(non_control, "avg_safety_score"),
            "avg_clarity": avg_metric(non_control, "avg_evidence_clarity"),
            # Per-condition detail
            "per_condition": {c: all_summaries[c] for c in conditions},
        }

        sweep_results[decay] = row

        mark = "ALL PASS" if row["all_gates_pass"] else "FAIL"
        print(f"  decay={decay:.2f}  [{mark:>8s}]  "
              f"delay_corr={row['delayed_correction_recovery']:>5.1f}%  "
              f"false_esc={row['false_escalation_rate']:>5.1f}%  "
              f"benign_rec={row['benign_recovery_noise']:>5.1f}%  "
              f"acc={row['overall_accuracy']:>5.1f}%")

    # --- Response surface table ---
    print("\n" + "=" * 90)
    print("  DECAY SENSITIVITY MAP — RESPONSE SURFACE")
    print("=" * 90)

    print(f"\n  {'decay':>6s}  {'gates':>8s}  "
          f"{'del_corr%':>9s}  {'false_e%':>8s}  {'bn_rec%':>7s}  "
          f"{'acc_all%':>8s}  {'acc_noise':>9s}  {'acc_delay':>9s}  "
          f"{'acc_adv':>7s}  {'acc_contr':>9s}")
    print(f"  {'-'*6}  {'-'*8}  "
          f"{'-'*9}  {'-'*8}  {'-'*7}  "
          f"{'-'*8}  {'-'*9}  {'-'*9}  "
          f"{'-'*7}  {'-'*9}")

    for decay in decay_values:
        r = sweep_results[decay]
        mark = "PASS" if r["all_gates_pass"] else "FAIL"
        print(f"  {decay:>6.2f}  {mark:>8s}  "
              f"{r['delayed_correction_recovery']:>9.1f}  "
              f"{r['false_escalation_rate']:>8.1f}  "
              f"{r['benign_recovery_noise']:>7.1f}  "
              f"{r['overall_accuracy']:>8.1f}  "
              f"{r['noise_accuracy']:>9.1f}  "
              f"{r['delayed_accuracy']:>9.1f}  "
              f"{r['adversarial_accuracy']:>7.1f}  "
              f"{r['contradiction_accuracy']:>9.1f}")

    # --- ABSTAIN metrics ---
    any_abstain = any(sweep_results[d]["total_abstain"] > 0 for d in decay_values)
    if any_abstain or enable_dual_boundary:
        print("\n" + "=" * 90)
        print("  ABSTAIN METRICS — UNCERTAINTY PRESERVATION")
        print("=" * 90)

        print(f"\n  {'decay':>6s}  {'abstain':>7s}  {'uncert':>6s}  "
              f"{'on_ben':>6s}  {'on_sus':>6s}  {'on_esc':>6s}  "
              f"{'false_safe%':>11s}  {'false_esc%':>10s}")
        print(f"  {'-'*6}  {'-'*7}  {'-'*6}  "
              f"{'-'*6}  {'-'*6}  {'-'*6}  "
              f"{'-'*11}  {'-'*10}")

        for decay in decay_values:
            r = sweep_results[decay]
            print(f"  {decay:>6.2f}  "
                  f"{r['total_abstain']:>7d}  "
                  f"{r['total_abstain_uncertainty']:>6d}  "
                  f"{r['abstain_on_benign']:>6d}  "
                  f"{r['abstain_on_suspicious']:>6d}  "
                  f"{r['abstain_on_escalate']:>6d}  "
                  f"{r['overall_false_safe']:>11.1f}  "
                  f"{r['overall_false_escalation']:>10.1f}")

        # Summary
        total_all_abstain = sum(sweep_results[d]["total_abstain"] for d in decay_values)
        total_uncertainty = sum(sweep_results[d]["total_abstain_uncertainty"] for d in decay_values)
        total_on_benign = sum(sweep_results[d]["abstain_on_benign"] for d in decay_values)
        total_on_escalate = sum(sweep_results[d]["abstain_on_escalate"] for d in decay_values)

        print(f"\n  Total ABSTAINs across sweep: {total_all_abstain}")
        print(f"  Of which uncertainty-preserving: {total_uncertainty}")
        if total_all_abstain > 0:
            print(f"  ABSTAIN on benign (correct caution): {total_on_benign}")
            print(f"  ABSTAIN on escalate (missed threat): {total_on_escalate}")
            if total_on_escalate > 0:
                print(f"  WARNING: {total_on_escalate} ABSTAINs on escalate scenarios — "
                      f"uncertainty preserved but threat not caught")
            else:
                print(f"  No ABSTAINs on escalate scenarios — threats always caught")

    # --- Characterization ---
    print(f"\n" + "=" * 90)
    print("  RESPONSE CHARACTERIZATION")
    print("=" * 90)

    passing_decays = [d for d in decay_values if sweep_results[d]["all_gates_pass"]]
    if passing_decays:
        print(f"\n  Passing range: [{min(passing_decays):.2f}, {max(passing_decays):.2f}]")
        print(f"  Passing count: {len(passing_decays)}/{len(decay_values)}")

        # Find optimal (highest overall accuracy among passing)
        best = max(passing_decays, key=lambda d: sweep_results[d]["overall_accuracy"])
        print(f"  Best accuracy among passing: decay={best:.2f} "
              f"(acc={sweep_results[best]['overall_accuracy']:.1f}%)")

        # Check for plateau (consecutive passing values with similar accuracy)
        if len(passing_decays) >= 3:
            accs = [sweep_results[d]["overall_accuracy"] for d in passing_decays]
            spread = max(accs) - min(accs)
            print(f"  Accuracy spread in passing range: {spread:.1f}pp")
            if spread < 5.0:
                print(f"  Shape: PLATEAU (spread < 5pp)")
            elif spread < 15.0:
                print(f"  Shape: GRADUAL SLOPE")
            else:
                print(f"  Shape: STEEP GRADIENT")
    else:
        print(f"\n  No decay value passes all gates.")

    # Detect cliff edges (>15pp jump between adjacent values)
    sorted_decays = sorted(decay_values)
    cliffs = []
    for i in range(1, len(sorted_decays)):
        d_prev = sorted_decays[i - 1]
        d_curr = sorted_decays[i]
        r_prev = sweep_results[d_prev]
        r_curr = sweep_results[d_curr]

        for metric in ["delayed_correction_recovery", "overall_accuracy",
                        "false_escalation_rate", "benign_recovery_noise"]:
            delta = abs(r_curr[metric] - r_prev[metric])
            if delta > 15.0:
                cliffs.append({
                    "metric": metric,
                    "from_decay": d_prev,
                    "to_decay": d_curr,
                    "from_val": r_prev[metric],
                    "to_val": r_curr[metric],
                    "delta": delta,
                })

    if cliffs:
        print(f"\n  CLIFF EDGES DETECTED (>15pp jump between adjacent values):")
        for c in cliffs:
            direction = "UP" if c["to_val"] > c["from_val"] else "DOWN"
            print(f"    {c['metric']:<35s}  "
                  f"decay {c['from_decay']:.2f}→{c['to_decay']:.2f}  "
                  f"{c['from_val']:.1f}→{c['to_val']:.1f}  "
                  f"({direction} {c['delta']:.1f}pp)")
    else:
        print(f"\n  No cliff edges detected (all transitions < 15pp).")

    # Check monotonicity of delayed correction recovery
    dcr_values = [sweep_results[d]["delayed_correction_recovery"] for d in sorted_decays]
    is_monotone_decreasing = all(dcr_values[i] >= dcr_values[i+1]
                                  for i in range(len(dcr_values)-1))
    print(f"\n  Delayed correction vs decay: "
          f"{'MONOTONE (more decay → more recovery)' if is_monotone_decreasing else 'NON-MONOTONE'}")

    # Check if false escalation increases monotonically with stronger decay
    fe_values = [sweep_results[d]["false_escalation_rate"] for d in sorted_decays]
    fe_monotone = all(fe_values[i] <= fe_values[i+1]
                       for i in range(len(fe_values)-1))
    print(f"  False escalation vs decay: "
          f"{'MONOTONE (more decay → more false esc)' if fe_monotone else 'NON-MONOTONE'}")

    # Pareto frontier: which decay values are not dominated?
    print(f"\n  PARETO ANALYSIS (delayed_correction_recovery vs false_escalation):")
    pareto = []
    for d in sorted_decays:
        r = sweep_results[d]
        dcr = r["delayed_correction_recovery"]
        fe = r["false_escalation_rate"]
        dominated = False
        for d2 in sorted_decays:
            if d2 == d:
                continue
            r2 = sweep_results[d2]
            if (r2["delayed_correction_recovery"] >= dcr and
                r2["false_escalation_rate"] <= fe and
                (r2["delayed_correction_recovery"] > dcr or
                 r2["false_escalation_rate"] < fe)):
                dominated = True
                break
        if not dominated:
            pareto.append(d)
            print(f"    decay={d:.2f}  del_corr={dcr:.1f}%  false_esc={fe:.1f}%  "
                  f"acc={r['overall_accuracy']:.1f}%  {'*PASS*' if r['all_gates_pass'] else ''}")

    print(f"\n  Pareto-optimal values: {[f'{d:.2f}' for d in pareto]}")

    # --- Verdict ---
    print(f"\n" + "=" * 90)
    if passing_decays:
        if len(passing_decays) >= 3:
            print(f"  VERDICT: OPERATING RANGE EXISTS [{min(passing_decays):.2f}, {max(passing_decays):.2f}]")
        elif len(passing_decays) >= 1:
            print(f"  VERDICT: NARROW OPERATING POINT (only {len(passing_decays)} value(s) pass)")
        if cliffs:
            print(f"  WARNING: {len(cliffs)} cliff edge(s) detected — response is NOT smooth")
        else:
            print(f"  RESPONSE: Smooth degradation confirmed")
    else:
        print(f"  VERDICT: NO OPERATING POINT FOUND — architecture needs redesign")
    print("=" * 90)

    # --- Cost + receipt ---
    wall_total = round(time.time() - t_start, 3)
    cost = {
        "wall_time_s": wall_total,
        "cpu_time_s": round(time.process_time() - cpu_start, 3),
        "peak_memory_mb": round(
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
        "python_version": platform.python_version(),
        "hostname": platform.node(),
        "timestamp_start": start_iso,
        "timestamp_end": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Flatten sweep results for receipt (remove per_condition detail for brevity)
    sweep_summary = {}
    for d in decay_values:
        r = dict(sweep_results[d])
        r.pop("per_condition", None)
        sweep_summary[f"{d:.2f}"] = r

    receipt = {
        "experiment": "MORPHSAT_DECAY_SENSITIVITY_V1",
        "seed": seed,
        "n_scenarios": len(scenarios),
        "n_decay_values": len(decay_values),
        "decay_values": decay_values,
        "conditions": conditions,
        "enable_dual_boundary": enable_dual_boundary,
        "commit_threat_boundary": commit_threat_boundary if enable_dual_boundary else None,
        "commit_safe_boundary": commit_safe_boundary if enable_dual_boundary else None,
        "sweep": sweep_summary,
        "passing_range": [min(passing_decays), max(passing_decays)] if passing_decays else None,
        "n_passing": len(passing_decays),
        "cliffs": cliffs,
        "pareto_optimal": pareto,
        "abstain_summary": {
            "total_abstain": sum(sweep_results[d]["total_abstain"] for d in decay_values),
            "total_abstain_uncertainty": sum(sweep_results[d]["total_abstain_uncertainty"] for d in decay_values),
            "total_abstain_on_benign": sum(sweep_results[d]["abstain_on_benign"] for d in decay_values),
            "total_abstain_on_suspicious": sum(sweep_results[d]["abstain_on_suspicious"] for d in decay_values),
            "total_abstain_on_escalate": sum(sweep_results[d]["abstain_on_escalate"] for d in decay_values),
        },
        "cost": cost,
    }

    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    receipt_path = RECEIPTS_DIR / f"decay_sensitivity_{ts}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, default=str))
    print(f"\n  Receipt: {receipt_path}")
    print(f"  Wall time: {wall_total:.1f}s")

    return receipt


def main():
    parser = argparse.ArgumentParser(
        description="MorphSAT Phase 1.6 — Decay Sensitivity Map")
    parser.add_argument("--step", type=float, default=0.05,
                        help="Step size for decay sweep (default: 0.05)")
    parser.add_argument("--min-decay", type=float, default=0.50,
                        help="Minimum decay value (default: 0.50)")
    parser.add_argument("--max-decay", type=float, default=1.00,
                        help="Maximum decay value (default: 1.00)")
    parser.add_argument("--condition", type=str, default=None,
                        choices=["A", "B", "C", "D", "all"],
                        help="Run specific condition group (default: all)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dual-boundary", action="store_true",
                        help="Enable dual-boundary (SPRT-like) mode")
    parser.add_argument("--threat-boundary", type=float, default=0.55,
                        help="Commit-threat boundary (default: 0.55)")
    parser.add_argument("--safe-boundary", type=float, default=0.40,
                        help="Commit-safe boundary (default: 0.40)")
    args = parser.parse_args()

    if args.condition == "A":
        conditions = ["control", "A_noise", "A_noise_heavy"]
    elif args.condition == "B":
        conditions = ["control", "B_contradiction", "B_contradiction_heavy"]
    elif args.condition == "C":
        conditions = ["control", "C_adversarial_kw", "C_adversarial_kw_heavy"]
    elif args.condition == "D":
        conditions = ["control", "D_delayed_correction", "D_delayed_correction_long"]
    else:
        conditions = None

    # Build decay values
    decay_values = []
    d = args.min_decay
    while d <= args.max_decay + 1e-9:
        decay_values.append(round(d, 3))
        d += args.step

    mode = "DUAL-BOUNDARY" if args.dual_boundary else "SINGLE-THRESHOLD"
    print(f"MorphSAT Phase 1.6 — Decay Sensitivity Map ({mode})")
    print(f"  Decay range: [{args.min_decay}, {args.max_decay}] step {args.step}")
    print(f"  Values: {len(decay_values)}")
    print(f"  Conditions: {conditions or 'all'}")
    print(f"  Seed: {args.seed}")
    print(f"  Scenarios: {len(ADVERSARIAL_SCENARIOS)}")
    if args.dual_boundary:
        print(f"  Threat boundary: {args.threat_boundary}")
        print(f"  Safe boundary: {args.safe_boundary}")

    sweep_decay(
        decay_values=decay_values,
        conditions=conditions,
        seed=args.seed,
        verbose=args.verbose,
        enable_dual_boundary=args.dual_boundary,
        commit_threat_boundary=args.threat_boundary,
        commit_safe_boundary=args.safe_boundary,
    )


if __name__ == "__main__":
    main()
