#!/usr/bin/env python3
"""MORPHSAT v8.1 Selective Gate Assists Experiment.

Tests calibrated escalation prompts to recover suspicious accuracy
without losing the v8 escalation gain.

Four conditions, one model (7B), same 20 scenarios:
  C0: v8_strong          — v8 gate_assists control (MUST ... UNLESS)
  C1: evidence_weigh     — list threat + counter-evidence, then verdict
  C2: soft_directive     — "you may agree or override"
  C3: direction_sensitive — C1 for escalate, neutral for everything else

Decision target:
  overall >= 92.5%, benign 100%, suspicious 75%, escalate >= 94.4%

Usage:
    python3 bench_gate_authority_v81.py --port 8085
"""

import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Dict, List

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

CONDITIONS = ["v8_strong", "evidence_weigh", "soft_directive", "direction_sensitive"]


# ---------------------------------------------------------------------------
# Evidence summary (shared)
# ---------------------------------------------------------------------------

def _summarize_evidence(monitor: ShadowMonitor) -> str:
    parts = []
    if monitor.threat_score > 0:
        parts.append(f"threat_score={monitor.threat_score:.2f}")
    if monitor.safety_score > 0:
        parts.append(f"safety_score={monitor.safety_score:.2f}")
    parts.append(f"tools_used={monitor.total_tools}")
    parts.append(f"state={monitor.state.value}")
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def prompt_neutral(action, monitor):
    """Condition A / neutral baseline (v7). Used for non-escalate directions."""
    if action.action == "ABSTAIN":
        return ("[SYSTEM] Evidence is contradictory or exceeds local capacity. "
                "Issue verdict as 'suspicious' with low confidence.")
    elif action.direction == "escalate":
        return "[SYSTEM] Threat evidence sufficient. Issue your verdict now."
    elif action.direction == "benign":
        return "[SYSTEM] Safety evidence sufficient. Issue your verdict now."
    else:
        return "[SYSTEM] Evidence threshold reached. Issue your verdict now."


def prompt_c0_strong(action, monitor):
    """C0: v8_strong. Exact v8 gate_assists prompt."""
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


def prompt_c1_evidence_weigh(action, monitor):
    """C1: evidence_weigh. Strong direction but asks for explicit evidence review."""
    evidence = _summarize_evidence(monitor)

    if action.action == "ABSTAIN":
        return prompt_c0_strong(action, monitor)  # same for abstain
    elif action.direction == "escalate":
        return (
            "[SYSTEM] The investigation controller has concluded this is a "
            "THREAT requiring ESCALATION based on accumulated evidence. "
            f"Threat indicators: {evidence}. "
            "Before issuing your verdict: "
            "1. State the single strongest threat indicator from your investigation. "
            "2. State the single strongest safety/mitigating indicator, if any. "
            "Then issue your verdict.")
    elif action.direction == "benign":
        return prompt_c0_strong(action, monitor)  # benign unchanged
    else:
        return prompt_c0_strong(action, monitor)  # suspicious unchanged


def prompt_c2_soft(action, monitor):
    """C2: soft_directive. Gate shares conclusion, no MUST language."""
    evidence = _summarize_evidence(monitor)

    if action.action == "ABSTAIN":
        return prompt_c0_strong(action, monitor)
    elif action.direction == "escalate":
        return (
            "[SYSTEM] The investigation controller's assessment is THREAT "
            f"requiring ESCALATION. Threat indicators: {evidence}. "
            "You may agree with this assessment or override it based on your "
            "investigation findings. Issue your verdict now.")
    elif action.direction == "benign":
        return prompt_c0_strong(action, monitor)
    else:
        return prompt_c0_strong(action, monitor)


def prompt_c3_direction_sensitive(action, monitor):
    """C3: direction_sensitive. C1 for escalate, neutral for everything else."""
    if action.direction == "escalate" and action.action != "ABSTAIN":
        return prompt_c1_evidence_weigh(action, monitor)
    else:
        return prompt_neutral(action, monitor)


# Dispatch table
PROMPT_DISPATCH = {
    "v8_strong": prompt_c0_strong,
    "evidence_weigh": prompt_c1_evidence_weigh,
    "soft_directive": prompt_c2_soft,
    "direction_sensitive": prompt_c3_direction_sensitive,
}


# ---------------------------------------------------------------------------
# Unified runner
# ---------------------------------------------------------------------------

def run_scenario(scenario: Dict, port: int, memory: SplitMemoryStore,
                 condition: str) -> Dict:
    monitor = ShadowMonitor(memory=memory)
    monitor.initialize(scenario["alert"])

    prompt_fn = PROMPT_DISPATCH[condition]

    messages = [
        {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Triage this alert:\n{scenario['alert']}"},
    ]
    turns = []
    verdict = None
    model_verdict = None
    tool_call_count = 0
    model_agreed = None
    t_start = time.time()

    for turn_num in range(MAX_TURNS):
        if monitor.committed:
            action = monitor.last_action
            prompt = prompt_fn(action, monitor)
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

    gate_direction = monitor.last_action.direction if monitor.committed else None

    # Track agreement (all conditions use directional prompts)
    if monitor.committed and gate_direction:
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

    # Agreement tracking
    agreed = [r for r in results if r["model_agreed"] is not None]
    summary["n_with_direction"] = len(agreed)
    summary["n_model_agreed"] = sum(1 for r in agreed if r["model_agreed"])
    summary["n_model_disagreed"] = sum(1 for r in agreed if not r["model_agreed"])
    summary["agreement_rate_pct"] = round(
        100 * summary["n_model_agreed"] / len(agreed), 1) if agreed else 0

    # Track time_06 specifically
    for r in results:
        if r["scenario_id"] == "time_06":
            summary["time_06_verdict"] = r["verdict"]
            summary["time_06_model_verdict"] = r["model_verdict"]
            summary["time_06_gate_direction"] = r["gate_direction"]
            summary["time_06_score"] = r["score"]

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
    c0 = summaries["v8_strong"]
    c1 = summaries["evidence_weigh"]
    c2 = summaries["soft_directive"]
    c3 = summaries["direction_sensitive"]

    decision = {
        "v8_control_accuracy": c0["accuracy_pct"],
        "conditions": {},
    }

    # Target: overall >= 92.5, benign 100, suspicious >= 75, escalate >= 94.4
    target_overall = 92.5
    target_suspicious = 75.0
    target_escalate = 94.4

    for name, s in summaries.items():
        acc = s["accuracy_pct"]
        sus = s["per_category"].get("suspicious", {}).get("accuracy_pct", 0)
        esc = s["per_category"].get("escalate", {}).get("accuracy_pct", 0)
        ben = s["per_category"].get("benign", {}).get("accuracy_pct", 0)
        t06 = s.get("time_06_verdict", "?")

        meets_target = (acc >= target_overall and sus >= target_suspicious
                        and esc >= target_escalate and ben >= 100.0)

        decision["conditions"][name] = {
            "accuracy": acc,
            "suspicious": sus,
            "escalate": esc,
            "benign": ben,
            "time_06": t06,
            "meets_target": meets_target,
        }

    # Find best condition
    winners = [name for name, d in decision["conditions"].items() if d["meets_target"]]

    if winners:
        # Prefer direction_sensitive if it wins
        if "direction_sensitive" in winners:
            decision["verdict"] = "SHIP_DIRECTION_SENSITIVE"
            decision["winner"] = "direction_sensitive"
        elif "evidence_weigh" in winners:
            decision["verdict"] = "SHIP_EVIDENCE_WEIGH"
            decision["winner"] = "evidence_weigh"
        elif "soft_directive" in winners:
            decision["verdict"] = "SHIP_SOFT_DIRECTIVE"
            decision["winner"] = "soft_directive"
        else:
            decision["verdict"] = "SHIP_V8_STRONG"
            decision["winner"] = "v8_strong"
        decision["reason"] = (
            f"{decision['winner']} meets all targets: "
            f"overall {decision['conditions'][decision['winner']]['accuracy']}%, "
            f"suspicious {decision['conditions'][decision['winner']]['suspicious']}%, "
            f"escalate {decision['conditions'][decision['winner']]['escalate']}%.")
    else:
        # Check if C2 lost escalation (proves MUST is load-bearing)
        c2_esc = decision["conditions"]["soft_directive"]["escalate"]
        c0_esc = decision["conditions"]["v8_strong"]["escalate"]
        if c2_esc < c0_esc - 5:
            decision["must_is_load_bearing"] = True

        # Check if any improved suspicious without losing escalate
        for name in ["evidence_weigh", "direction_sensitive"]:
            d = decision["conditions"][name]
            d0 = decision["conditions"]["v8_strong"]
            if d["suspicious"] > d0["suspicious"] and d["escalate"] >= d0["escalate"] - 2:
                decision["partial_winner"] = name
                break

        if "partial_winner" in decision:
            decision["verdict"] = "PARTIAL_IMPROVEMENT"
            decision["reason"] = (
                f"{decision['partial_winner']} improved suspicious without losing escalate, "
                f"but didn't meet full target.")
        else:
            decision["verdict"] = "PROMPT_CEILING_REACHED"
            decision["reason"] = (
                "No condition recovered suspicious while keeping escalation. "
                "Prompt-only ceiling is 90%. Next step: monitor threshold tuning.")

    return decision


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_experiment(port: int) -> Dict:
    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    t_start = time.time()
    cpu_start = time.process_time()

    all_results = {}
    all_summaries = {}

    for condition in CONDITIONS:
        print(f"\n{'='*60}")
        print(f"  CONDITION: {condition}")
        print(f"{'='*60}\n")

        memory_path = f"/tmp/v81_gate_{condition}_{int(time.time())}.json"
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
            ag = ""
            if result["model_agreed"] is not None:
                ag = " AGR" if result["model_agreed"] else " DIS"
            gd = f" [{result['gate_direction'] or '-'}]"
            marker = " ***" if result["scenario_id"] == "time_06" else ""
            print(f" => {v:10s} (model={mv:10s}) {sc}/2{ag}{gd} "
                  f"({result['wall_time_s']:.1f}s){marker}")

        all_results[condition] = results
        summary = summarize_condition(results, condition)
        all_summaries[condition] = summary

        t06 = summary.get("time_06_verdict", "?")
        print(f"\n  {condition}: {summary['accuracy_pct']}% accuracy "
              f"(time_06={t06})")

        Path(memory_path).unlink(missing_ok=True)

    # Comparison table
    print(f"\n{'='*78}")
    print(f"  COMPARISON")
    print(f"{'='*78}\n")

    headers = ["Metric"] + CONDITIONS
    print(f"  {headers[0]:<25s}", end="")
    for h in headers[1:]:
        print(f"  {h:>18s}", end="")
    print()
    print(f"  {'-'*25}", end="")
    for _ in CONDITIONS:
        print(f"  {'-'*18}", end="")
    print()

    for metric in ["accuracy_pct", "model_accuracy_pct",
                    "tool_loop_rate_pct", "avg_turns"]:
        print(f"  {metric:<25s}", end="")
        for c in CONDITIONS:
            val = all_summaries[c].get(metric, "-")
            print(f"  {str(val):>18s}", end="")
        print()

    print()
    for cat in ["benign", "suspicious", "escalate"]:
        print(f"  {cat:<25s}", end="")
        for c in CONDITIONS:
            val = all_summaries[c]["per_category"].get(
                cat, {}).get("accuracy_pct", "-")
            s = f"{val}%" if val != "-" else "-"
            print(f"  {s:>18s}", end="")
        print()

    # time_06 row
    print()
    print(f"  {'time_06 verdict':<25s}", end="")
    for c in CONDITIONS:
        t06 = all_summaries[c].get("time_06_verdict", "?")
        t06_score = all_summaries[c].get("time_06_score", "?")
        s = f"{t06} ({t06_score}/2)"
        print(f"  {s:>18s}", end="")
    print()

    # Agreement
    print()
    for c in CONDITIONS:
        s = all_summaries[c]
        print(f"  {c}: {s['n_model_agreed']}/{s['n_with_direction']} "
              f"agreed ({s['agreement_rate_pct']}%)")

    # Decision
    decision = apply_decision(all_summaries)
    print(f"\n{'='*78}")
    print(f"  DECISION")
    print(f"{'='*78}")
    print(f"  Verdict: {decision['verdict']}")
    print(f"  Reason: {decision['reason']}")
    if decision.get("must_is_load_bearing"):
        print(f"  NOTE: MUST language is load-bearing (soft_directive lost escalation)")

    # Receipt
    wall_total = round(time.time() - t_start, 3)
    receipt = {
        "experiment": "MORPHSAT_V8_1_SELECTIVE_GATE_ASSISTS",
        "model": "qwen2.5-coder-7b",
        "conditions": CONDITIONS,
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
    receipt_path = RECEIPTS_DIR / f"morphsat_v81_selective_{ts}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, default=str))
    print(f"\n  Receipt: {receipt_path}")
    print(f"  Wall time: {wall_total:.1f}s ({wall_total/60:.1f}m)")

    return receipt


def main():
    parser = argparse.ArgumentParser(
        description="MorphSAT v8.1 Selective Gate Assists")
    parser.add_argument("--port", type=int, default=8085)
    args = parser.parse_args()

    print("MorphSAT v8.1 Selective Gate Assists Experiment")
    print(f"  Port: {args.port}")
    print(f"  Model: Qwen2.5-Coder-7B Q4_K_M")
    print(f"  Conditions: {', '.join(CONDITIONS)}")
    print(f"  Scenarios: {len(BENCHMARK_SCENARIOS)}")
    print(f"  Target: overall>=92.5%, suspicious>=75%, escalate>=94.4%")
    print()

    run_experiment(port=args.port)


if __name__ == "__main__":
    main()
