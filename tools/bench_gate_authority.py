#!/usr/bin/env python3
"""MORPHSAT v8 Gate Authority Experiment.

Tests who should have final verdict authority when the v7 shadow monitor
fires COMMIT with a direction.

Three conditions, one model (7B), same 20 scenarios:
  A: model_decides  — v7 baseline (model gives verdict)
  B: gate_overrides — monitor direction replaces model verdict
  C: gate_assists   — strong prompt with monitor's conclusion

Decision logic:
  gate_overrides > model_decides → monitor signal good, model is bottleneck
    gate_assists ≈ gate_overrides → ship gate_assists (prompt fix)
    gate_assists ≈ model_decides → ship gate_overrides (hard override)
  gate_overrides ≤ model_decides → monitor direction has errors, don't override

Usage:
    python3 tools/bench_gate_authority.py --port 8085
"""

import argparse
import json
import os
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Add morphsat to path
sys.path.insert(0, str(Path.home() / "morphsat"))
from morphsat.shadow_monitor import ShadowMonitor, ShadowState
from morphsat.commit_gate import SplitMemoryStore, CommitAction

# Add sentinel eval to path
sys.path.insert(0, str(Path.home() / "tools" / "sentinel"))
from eval.grammar import query_llama_multi
from eval.bench_morphsat import (
    BENCHMARK_SCENARIOS, TRIAGE_SYSTEM_PROMPT,
    simulate_tool, classify_output, score_verdict,
)

RECEIPTS_DIR = Path.home() / "receipts"
MAX_TURNS = 8


# ---------------------------------------------------------------------------
# Prompt builders per condition
# ---------------------------------------------------------------------------

def _summarize_evidence(monitor: ShadowMonitor) -> str:
    """One-line summary from monitor state for gate_assists prompt."""
    parts = []
    if monitor.threat_score > 0:
        parts.append(f"threat_score={monitor.threat_score:.2f}")
    if monitor.safety_score > 0:
        parts.append(f"safety_score={monitor.safety_score:.2f}")
    parts.append(f"tools_used={monitor.total_tools}")
    parts.append(f"state={monitor.state.value}")
    return ", ".join(parts)


def commit_prompt_a(action, monitor):
    """Condition A: model_decides (v7 baseline). Neutral prompt."""
    if action.action == "ABSTAIN":
        return ("[SYSTEM] Evidence is contradictory or exceeds local capacity. "
                "Issue verdict as 'suspicious' with low confidence.")
    elif action.direction == "escalate":
        return "[SYSTEM] Threat evidence sufficient. Issue your verdict now."
    elif action.direction == "benign":
        return "[SYSTEM] Safety evidence sufficient. Issue your verdict now."
    else:
        return "[SYSTEM] Evidence threshold reached. Issue your verdict now."


def commit_prompt_c(action, monitor):
    """Condition C: gate_assists. Strong directional prompt."""
    evidence = _summarize_evidence(monitor)

    if action.action == "ABSTAIN":
        return (
            "[SYSTEM] The investigation controller has concluded the evidence is "
            "CONTRADICTORY or INSUFFICIENT for a local decision. "
            f"Evidence state: {evidence}. "
            "You MUST output verdict 'suspicious' with low confidence. "
            "Issue your verdict now.")
    elif action.direction == "escalate":
        return (
            "[SYSTEM] The investigation controller has concluded this is a "
            "THREAT requiring ESCALATION based on accumulated evidence. "
            f"Threat indicators: {evidence}. "
            "You MUST output verdict 'escalate' UNLESS you have specific "
            "evidence that contradicts the threat assessment. "
            "Issue your verdict now.")
    elif action.direction == "benign":
        return (
            "[SYSTEM] The investigation controller has concluded this alert is "
            "BENIGN based on accumulated safety evidence. "
            f"Safety indicators: {evidence}. "
            "You MUST output verdict 'benign' UNLESS you have specific "
            "evidence of threat that contradicts the safety assessment. "
            "Issue your verdict now.")
    else:
        return (
            "[SYSTEM] The investigation controller has concluded the evidence is "
            f"AMBIGUOUS. Evidence state: {evidence}. "
            "You MUST output verdict 'suspicious' to flag for further review. "
            "Issue your verdict now.")


# ---------------------------------------------------------------------------
# Unified runner — parameterized by condition
# ---------------------------------------------------------------------------

def run_scenario(scenario: Dict, port: int, memory: SplitMemoryStore,
                 condition: str) -> Dict:
    """Run one scenario under a given condition.

    condition: 'model_decides' | 'gate_overrides' | 'gate_assists'
    """
    monitor = ShadowMonitor(memory=memory)
    monitor.initialize(scenario["alert"])

    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Triage this alert:\n{scenario['alert']}"},
    ]
    turns = []
    verdict = None
    model_verdict = None  # what the model actually said (for condition B)
    tool_call_count = 0
    overridden = False
    model_agreed = None  # for condition C
    t_start = time.time()

    for turn_num in range(MAX_TURNS):
        if monitor.committed:
            action = monitor.last_action

            if condition == "gate_overrides":
                # Condition B: still prompt model (record what it says),
                # but we'll override the verdict below
                prompt = commit_prompt_a(action, monitor)
            elif condition == "gate_assists":
                # Condition C: strong directional prompt
                prompt = commit_prompt_c(action, monitor)
            else:
                # Condition A: baseline
                prompt = commit_prompt_a(action, monitor)

            messages.append({"role": "user", "content": prompt})

        resp = query_llama_multi(port, messages, max_tokens=400)
        content = resp["content"]
        event_type, payload = classify_output(content)

        if event_type is None:
            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content":
                "Continue. Use a tool or issue your verdict."})
            turns.append({"turn": turn_num, "type": "reasoning",
                          "tokens": resp["tokens"], "wall_s": resp["wall_s"]})
            continue

        if event_type == "TOOL_CALL":
            if monitor.committed:
                messages.append({"role": "assistant", "content": content})
                messages.append({"role": "user", "content":
                    "[SYSTEM] Investigation complete. You must decide now."})
                turns.append({"turn": turn_num, "type": "gate_block",
                              "tokens": resp["tokens"], "wall_s": resp["wall_s"]})
                continue

            tool_call_count += 1
            tool_name = payload.get("name", "unknown")
            tool_args = payload.get("arguments", {})
            tool_result = simulate_tool(tool_name, tool_args, scenario)
            action = monitor.process_evidence(
                tool_name, tool_result, model_output=content)

            messages.append({"role": "assistant", "content": content})
            messages.append({"role": "user", "content": f"Tool result:\n{tool_result}"})
            turns.append({
                "turn": turn_num, "type": "tool_call", "tool": tool_name,
                "shadow_state": monitor.state.value,
                "action": action.action,
                "direction": action.direction,
                "tokens": resp["tokens"], "wall_s": resp["wall_s"],
            })

        elif event_type == "VERDICT_ISSUED":
            model_verdict = payload.get("verdict", "").lower().strip()
            verdict = model_verdict
            turns.append({"turn": turn_num, "type": "verdict",
                          "verdict": model_verdict,
                          "tokens": resp["tokens"], "wall_s": resp["wall_s"]})
            break

    # Force verdict if none issued
    if verdict is None:
        if not monitor.committed:
            monitor._force_commit("max_turns_no_verdict")
        messages.append({"role": "user", "content":
            "You must issue your final verdict NOW. Output a verdict block."})
        resp = query_llama_multi(port, messages, max_tokens=200)
        _, payload = classify_output(resp["content"])
        if payload and "verdict" in payload:
            model_verdict = payload["verdict"].lower().strip()
            verdict = model_verdict
            turns.append({"turn": len(turns), "type": "forced_verdict",
                          "verdict": model_verdict,
                          "tokens": resp["tokens"], "wall_s": resp["wall_s"]})

    # --- Condition B: gate_overrides ---
    gate_direction = monitor.last_action.direction if monitor.committed else None
    if condition == "gate_overrides" and monitor.committed and gate_direction:
        if verdict != gate_direction:
            overridden = True
            verdict = gate_direction

    # --- Condition C: track agreement ---
    if condition == "gate_assists" and monitor.committed and gate_direction:
        model_agreed = (model_verdict == gate_direction)

    # Close episode
    resolution = verdict or gate_direction or "suspicious"
    confidence = 0.8 if verdict and score_verdict(verdict, scenario["category"]) == 2 else 0.5
    monitor.close_episode(resolution, confidence)

    tool_loop = model_verdict is None or any(
        t["type"] == "forced_verdict" for t in turns)

    return {
        "scenario_id": scenario["id"],
        "category": scenario["category"],
        "condition": condition,
        "verdict": verdict,
        "model_verdict": model_verdict,
        "gate_direction": gate_direction,
        "overridden": overridden,
        "model_agreed": model_agreed,
        "score": score_verdict(verdict, scenario["category"]),
        "model_score": score_verdict(model_verdict, scenario["category"]),
        "n_turns": len(turns),
        "n_tool_calls": tool_call_count,
        "tool_loop": tool_loop,
        "wall_time_s": round(time.time() - t_start, 3),
        "final_state": monitor.state.value,
    }


# ---------------------------------------------------------------------------
# Summarize
# ---------------------------------------------------------------------------

def summarize_condition(results: List[Dict], condition: str) -> Dict:
    n = len(results)
    total_score = sum(r["score"] for r in results)
    max_score = n * 2

    cat_scores = {}
    for r in results:
        cat = r["category"]
        if cat not in cat_scores:
            cat_scores[cat] = {"score": 0, "max": 0, "model_score": 0}
        cat_scores[cat]["score"] += r["score"]
        cat_scores[cat]["model_score"] += r["model_score"]
        cat_scores[cat]["max"] += 2

    summary = {
        "condition": condition,
        "accuracy_pct": round(100 * total_score / max_score, 1),
        "model_accuracy_pct": round(
            100 * sum(r["model_score"] for r in results) / max_score, 1),
        "tool_loop_rate_pct": round(
            100 * sum(1 for r in results if r["tool_loop"]) / n, 1),
        "avg_turns": round(sum(r["n_turns"] for r in results) / n, 2),
        "per_category": {
            cat: {
                "accuracy_pct": round(100 * cs["score"] / cs["max"], 1),
                "model_accuracy_pct": round(100 * cs["model_score"] / cs["max"], 1),
            }
            for cat, cs in cat_scores.items()
        },
    }

    # Condition-specific
    if condition == "gate_overrides":
        summary["n_overridden"] = sum(1 for r in results if r["overridden"])
        summary["override_helped"] = sum(
            1 for r in results if r["overridden"] and r["score"] > r["model_score"])
        summary["override_hurt"] = sum(
            1 for r in results if r["overridden"] and r["score"] < r["model_score"])
        summary["override_neutral"] = sum(
            1 for r in results if r["overridden"] and r["score"] == r["model_score"])
    elif condition == "gate_assists":
        agreed = [r for r in results if r["model_agreed"] is not None]
        summary["n_with_direction"] = len(agreed)
        summary["n_model_agreed"] = sum(1 for r in agreed if r["model_agreed"])
        summary["n_model_disagreed"] = sum(1 for r in agreed if not r["model_agreed"])
        summary["agreement_rate_pct"] = round(
            100 * summary["n_model_agreed"] / len(agreed), 1) if agreed else 0

    # Wrong list
    summary["wrong"] = [
        {"id": r["scenario_id"], "category": r["category"],
         "verdict": r["verdict"], "model_verdict": r["model_verdict"],
         "gate_direction": r["gate_direction"]}
        for r in results if r["score"] < 2
    ]

    return summary


# ---------------------------------------------------------------------------
# Decision gate
# ---------------------------------------------------------------------------

def apply_decision(summaries: Dict[str, Dict]) -> Dict:
    a = summaries["model_decides"]
    b = summaries["gate_overrides"]
    c = summaries["gate_assists"]

    a_acc = a["accuracy_pct"]
    b_acc = b["accuracy_pct"]
    c_acc = c["accuracy_pct"]

    decision = {}
    if b_acc > a_acc:
        decision["monitor_signal"] = "GOOD"
        decision["model_is_bottleneck"] = True
        if abs(c_acc - b_acc) <= 2.5:
            decision["verdict"] = "SHIP_GATE_ASSISTS"
            decision["reason"] = (
                f"gate_assists ({c_acc}%) ≈ gate_overrides ({b_acc}%). "
                f"Strong prompt is sufficient — no hard override needed.")
        elif abs(c_acc - a_acc) <= 2.5:
            decision["verdict"] = "SHIP_GATE_OVERRIDES"
            decision["reason"] = (
                f"gate_assists ({c_acc}%) ≈ model_decides ({a_acc}%). "
                f"Model ignores strong prompts. Hard override needed for escalation.")
        else:
            decision["verdict"] = "MIXED"
            decision["reason"] = (
                f"gate_assists ({c_acc}%) between model_decides ({a_acc}%) "
                f"and gate_overrides ({b_acc}%). Partial prompt effect.")
    elif b_acc == a_acc:
        decision["monitor_signal"] = "NEUTRAL"
        decision["model_is_bottleneck"] = False
        decision["verdict"] = "NO_CHANGE"
        decision["reason"] = (
            f"gate_overrides ({b_acc}%) = model_decides ({a_acc}%). "
            f"Override doesn't help. Monitor direction matches model verdict "
            f"or errors cancel out.")
    else:
        decision["monitor_signal"] = "HAS_ERRORS"
        decision["model_is_bottleneck"] = False
        decision["verdict"] = "DO_NOT_OVERRIDE"
        decision["reason"] = (
            f"gate_overrides ({b_acc}%) < model_decides ({a_acc}%). "
            f"Monitor direction has errors. Investigate which scenarios "
            f"the monitor gets wrong.")

    # Escalation-specific comparison
    a_esc = a["per_category"].get("escalate", {}).get("accuracy_pct", 0)
    b_esc = b["per_category"].get("escalate", {}).get("accuracy_pct", 0)
    c_esc = c["per_category"].get("escalate", {}).get("accuracy_pct", 0)
    decision["escalate_detail"] = {
        "model_decides": a_esc,
        "gate_overrides": b_esc,
        "gate_assists": c_esc,
        "override_escalate_delta_pp": round(b_esc - a_esc, 1),
        "assists_escalate_delta_pp": round(c_esc - a_esc, 1),
    }

    return decision


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_experiment(port: int, label: str = "v8") -> Dict:
    conditions = ["model_decides", "gate_overrides", "gate_assists"]

    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    t_start = time.time()
    cpu_start = time.process_time()

    all_results = {}
    all_summaries = {}

    for condition in conditions:
        print(f"\n{'='*60}")
        print(f"  CONDITION: {condition}")
        print(f"{'='*60}\n")

        # Fresh memory per condition (isolation)
        memory_path = f"/tmp/v8_gate_{condition}_{int(time.time())}.json"
        memory = SplitMemoryStore(memory_path)
        results = []

        for i, scenario in enumerate(BENCHMARK_SCENARIOS):
            print(f"  [{i+1:2d}/{len(BENCHMARK_SCENARIOS)}] "
                  f"{scenario['id']:12s} ({scenario['category']:10s}) ...",
                  end="", flush=True)

            result = run_scenario(scenario, port, memory, condition)
            results.append(result)

            v = result["verdict"] or "NONE"
            mv = result["model_verdict"] or "NONE"
            sc = result["score"]
            ov = " OVR" if result["overridden"] else ""
            ag = ""
            if result["model_agreed"] is not None:
                ag = " AGR" if result["model_agreed"] else " DIS"
            gd = f" [{result['gate_direction'] or '-'}]"
            print(f" => {v:10s} (model={mv:10s}) {sc}/2{ov}{ag}{gd} "
                  f"({result['wall_time_s']:.1f}s)")

        all_results[condition] = results
        summary = summarize_condition(results, condition)
        all_summaries[condition] = summary

        print(f"\n  {condition}: {summary['accuracy_pct']}% accuracy "
              f"(model would be {summary['model_accuracy_pct']}%)")

        # Cleanup temp memory
        Path(memory_path).unlink(missing_ok=True)

    # Print comparison
    print(f"\n{'='*70}")
    print(f"  COMPARISON")
    print(f"{'='*70}\n")

    headers = ["Metric"] + conditions
    print(f"  {headers[0]:<25s}", end="")
    for h in headers[1:]:
        print(f"  {h:>16s}", end="")
    print()
    print(f"  {'-'*25}", end="")
    for _ in conditions:
        print(f"  {'-'*16}", end="")
    print()

    for metric in ["accuracy_pct", "model_accuracy_pct",
                    "tool_loop_rate_pct", "avg_turns"]:
        print(f"  {metric:<25s}", end="")
        for c in conditions:
            val = all_summaries[c].get(metric, "-")
            print(f"  {str(val):>16s}", end="")
        print()

    print()
    for cat in ["benign", "suspicious", "escalate"]:
        print(f"  {cat:<25s}", end="")
        for c in conditions:
            val = all_summaries[c]["per_category"].get(
                cat, {}).get("accuracy_pct", "-")
            s = f"{val}%" if val != "-" else "-"
            print(f"  {s:>16s}", end="")
        print()

    # Condition-specific
    b = all_summaries["gate_overrides"]
    print(f"\n  gate_overrides: {b['n_overridden']} overridden "
          f"(helped {b['override_helped']}, hurt {b['override_hurt']}, "
          f"neutral {b['override_neutral']})")

    c_sum = all_summaries["gate_assists"]
    print(f"  gate_assists: {c_sum['n_model_agreed']}/{c_sum['n_with_direction']} "
          f"model agreed ({c_sum['agreement_rate_pct']}%)")

    # Decision
    decision = apply_decision(all_summaries)
    print(f"\n{'='*70}")
    print(f"  DECISION")
    print(f"{'='*70}")
    print(f"  Monitor signal: {decision['monitor_signal']}")
    print(f"  Verdict: {decision['verdict']}")
    print(f"  Reason: {decision['reason']}")
    esc = decision["escalate_detail"]
    print(f"  Escalate: A={esc['model_decides']}% B={esc['gate_overrides']}% "
          f"C={esc['gate_assists']}% "
          f"(override delta {esc['override_escalate_delta_pp']:+.1f}pp, "
          f"assists delta {esc['assists_escalate_delta_pp']:+.1f}pp)")

    # Build receipt
    wall_total = round(time.time() - t_start, 3)
    receipt = {
        "experiment": f"MORPHSAT_{label.upper()}_GATE_AUTHORITY",
        "model": "qwen2.5-coder-7b",
        "conditions": conditions,
        "n_scenarios": len(BENCHMARK_SCENARIOS),
        "per_condition": all_summaries,
        "decision": decision,
        "results": all_results,
        "cost": {
            "wall_time_s": wall_total,
            "cpu_time_s": round(time.process_time() - cpu_start, 3),
            "peak_memory_mb": round(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "timestamp_start": start_iso,
            "timestamp_end": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    }

    RECEIPTS_DIR.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    receipt_path = RECEIPTS_DIR / f"morphsat_{label}_gate_authority_{ts}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, default=str))
    print(f"\n  Receipt: {receipt_path}")
    print(f"  Wall time: {wall_total:.1f}s ({wall_total/60:.1f}m)")

    return receipt


def main():
    parser = argparse.ArgumentParser(
        description="MorphSAT v8 Gate Authority Experiment")
    parser.add_argument("--port", type=int, default=8085,
                        help="llama-server port")
    parser.add_argument("--label", type=str, default="v8",
                        help="Experiment label for receipt filename")
    args = parser.parse_args()

    print(f"MorphSAT {args.label} Gate Authority Experiment")
    print(f"  Port: {args.port}")
    print(f"  Model: Qwen2.5-Coder-7B Q4_K_M")
    print(f"  Conditions: model_decides, gate_overrides, gate_assists")
    print(f"  Scenarios: {len(BENCHMARK_SCENARIOS)}")
    print()

    run_experiment(port=args.port, label=args.label)


if __name__ == "__main__":
    main()
