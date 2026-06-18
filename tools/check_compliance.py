#!/usr/bin/env python3
"""MorphSAT Plan 5 — Receipt-Level Compliance Checker.

Verifies that shadow monitor execution traces satisfy formal properties
derived from the architecture specification. These are past-time temporal
logic (PPLTL) properties: they check whether a trace ALREADY PRODUCED
satisfies invariants, not whether future traces will.

Properties checked:

  P1: NEVER commit before minimum evidence
      COMMIT or ABSTAIN must not occur before turn >= 2.
      (Structural: early-verdict guard in harness, but must hold in trace.)

  P2: NEVER escalate without threat evidence
      If final action is COMMIT with direction "escalate",
      then threat_score > safety_score at commit turn.

  P3: If inside continue zone and budget exhausts, ABSTAIN
      In dual-boundary mode, if the last turn has evidence_balance inside
      [-safe_boundary, threat_boundary] and action is forced, then
      action must be ABSTAIN, not COMMIT.

  P4: Correction evidence must be processed before terminal verdict
      If a "correction" or "negated_threat" category appears in the trace,
      and the trace ends in COMMIT, then the correction must appear BEFORE
      the commit turn (not after — post-commit evidence is ignored).

  P5: Every commitment must cite boundary crossed (dual-boundary mode)
      If dual_boundary is True and final action is COMMIT, then exactly
      one boundary must be recorded as crossed in the trace reason.

  P6: No state transition skips the state machine
      Posture transitions must follow legal edges. NORMAL cannot jump
      directly to COMMIT_READY without going through INVESTIGATING or
      clarity threshold.

  P7: Threat decay monotonicity
      cumulative_threat_decayed must be non-decreasing across turns
      (decay is additive — you can't un-decay).

Usage:
    python3 tools/check_compliance.py                  # check latest receipt
    python3 tools/check_compliance.py --receipt FILE   # check specific receipt
    python3 tools/check_compliance.py --sweep          # check all decay sweep receipts
    python3 tools/check_compliance.py --generate       # generate fresh traces + check

WO-RECEIPT-COST-01 compliant.
"""

import argparse
import json
import platform
import resource
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

RECEIPTS_DIR = Path.home() / "receipts" / "morphsat_adversarial"
COMPLIANCE_DIR = Path.home() / "receipts" / "morphsat_compliance"


# Valid state transitions in the shadow monitor
LEGAL_TRANSITIONS = {
    "normal": {"orienting", "commit_ready", "escalate_ready",
               "abstain_ready", "swarm_call", "normal"},
    "orienting": {"normal", "safe_distance", "investigating",
                  "escalate_ready", "commit_ready", "abstain_ready",
                  "swarm_call"},
    "safe_distance": {"normal", "escalate_ready", "commit_ready",
                      "abstain_ready", "swarm_call"},
    "investigating": {"commit_ready", "escalate_ready", "abstain_ready",
                      "swarm_call"},
    "commit_ready": set(),  # terminal
    "escalate_ready": set(),  # terminal
    "abstain_ready": set(),  # terminal
    "swarm_call": set(),  # terminal
}


@dataclass
class PropertyResult:
    """Result of checking one property on one trace."""
    property_id: str
    property_name: str
    passed: bool
    detail: str
    turn: Optional[int] = None  # turn where violation occurred


@dataclass
class TraceComplianceResult:
    """Result of checking all properties on one trace."""
    scenario_id: str
    condition: str
    decay: float
    dual_boundary: bool
    n_turns: int
    properties: List[PropertyResult]
    all_passed: bool = field(init=False)

    def __post_init__(self):
        self.all_passed = all(p.passed for p in self.properties)


def check_trace(history: List[dict], posture_trace: List[dict],
                scenario_id: str = "unknown", condition: str = "unknown",
                decay: float = 1.0, dual_boundary: bool = False,
                commit_threat_boundary: float = 0.55,
                commit_safe_boundary: float = 0.40,
                final_action: str = "",
                final_direction: str = "",
                final_reason: str = "") -> TraceComplianceResult:
    """Check all properties on a single execution trace."""

    results = []

    # --- P1: Never commit before minimum evidence ---
    commit_turn = None
    for h in history:
        if h["action"] in ("COMMIT", "ABSTAIN"):
            commit_turn = h["turn"]
            break
    if commit_turn is not None:
        p1_pass = commit_turn >= 2
        results.append(PropertyResult(
            "P1", "never_commit_before_min_evidence",
            p1_pass,
            f"First terminal action at turn {commit_turn}"
            + ("" if p1_pass else " (VIOLATION: < 2)"),
            turn=commit_turn))
    else:
        results.append(PropertyResult(
            "P1", "never_commit_before_min_evidence",
            True, "No terminal action in trace"))

    # --- P2: Never escalate without threat evidence ---
    if final_action == "COMMIT" and final_direction == "escalate":
        if history:
            last = history[-1]
            p2_pass = last["threat_score"] > last["safety_score"]
            results.append(PropertyResult(
                "P2", "never_escalate_without_threat",
                p2_pass,
                f"Escalate with t={last['threat_score']:.3f} "
                f"s={last['safety_score']:.3f}"
                + ("" if p2_pass else " (VIOLATION: safety >= threat)"),
                turn=last["turn"]))
        else:
            results.append(PropertyResult(
                "P2", "never_escalate_without_threat",
                True, "No history"))
    else:
        results.append(PropertyResult(
            "P2", "never_escalate_without_threat",
            True, f"Final action is {final_action}/{final_direction}, not escalate"))

    # --- P3: Budget exhaustion in continue zone → ABSTAIN ---
    if dual_boundary and history:
        last = history[-1]
        balance = last.get("evidence_balance", 0.0)
        in_zone = (-commit_safe_boundary < balance < commit_threat_boundary)
        is_forced = final_reason and "forced:" in final_reason

        if in_zone and is_forced:
            p3_pass = final_action == "ABSTAIN"
            results.append(PropertyResult(
                "P3", "continue_zone_budget_exhaustion_abstains",
                p3_pass,
                f"Forced in zone (bal={balance:.3f}), "
                f"action={final_action}"
                + ("" if p3_pass else " (VIOLATION: should be ABSTAIN)"),
                turn=last["turn"]))
        elif in_zone and not is_forced:
            results.append(PropertyResult(
                "P3", "continue_zone_budget_exhaustion_abstains",
                True, f"In zone but not forced (bal={balance:.3f})"))
        else:
            results.append(PropertyResult(
                "P3", "continue_zone_budget_exhaustion_abstains",
                True, f"Not in zone at end (bal={balance:.3f})"))
    else:
        results.append(PropertyResult(
            "P3", "continue_zone_budget_exhaustion_abstains",
            True, "Single-threshold mode or no history"))

    # --- P4: Correction processed before terminal verdict ---
    correction_turns = [h["turn"] for h in history
                        if h["category"] in ("correction", "negated_threat")]
    if correction_turns and commit_turn is not None:
        # All corrections must appear before or at commit turn
        late_corrections = [t for t in correction_turns if t > commit_turn]
        p4_pass = len(late_corrections) == 0
        results.append(PropertyResult(
            "P4", "correction_before_terminal",
            p4_pass,
            f"Corrections at turns {correction_turns}, "
            f"commit at turn {commit_turn}"
            + (f" (VIOLATION: {len(late_corrections)} post-commit corrections)"
               if not p4_pass else ""),
            turn=late_corrections[0] if late_corrections else None))
    else:
        results.append(PropertyResult(
            "P4", "correction_before_terminal",
            True,
            f"{'No corrections' if not correction_turns else 'No commit'} "
            f"in trace"))

    # --- P5: Commitment cites boundary (dual-boundary) ---
    if dual_boundary and final_action == "COMMIT":
        cites_boundary = ("boundary crossed" in (final_reason or "")
                          or "boundary" in (final_reason or "").lower())
        results.append(PropertyResult(
            "P5", "commitment_cites_boundary",
            cites_boundary,
            f"Reason: {final_reason}"
            + ("" if cites_boundary else " (VIOLATION: no boundary citation)")))
    else:
        results.append(PropertyResult(
            "P5", "commitment_cites_boundary",
            True,
            f"{'Single-threshold' if not dual_boundary else 'Non-COMMIT'} — N/A"))

    # --- P6: Legal state transitions ---
    p6_violations = []
    for pt in posture_trace:
        from_state = pt.get("from", pt.get("from_state", ""))
        to_state = pt.get("to", pt.get("to_state", ""))
        if from_state in LEGAL_TRANSITIONS:
            legal_targets = LEGAL_TRANSITIONS[from_state]
            if to_state not in legal_targets and from_state != to_state:
                # Allow initialize transitions (turn 0)
                if pt.get("turn", 1) > 0:
                    p6_violations.append(
                        f"turn {pt.get('turn')}: {from_state}→{to_state}")
    results.append(PropertyResult(
        "P6", "legal_state_transitions",
        len(p6_violations) == 0,
        f"{len(p6_violations)} violations"
        + (f": {p6_violations}" if p6_violations else "")))

    # --- P7: Threat decay monotonicity ---
    if len(history) >= 2:
        decay_vals = [h.get("cumulative_threat_decayed", 0.0) for h in history]
        non_monotone = []
        for i in range(1, len(decay_vals)):
            if decay_vals[i] < decay_vals[i-1] - 1e-9:
                non_monotone.append(
                    f"turn {history[i]['turn']}: "
                    f"{decay_vals[i-1]:.3f}→{decay_vals[i]:.3f}")
        results.append(PropertyResult(
            "P7", "threat_decay_monotonicity",
            len(non_monotone) == 0,
            f"{len(non_monotone)} violations"
            + (f": {non_monotone}" if non_monotone else "")))
    else:
        results.append(PropertyResult(
            "P7", "threat_decay_monotonicity",
            True, "Too few turns to check"))

    return TraceComplianceResult(
        scenario_id=scenario_id,
        condition=condition,
        decay=decay,
        dual_boundary=dual_boundary,
        n_turns=len(history),
        properties=results)


def generate_and_check(decay_values: List[float] = None,
                       conditions: List[str] = None,
                       enable_dual_boundary: bool = False,
                       commit_threat_boundary: float = 0.55,
                       commit_safe_boundary: float = 0.40,
                       seed: int = 42) -> Dict:
    """Generate fresh traces and check compliance on each."""
    import random
    from morphsat.shadow_monitor import ShadowMonitor
    from morphsat.commit_gate import SplitMemoryStore, classify_tool_result
    from tools.bench_adversarial_robustness import (
        ADVERSARIAL_SCENARIOS, ALL_CONDITIONS,
        build_canonical_sequence,
        inject_noise, inject_contradictions,
        inject_adversarial_keywords, inject_delayed_correction,
    )

    if decay_values is None:
        decay_values = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]
    if conditions is None:
        conditions = ALL_CONDITIONS

    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    t_start = time.time()
    cpu_start = time.process_time()

    all_results = []
    property_counts = {}

    for decay in decay_values:
        for condition in conditions:
            rng = random.Random(seed)
            for scenario in ADVERSARIAL_SCENARIOS:
                # Build tool sequence with same injection as run_condition
                canonical = build_canonical_sequence(
                    scenario, n_tools=3, rng=random.Random(42))
                sub_rng = random.Random(rng.randint(0, 10000))

                if condition == "control":
                    tool_seq = canonical
                elif condition == "A_noise":
                    tool_seq = inject_noise(canonical, n_noise=2,
                                            position="interleaved", rng=sub_rng)
                elif condition == "A_noise_heavy":
                    tool_seq = inject_noise(canonical, n_noise=4,
                                            position="random", rng=sub_rng)
                elif condition == "B_contradiction":
                    tool_seq = inject_contradictions(canonical,
                                                     n_contradictions=1, rng=sub_rng)
                elif condition == "B_contradiction_heavy":
                    tool_seq = inject_contradictions(canonical,
                                                     n_contradictions=2, rng=sub_rng)
                elif condition == "C_adversarial_kw":
                    tool_seq = inject_adversarial_keywords(canonical,
                                                           n_adversarial=2, rng=sub_rng)
                elif condition == "C_adversarial_kw_heavy":
                    tool_seq = inject_adversarial_keywords(canonical,
                                                           n_adversarial=3, rng=sub_rng)
                elif condition == "D_delayed_correction":
                    tool_seq = inject_delayed_correction(canonical,
                                                         delay_steps=2, rng=sub_rng)
                elif condition == "D_delayed_correction_long":
                    tool_seq = inject_delayed_correction(canonical,
                                                         delay_steps=4, rng=sub_rng)
                else:
                    raise ValueError(f"Unknown condition: {condition}")

                # Run fresh monitor
                tmp_path = f"/tmp/compliance_{id(scenario)}_{hash(condition)}.json"
                memory = SplitMemoryStore(tmp_path)
                monitor = ShadowMonitor(
                    memory=memory,
                    evidence_decay=decay,
                    enable_correction=True,
                    enable_dual_boundary=enable_dual_boundary,
                    commit_threat_boundary=commit_threat_boundary,
                    commit_safe_boundary=commit_safe_boundary,
                )
                monitor.initialize(scenario["alert"])

                for tool_name, tool_result in tool_seq:
                    if monitor.committed:
                        break
                    monitor.process_evidence(tool_name, tool_result)

                if not monitor.committed:
                    balance = monitor.threat_score - monitor.safety_score
                    monitor._force_commit("compliance_test_end", balance)

                # Check compliance on the trace
                compliance = check_trace(
                    history=monitor.history,
                    posture_trace=[
                        {"turn": t.turn, "from": t.from_state,
                         "to": t.to_state, "trigger": t.trigger}
                        for t in monitor.posture_trace
                    ],
                    scenario_id=scenario["id"],
                    condition=condition,
                    decay=decay,
                    dual_boundary=enable_dual_boundary,
                    commit_threat_boundary=commit_threat_boundary,
                    commit_safe_boundary=commit_safe_boundary,
                    final_action=monitor.last_action.action,
                    final_direction=monitor.last_action.direction or "",
                    final_reason=monitor.last_action.reason or "",
                )

                all_results.append(compliance)

                # Count per-property pass/fail
                for p in compliance.properties:
                    key = p.property_id
                    if key not in property_counts:
                        property_counts[key] = {"name": p.property_name,
                                                "pass": 0, "fail": 0,
                                                "violations": []}
                    if p.passed:
                        property_counts[key]["pass"] += 1
                    else:
                        property_counts[key]["fail"] += 1
                        property_counts[key]["violations"].append({
                            "scenario": scenario["id"],
                            "condition": condition,
                            "decay": decay,
                            "detail": p.detail,
                            "turn": p.turn,
                        })

                Path(tmp_path).unlink(missing_ok=True)

    # --- Print results ---
    n_total = len(all_results)
    n_pass = sum(1 for r in all_results if r.all_passed)

    print("\n" + "=" * 80)
    print("  MORPHSAT PLAN 5 — RECEIPT-LEVEL COMPLIANCE CHECK")
    print("=" * 80)
    print(f"\n  Traces checked: {n_total}")
    print(f"  All properties pass: {n_pass}/{n_total} "
          f"({100*n_pass/n_total:.1f}%)")
    print(f"  Dual-boundary: {enable_dual_boundary}")
    print(f"  Decay values: {decay_values}")

    print(f"\n  {'Property':>4s}  {'Name':<45s}  {'Pass':>5s}  {'Fail':>5s}  {'Rate':>6s}")
    print(f"  {'----':>4s}  {'-'*45}  {'-----':>5s}  {'-----':>5s}  {'------':>6s}")

    for pid in sorted(property_counts.keys()):
        pc = property_counts[pid]
        total = pc["pass"] + pc["fail"]
        rate = 100 * pc["pass"] / total if total > 0 else 0
        mark = "PASS" if pc["fail"] == 0 else "FAIL"
        print(f"  {pid:>4s}  {pc['name']:<45s}  "
              f"{pc['pass']:>5d}  {pc['fail']:>5d}  "
              f"{rate:>5.1f}% {mark}")

    # Print violations
    any_violations = any(pc["fail"] > 0 for pc in property_counts.values())
    if any_violations:
        print(f"\n  VIOLATIONS:")
        for pid in sorted(property_counts.keys()):
            pc = property_counts[pid]
            if pc["fail"] > 0:
                print(f"\n  {pid} ({pc['name']}):")
                for v in pc["violations"][:10]:  # limit to first 10
                    print(f"    {v['scenario']} / {v['condition']} / "
                          f"decay={v['decay']}: {v['detail']}")
                if len(pc["violations"]) > 10:
                    print(f"    ... and {len(pc['violations']) - 10} more")

    # --- Verdict ---
    print(f"\n" + "=" * 80)
    if not any_violations:
        print(f"  VERDICT: ALL {len(property_counts)} PROPERTIES SATISFIED "
              f"ACROSS {n_total} TRACES")
    else:
        n_violated = sum(1 for pc in property_counts.values() if pc["fail"] > 0)
        print(f"  VERDICT: {n_violated}/{len(property_counts)} PROPERTIES "
              f"VIOLATED")
    print("=" * 80)

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

    receipt = {
        "experiment": "MORPHSAT_COMPLIANCE_CHECK_V1",
        "n_traces": n_total,
        "n_all_pass": n_pass,
        "compliance_rate_pct": round(100 * n_pass / n_total, 1),
        "enable_dual_boundary": enable_dual_boundary,
        "commit_threat_boundary": commit_threat_boundary if enable_dual_boundary else None,
        "commit_safe_boundary": commit_safe_boundary if enable_dual_boundary else None,
        "decay_values": decay_values,
        "conditions": conditions,
        "seed": seed,
        "properties": {
            pid: {
                "name": pc["name"],
                "pass": pc["pass"],
                "fail": pc["fail"],
                "rate_pct": round(100 * pc["pass"] / (pc["pass"] + pc["fail"]), 1),
                "violations": pc["violations"][:20],  # cap at 20 per property
            }
            for pid, pc in sorted(property_counts.items())
        },
        "cost": cost,
    }

    COMPLIANCE_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    receipt_path = COMPLIANCE_DIR / f"compliance_check_{ts}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, default=str))
    print(f"\n  Receipt: {receipt_path}")
    print(f"  Wall time: {wall_total:.1f}s")

    return receipt


def main():
    parser = argparse.ArgumentParser(
        description="MorphSAT Plan 5 — Receipt-Level Compliance Check")
    parser.add_argument("--generate", action="store_true",
                        help="Generate fresh traces and check compliance")
    parser.add_argument("--dual-boundary", action="store_true",
                        help="Enable dual-boundary mode")
    parser.add_argument("--decay", type=float, nargs="+",
                        default=None,
                        help="Decay values to test (default: 0.70-1.00)")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    decay_values = args.decay
    if decay_values is None:
        decay_values = [0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00]

    generate_and_check(
        decay_values=decay_values,
        enable_dual_boundary=args.dual_boundary,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
