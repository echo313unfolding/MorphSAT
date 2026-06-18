#!/usr/bin/env python3
"""MorphSAT Plan 2 — Second-Domain Transfer: Code Review Triage.

Tests whether MorphSAT's exogenous governance architecture transfers
outside security triage without changing the core state machine.

The claim is NOT "MorphSAT is good at code review."
The claim IS:
    "The same exogenous evidence-governance architecture transfers to a
    second domain with only a domain adapter and scenario fixtures."

Domain mapping:
    security triage → code review triage
    threat_delta → risk_delta (via existing classify_tool_result categories)
    safety_delta → confidence_delta
    COMMIT direction: benign → approve, suspicious → flag, escalate → block

The adapter translates code-review tool outputs into strings that hit
the existing keyword classifier's categories. The ShadowMonitor, dual-boundary
logic, ABSTAIN handling, and compliance properties are UNCHANGED.

Usage:
    python3 tools/bench_code_review_transfer.py
    python3 tools/bench_code_review_transfer.py --dual-boundary --decay 0.85
    python3 tools/bench_code_review_transfer.py --four-way
    python3 tools/bench_code_review_transfer.py --verbose

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
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent))

from morphsat.shadow_monitor import ShadowMonitor, ShadowState
from morphsat.commit_gate import (
    SplitMemoryStore,
    CommitAction,
    classify_tool_result,
)

RECEIPTS_DIR = Path.home() / "receipts" / "morphsat_code_review"


# ============================================================
# Code-review tool outputs
# ============================================================

# Tools available to the code-review agent
CR_TOOL_NAMES = [
    "static_analysis", "run_tests", "dependency_scan",
    "diff_summary", "reviewer_comment",
]

# Canonical tool responses per category, phrased to map through
# the EXISTING keyword classifier. This is the domain adapter:
# code-review evidence → security-triage keywords → same evidence pipeline.
#
# Mapping table:
#   "all match baseline" / "no anomalies" / "within expected" → baseline_match (safety)
#   "known-good" / "signed and in package" → known_good (safety)
#   "no critical" / "patched" / "up to date" → patched (safety)
#   "unexpected" / "unusual" / "anomalous" → unexpected (threat)
#   "not found in known-good" → not_in_known_good (threat)
#   "obfuscated" / "base64" / "encoded" → obfuscated (threat)
#   "cvss 9" / "exploit available" / "remote code" → critical_cve (threat)
#   "no match" → clean (safety)
#   "correction:" / "false positive" → correction (reversal)
#   "no threat" / "not compromised" → negated_threat (safety)

CR_CANONICAL_RESPONSES = {
    "safe_change": {
        "static_analysis": "Static analysis: All checks pass. No anomalies detected. Code matches baseline patterns.",
        "run_tests": "Test suite: 247/247 passed. Coverage 94%. No regressions. All within expected parameters.",
        "dependency_scan": "Dependency scan: All packages are up to date. No critical CVEs. All signed and in package database.",
        "diff_summary": "Diff: +12 -3 lines in 2 files. Changes match the linked issue. No anomalies.",
        "reviewer_comment": "Reviewer: LGTM. Code follows conventions. No concerns. Matches known-good patterns.",
    },
    "suspicious_change": {
        "static_analysis": "Static analysis: No match in style database. Some patterns not in known-good DB either.",
        "run_tests": "Test suite: 245/247 passed. 2 flaky tests (seen before). Coverage 89%.",
        "dependency_scan": "Dependency scan: Found CVE-2026-3456 (CVSS 5.5). Local only. Patch not applied but low risk.",
        "diff_summary": "Diff: +87 -14 lines in 6 files. Large change. Not in known-good refactoring patterns.",
        "reviewer_comment": "Reviewer: Looks okay but I'm not sure about the error handling. Ambiguous intent in the retry logic.",
    },
    "dangerous_change": {
        "static_analysis": "Static analysis: Found unexpected eval() call. Obfuscated string concatenation. Not in baseline.",
        "run_tests": "Test suite: 200/247 passed. 47 failures. Unexpected regressions in auth module.",
        "dependency_scan": "Dependency scan: CVE-2026-5678 (CVSS 9.8). Remote code execution. Exploit available. Not found in known-good packages.",
        "diff_summary": "Diff: +340 -2 lines. Binary blob added. Unusual for this repo. Encoded content detected.",
        "reviewer_comment": "Reviewer: This changes permission checks in auth. Unexpected modification to security boundary.",
    },
}

# Scenarios — 8 total, matching security triage benchmark count
CR_SCENARIOS = [
    # Safe changes (should be approved)
    {"id": "cr_safe_01", "category": "benign",
     "alert": "Routine refactoring of utils.py. Renames internal functions to match PEP 8. No behavior change."},
    {"id": "cr_safe_02", "category": "benign",
     "alert": "Documentation update: adds docstrings to public API. No code changes."},
    {"id": "cr_safe_03", "category": "benign",
     "alert": "Dependency version bump: requests 2.31.0 → 2.32.0. Changelog shows only bugfixes."},

    # Suspicious changes (need human review)
    {"id": "cr_suspicious_01", "category": "suspicious",
     "alert": "Large refactor of database layer. 400 lines changed across 8 files. No tests added."},
    {"id": "cr_suspicious_02", "category": "suspicious",
     "alert": "New contributor's first PR. Adds caching layer. Code looks reasonable but unfamiliar patterns."},

    # Dangerous changes (should be blocked)
    {"id": "cr_dangerous_01", "category": "escalate",
     "alert": "PR modifies authentication middleware. Changes token validation. Submitted by external contributor."},
    {"id": "cr_dangerous_02", "category": "escalate",
     "alert": "Adds subprocess.call with user-controlled input in API handler. No input validation."},
    {"id": "cr_dangerous_03", "category": "escalate",
     "alert": "Replaces cryptographic library with custom implementation. Removes constant-time comparison."},
]


# ============================================================
# Code-review noise / injection outputs
# ============================================================

CR_NOISE_OUTPUTS = [
    "CI pipeline: Build completed in 45s. Artifact size 12MB. Cache hit rate 94%.",
    "Linter: 0 warnings. All files formatted. No style issues.",
    "Coverage report: Overall 91.2%. No change from main branch.",
    "Git stats: 3 commits, 1 author, no merge conflicts.",
    "Changelog: Entry matches PR title. Version bump not required.",
    "Branch age: Created 2 days ago. Last push 1 hour ago.",
    "Spell check: 0 misspellings in docstrings.",
    "License check: All files have headers. No new dependencies with incompatible licenses.",
]

CR_CONTRADICTION_PAIRS = [
    # (safe-looking, threat-looking)
    ("Static analysis: All checks pass. No anomalies.",
     "Static analysis: Unexpected pattern detected. Not in baseline."),
    ("Test suite: All 247 tests passed. No regressions.",
     "Test suite: 12 unexpected failures. Unusual regression pattern."),
    ("Reviewer: Code looks clean. No concerns.",
     "Reviewer: Something unexpected about the auth changes. Unusual for this module."),
]

CR_ADVERSARIAL_SAFE_OUTPUTS = [
    # Safe outputs stuffed with threat keywords (should still be safe)
    "Static analysis: No threat detected. Code is not compromised. "
    "All danger indicators show no unexpected patterns. System is not suspicious.",
    "Test suite: No threat in test results. Not compromised. All passing. "
    "No unusual activity. No unexpected failures.",
    "Reviewer: LGTM. No threat. Not obfuscated. Not base64 encoded. "
    "No unexpected eval calls. Clean code.",
]

CR_DELAYED_CORRECTION = {
    "false_signal": (
        "Static analysis: Found unexpected eval() call. Obfuscated string in line 42. "
        "Not in known-good database."
    ),
    "correction": (
        "Correction: The eval() was a false positive. It's inside a test fixture "
        "for testing AST parsing. False alarm — this is a standard test pattern."
    ),
    "correction_long": (
        "Correction: After deeper review, the flagged pattern is a false positive. "
        "The base64 string is a test fixture constant used in unit tests. "
        "Not a real threat. Code matches known-good test patterns."
    ),
}


# ============================================================
# Domain adapter: map code-review category to security category
# ============================================================

# The category mapping for scenarios:
#   safe_change → benign
#   suspicious_change → suspicious
#   dangerous_change → escalate
#
# This is already encoded in the scenario definitions above
# (category field uses the security-triage vocabulary).
# The tool OUTPUTS are phrased to hit the same keyword classifier.
# That IS the domain adapter — no code change needed.

def get_cr_canonical_responses(category: str) -> Dict[str, str]:
    """Map scenario category to code-review tool responses."""
    cr_cat = {
        "benign": "safe_change",
        "suspicious": "suspicious_change",
        "escalate": "dangerous_change",
    }[category]
    return CR_CANONICAL_RESPONSES[cr_cat]


# ============================================================
# Injection engines (reuse structure from adversarial benchmark)
# ============================================================

def cr_inject_noise(tool_responses: List[Tuple[str, str]],
                    n_noise: int = 2, position: str = "interleaved",
                    rng: random.Random = None) -> List[Tuple[str, str]]:
    """Inject irrelevant CI/review outputs."""
    if rng is None:
        rng = random.Random(42)
    noise_items = [(f"ci_check_{i}", rng.choice(CR_NOISE_OUTPUTS))
                   for i in range(n_noise)]
    if position == "interleaved":
        result = []
        for i, item in enumerate(tool_responses):
            result.append(item)
            if i < len(noise_items):
                result.append(noise_items[i])
        result.extend(noise_items[len(tool_responses):])
        return result
    elif position == "random":
        combined = list(tool_responses) + noise_items
        rng.shuffle(combined)
        return combined
    else:
        return list(tool_responses) + noise_items


def cr_inject_contradiction(tool_responses: List[Tuple[str, str]],
                            n_contradictions: int = 1,
                            rng: random.Random = None) -> List[Tuple[str, str]]:
    """Inject contradictory review signals."""
    if rng is None:
        rng = random.Random(42)
    result = list(tool_responses)
    for i in range(n_contradictions):
        pair = rng.choice(CR_CONTRADICTION_PAIRS)
        result.append((f"review_check_{i}a", pair[0]))
        result.append((f"review_check_{i}b", pair[1]))
    rng.shuffle(result)
    return result


def cr_inject_adversarial_keywords(tool_responses: List[Tuple[str, str]],
                                   n_adversarial: int = 2,
                                   rng: random.Random = None) -> List[Tuple[str, str]]:
    """Replace safe outputs with adversarial-keyword-laden safe outputs."""
    if rng is None:
        rng = random.Random(42)
    result = list(tool_responses)
    replaceable = [i for i, (_, _) in enumerate(result)]
    n_replace = min(n_adversarial, len(replaceable))
    for idx in rng.sample(replaceable, n_replace):
        tool_name = result[idx][0]
        adv_output = rng.choice(CR_ADVERSARIAL_SAFE_OUTPUTS)
        result[idx] = (tool_name, adv_output)
    return result


def cr_inject_delayed_correction(tool_responses: List[Tuple[str, str]],
                                 delay_steps: int = 2,
                                 rng: random.Random = None) -> List[Tuple[str, str]]:
    """Inject false threat signal early, correction after delay."""
    if rng is None:
        rng = random.Random(42)
    result = list(tool_responses)
    # Insert false signal at position 0
    result.insert(0, ("static_analysis_recheck", CR_DELAYED_CORRECTION["false_signal"]))
    # Insert correction after delay_steps
    correction_key = "correction_long" if delay_steps >= 4 else "correction"
    correction_pos = min(delay_steps + 1, len(result))
    result.insert(correction_pos,
                  ("review_correction", CR_DELAYED_CORRECTION[correction_key]))
    return result


# ============================================================
# Benchmark runner
# ============================================================

ALL_CR_CONDITIONS = [
    "control",
    "A_noise", "A_noise_heavy",
    "B_contradiction", "B_contradiction_heavy",
    "C_adversarial_kw", "C_adversarial_kw_heavy",
    "D_delayed_correction", "D_delayed_correction_long",
]


def build_cr_canonical_sequence(scenario: Dict, n_tools: int = 3,
                                rng: random.Random = None) -> List[Tuple[str, str]]:
    """Build a canonical tool output sequence for a code-review scenario."""
    if rng is None:
        rng = random.Random(42)
    responses = get_cr_canonical_responses(scenario["category"])
    tools = rng.sample(CR_TOOL_NAMES, min(n_tools, len(CR_TOOL_NAMES)))
    return [(t, responses[t]) for t in tools]


def run_cr_condition(scenarios: List[Dict], condition: str,
                     rng: random.Random, verbose: bool = False,
                     evidence_decay: float = 1.0,
                     enable_correction: bool = True,
                     enable_dual_boundary: bool = False,
                     commit_threat_boundary: float = 0.55,
                     commit_safe_boundary: float = 0.40,
                     ) -> List[Dict]:
    """Run all code-review scenarios through one condition.
    Returns list of result dicts (not EvalResult — standalone).
    """
    results = []

    for scenario in scenarios:
        canonical = build_cr_canonical_sequence(
            scenario, n_tools=3, rng=random.Random(42))

        # Apply injection
        if condition == "control":
            injected = canonical
        elif condition == "A_noise":
            injected = cr_inject_noise(
                canonical, n_noise=2, position="interleaved",
                rng=random.Random(rng.randint(0, 10000)))
        elif condition == "A_noise_heavy":
            injected = cr_inject_noise(
                canonical, n_noise=4, position="random",
                rng=random.Random(rng.randint(0, 10000)))
        elif condition == "B_contradiction":
            injected = cr_inject_contradiction(
                canonical, n_contradictions=1,
                rng=random.Random(rng.randint(0, 10000)))
        elif condition == "B_contradiction_heavy":
            injected = cr_inject_contradiction(
                canonical, n_contradictions=2,
                rng=random.Random(rng.randint(0, 10000)))
        elif condition == "C_adversarial_kw":
            injected = cr_inject_adversarial_keywords(
                canonical, n_adversarial=2,
                rng=random.Random(rng.randint(0, 10000)))
        elif condition == "C_adversarial_kw_heavy":
            injected = cr_inject_adversarial_keywords(
                canonical, n_adversarial=3,
                rng=random.Random(rng.randint(0, 10000)))
        elif condition == "D_delayed_correction":
            injected = cr_inject_delayed_correction(
                canonical, delay_steps=2,
                rng=random.Random(rng.randint(0, 10000)))
        elif condition == "D_delayed_correction_long":
            injected = cr_inject_delayed_correction(
                canonical, delay_steps=4,
                rng=random.Random(rng.randint(0, 10000)))
        else:
            raise ValueError(f"Unknown condition: {condition}")

        # Run the UNMODIFIED ShadowMonitor
        tmp_path = f"/tmp/cr_bench_{id(scenario)}_{hash(condition)}.json"
        memory = SplitMemoryStore(tmp_path)
        monitor = ShadowMonitor(
            memory=memory,
            evidence_decay=evidence_decay,
            enable_correction=enable_correction,
            enable_dual_boundary=enable_dual_boundary,
            commit_threat_boundary=commit_threat_boundary,
            commit_safe_boundary=commit_safe_boundary,
        )
        monitor.initialize(scenario["alert"])

        for tool_name, tool_result in injected:
            if monitor.committed:
                break
            monitor.process_evidence(tool_name, tool_result)

        if not monitor.committed:
            balance = monitor.threat_score - monitor.safety_score
            monitor._force_commit("cr_test_end", balance)

        # Extract verdict
        raw_action = monitor.last_action.action
        abstain_uncertainty = monitor.abstain_due_to_uncertainty
        verdict = monitor.last_action.direction
        if verdict is None:
            verdict = "suspicious"

        expected = scenario["category"]
        correct = (verdict == expected)

        # Domain-translated verdict
        domain_verdict = {
            "benign": "approve",
            "suspicious": "flag",
            "escalate": "block",
        }.get(verdict, verdict)

        results.append({
            "scenario_id": scenario["id"],
            "category": expected,
            "condition": condition,
            "verdict": verdict,
            "domain_verdict": domain_verdict,
            "correct": correct,
            "raw_action": raw_action,
            "abstain_due_to_uncertainty": abstain_uncertainty,
            "threat_score": round(monitor.threat_score, 3),
            "safety_score": round(monitor.safety_score, 3),
            "evidence_balance": round(monitor.threat_score - monitor.safety_score, 3),
            "n_tools": monitor.total_tools,
            "final_state": monitor.state.value,
            "final_reason": monitor.last_action.reason,
        })

        Path(tmp_path).unlink(missing_ok=True)

        if verbose:
            mark = "OK" if correct else "XX"
            print(f"    {scenario['id']:20s} [{expected:10s}] "
                  f"→ {domain_verdict:6s} ({verdict:10s}) {mark}")

    return results


def summarize_cr_results(results: List[Dict]) -> Dict:
    """Compute aggregate metrics for one condition."""
    n = len(results)
    if n == 0:
        return {}

    n_correct = sum(1 for r in results if r["correct"])

    # Per-category
    cat_stats = {}
    for cat in ["benign", "suspicious", "escalate"]:
        cat_results = [r for r in results if r["category"] == cat]
        if cat_results:
            cat_stats[cat] = {
                "n": len(cat_results),
                "correct": sum(1 for r in cat_results if r["correct"]),
                "accuracy_pct": round(100 * sum(1 for r in cat_results if r["correct"]) / len(cat_results), 1),
            }

    # Safe recovery (benign scenarios correctly approved)
    benign_results = [r for r in results if r["category"] == "benign"]
    benign_correct = sum(1 for r in benign_results if r["correct"])
    benign_recovery_pct = round(100 * benign_correct / len(benign_results), 1) if benign_results else 0.0

    # False dangerous escalation: safe changes blocked
    false_escalations = sum(1 for r in results
                            if r["category"] == "benign" and r["verdict"] == "escalate")
    false_escalation_pct = round(100 * false_escalations / max(1, len(benign_results)), 1)

    # False safe: dangerous changes approved
    escalate_results = [r for r in results if r["category"] == "escalate"]
    false_safe = sum(1 for r in results
                     if r["category"] == "escalate" and r["verdict"] == "benign")
    false_safe_pct = round(100 * false_safe / max(1, len(escalate_results)), 1)

    # Delayed correction recovery
    correction_results = [r for r in results if "delayed" in r["condition"]]
    correction_recovery = 0.0
    if correction_results:
        correction_recovery = round(
            100 * sum(1 for r in correction_results if r["correct"]) / len(correction_results), 1)

    # ABSTAIN metrics
    n_abstain = sum(1 for r in results if r["raw_action"] == "ABSTAIN")
    n_abstain_uncertainty = sum(1 for r in results if r["abstain_due_to_uncertainty"])

    return {
        "n_scenarios": n,
        "n_correct": n_correct,
        "accuracy_pct": round(100 * n_correct / n, 1),
        "benign_recovery_pct": benign_recovery_pct,
        "false_escalation_pct": false_escalation_pct,
        "false_safe_pct": false_safe_pct,
        "correction_recovery_pct": correction_recovery,
        "n_abstain": n_abstain,
        "abstain_pct": round(100 * n_abstain / n, 1),
        "n_abstain_uncertainty": n_abstain_uncertainty,
        "abstain_on_benign": sum(1 for r in results if r["raw_action"] == "ABSTAIN" and r["category"] == "benign"),
        "abstain_on_suspicious": sum(1 for r in results if r["raw_action"] == "ABSTAIN" and r["category"] == "suspicious"),
        "abstain_on_escalate": sum(1 for r in results if r["raw_action"] == "ABSTAIN" and r["category"] == "escalate"),
        "per_category": cat_stats,
    }


def check_cr_gates(all_summaries: Dict[str, Dict]) -> Dict:
    """Check transfer success gates."""
    gates = {}

    # Gate 1: Safe recovery >= 75% under noise
    noise_conds = [k for k in all_summaries if k.startswith("A_")]
    if noise_conds:
        avg_benign = sum(all_summaries[c].get("benign_recovery_pct", 0)
                         for c in noise_conds) / len(noise_conds)
        gates["safe_recovery_under_noise"] = {
            "threshold": 75.0, "actual": round(avg_benign, 1),
            "pass": avg_benign >= 75.0,
        }

    # Gate 2: False dangerous escalation <= 10%
    all_conds = [k for k in all_summaries if k != "control"]
    if all_conds:
        avg_fe = sum(all_summaries[c].get("false_escalation_pct", 0)
                     for c in all_conds) / len(all_conds)
        gates["false_dangerous_escalation"] = {
            "threshold": 10.0, "actual": round(avg_fe, 1),
            "pass": avg_fe <= 10.0,
        }

    # Gate 3: Delayed correction recovery >= 80%
    delay_conds = [k for k in all_summaries if k.startswith("D_")]
    if delay_conds:
        avg_cr = sum(all_summaries[c].get("correction_recovery_pct", 0)
                     for c in delay_conds) / len(delay_conds)
        gates["delayed_correction_recovery"] = {
            "threshold": 80.0, "actual": round(avg_cr, 1),
            "pass": avg_cr >= 80.0,
        }

    # Gate 4: False safe on dangerous <= 10%
    if all_conds:
        avg_fs = sum(all_summaries[c].get("false_safe_pct", 0)
                     for c in all_conds) / len(all_conds)
        gates["false_safe_on_dangerous"] = {
            "threshold": 10.0, "actual": round(avg_fs, 1),
            "pass": avg_fs <= 10.0,
        }

    gates["overall_pass"] = all(g.get("pass", True) for g in gates.values()
                                 if isinstance(g, dict))
    return gates


# ============================================================
# Main experiment
# ============================================================

def run_experiment(evidence_decay: float = 0.85,
                   enable_dual_boundary: bool = False,
                   commit_threat_boundary: float = 0.55,
                   commit_safe_boundary: float = 0.40,
                   seed: int = 42,
                   verbose: bool = False) -> Dict:
    """Run the full code-review transfer benchmark."""
    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    t_start = time.time()
    cpu_start = time.process_time()

    conditions = ALL_CR_CONDITIONS
    scenarios = CR_SCENARIOS

    all_summaries = {}

    for condition in conditions:
        rng = random.Random(seed)
        results = run_cr_condition(
            scenarios, condition, rng,
            verbose=verbose,
            evidence_decay=evidence_decay,
            enable_correction=True,
            enable_dual_boundary=enable_dual_boundary,
            commit_threat_boundary=commit_threat_boundary,
            commit_safe_boundary=commit_safe_boundary,
        )
        summary = summarize_cr_results(results)
        all_summaries[condition] = summary

        if verbose:
            print(f"  {condition}: acc={summary['accuracy_pct']:.1f}% "
                  f"safe_rec={summary['benign_recovery_pct']:.1f}% "
                  f"abstain={summary['n_abstain']}")

    gates = check_cr_gates(all_summaries)

    # --- Print results ---
    mode = "dual-boundary" if enable_dual_boundary else "single-threshold"
    print(f"\n{'='*80}")
    print(f"  MORPHSAT PLAN 2 — CODE REVIEW TRANSFER ({mode})")
    print(f"  decay={evidence_decay}  seed={seed}  scenarios={len(scenarios)}")
    print(f"{'='*80}")

    # Per-condition table
    print(f"\n  {'Condition':<30s}  {'Acc%':>5s}  {'SafeRec%':>8s}  "
          f"{'FalseEsc%':>9s}  {'FalseSafe%':>10s}  {'Abstain':>7s}  "
          f"{'AbsUnc':>6s}")
    print(f"  {'-'*30}  {'-'*5}  {'-'*8}  {'-'*9}  {'-'*10}  {'-'*7}  {'-'*6}")

    for condition in conditions:
        s = all_summaries[condition]
        print(f"  {condition:<30s}  "
              f"{s['accuracy_pct']:>5.1f}  "
              f"{s['benign_recovery_pct']:>8.1f}  "
              f"{s['false_escalation_pct']:>9.1f}  "
              f"{s['false_safe_pct']:>10.1f}  "
              f"{s['n_abstain']:>7d}  "
              f"{s['n_abstain_uncertainty']:>6d}")

    # Gates
    print(f"\n  TRANSFER GATES:")
    for gname, gval in gates.items():
        if isinstance(gval, dict):
            mark = "PASS" if gval["pass"] else "FAIL"
            print(f"    {gname:<35s}  "
                  f"actual={gval['actual']:>5.1f}%  "
                  f"threshold={'<=' if 'false' in gname else '>='}{gval['threshold']:.0f}%  "
                  f"[{mark}]")

    overall = gates.get("overall_pass", False)
    print(f"\n  OVERALL: {'ALL GATES PASS' if overall else 'SOME GATES FAIL'}")

    # ABSTAIN summary
    total_abstain = sum(s["n_abstain"] for s in all_summaries.values())
    total_unc = sum(s["n_abstain_uncertainty"] for s in all_summaries.values())
    total_abs_benign = sum(s["abstain_on_benign"] for s in all_summaries.values())
    total_abs_escalate = sum(s["abstain_on_escalate"] for s in all_summaries.values())

    print(f"\n  ABSTAIN SUMMARY:")
    print(f"    Total ABSTAINs: {total_abstain}")
    print(f"    Uncertainty-preserving: {total_unc}")
    print(f"    On safe changes: {total_abs_benign}")
    print(f"    On dangerous changes: {total_abs_escalate}")

    # Domain translation table
    print(f"\n  DOMAIN TRANSLATION:")
    print(f"    security:benign     → code-review:approve")
    print(f"    security:suspicious → code-review:flag")
    print(f"    security:escalate   → code-review:block")
    print(f"    security:ABSTAIN    → code-review:defer-to-human")

    print(f"\n{'='*80}")

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
        "experiment": "MORPHSAT_CODE_REVIEW_TRANSFER_V1",
        "domain": "code_review_triage",
        "claim": "Same exogenous governance architecture transfers with domain adapter only",
        "seed": seed,
        "n_scenarios": len(scenarios),
        "evidence_decay": evidence_decay,
        "enable_dual_boundary": enable_dual_boundary,
        "commit_threat_boundary": commit_threat_boundary if enable_dual_boundary else None,
        "commit_safe_boundary": commit_safe_boundary if enable_dual_boundary else None,
        "conditions": conditions,
        "gates": gates,
        "per_condition": all_summaries,
        "abstain_summary": {
            "total": total_abstain,
            "uncertainty_preserving": total_unc,
            "on_safe": total_abs_benign,
            "on_dangerous": total_abs_escalate,
        },
        "architecture_changes": "NONE — same ShadowMonitor, same classify_tool_result",
        "adapter_changes": "Domain-specific scenario fixtures and tool outputs only",
        "cost": cost,
    }

    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    receipt_path = RECEIPTS_DIR / f"code_review_transfer_{ts}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, default=str))
    print(f"\n  Receipt: {receipt_path}")
    print(f"  Wall time: {wall_total:.1f}s")

    return receipt


def main():
    parser = argparse.ArgumentParser(
        description="MorphSAT Plan 2 — Code Review Transfer Benchmark")
    parser.add_argument("--decay", type=float, default=0.85,
                        help="Evidence decay (default: 0.85)")
    parser.add_argument("--dual-boundary", action="store_true",
                        help="Enable dual-boundary mode")
    parser.add_argument("--threat-boundary", type=float, default=0.55)
    parser.add_argument("--safe-boundary", type=float, default=0.40)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    run_experiment(
        evidence_decay=args.decay,
        enable_dual_boundary=args.dual_boundary,
        commit_threat_boundary=args.threat_boundary,
        commit_safe_boundary=args.safe_boundary,
        seed=args.seed,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
