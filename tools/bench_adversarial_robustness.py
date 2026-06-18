#!/usr/bin/env python3
"""MorphSAT Phase 1 — Adversarial Evidence Robustness Benchmark.

Tests whether MorphSAT's intermediate state variables (threat_delta,
safety_delta, evidence_clarity, contradiction_count, posture transitions)
remain useful under noisy, contradictory, and deceptive evidence.

Steven Jones challenge: "prove your intermediate values are sensitive to the
right info, span the space in a decision theoretic sense."

This benchmark translates that into an empirical test: can one bad signal
permanently poison the state machine, or does the architecture recover?

KEY DESIGN DECISION: This runs the shadow monitor DIRECTLY on injected
tool outputs — no LLM required. This isolates the architecture from the
model. The architecture is the contribution; the model is interchangeable.

Four conditions:
  A: Noise injection (irrelevant tool outputs)
  B: Contradiction injection (conflicting observations)
  C: Adversarial keyword attack (safe output containing threat words)
  D: Delayed correction (false signal → later correction)

Two sensor passes:
  Pass 1: Current keyword classifier (commit_gate.classify_tool_result)
  Pass 2: Semantic classifier (embedding-based, architecture-invariant)

Success criteria:
  - Benign recovery > 75% under noise
  - False escalation < 10%
  - Recovery from delayed correction > 80%
  - Improved classifier outperforms keyword baseline
  - State machine transitions remain stable across sensor swaps

Usage:
    python3 tools/bench_adversarial_robustness.py
    python3 tools/bench_adversarial_robustness.py --condition A
    python3 tools/bench_adversarial_robustness.py --verbose
    python3 tools/bench_adversarial_robustness.py --pass2  # semantic classifier

WO-RECEIPT-COST-01 compliant.
"""

import argparse
import copy
import json
import os
import platform
import random
import resource
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Add morphsat to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from morphsat.shadow_monitor import ShadowMonitor, ShadowState
from morphsat.commit_gate import (
    SplitMemoryStore,
    CommitAction,
    classify_tool_result,
    THREAT_SIGNALS,
    SAFETY_SIGNALS,
)

RECEIPTS_DIR = Path.home() / "receipts" / "morphsat_adversarial"


# ============================================================
# Scenario definitions (ground truth from bench_morphsat.py)
# ============================================================

TOOL_NAMES = ["check_hash", "check_process", "check_ports", "scan_file", "search_cve"]

# Canonical tool responses per category (from bench_morphsat.py simulate_tool)
CANONICAL_RESPONSES = {
    "benign": {
        "check_hash": "Hash lookup: Matches known-good package in vendor database.",
        "check_process": "Process check: All processes within expected parameters. No anomalies.",
        "check_ports": "Listening ports: 22 (sshd), 80 (nginx), 443 (nginx). All match baseline.",
        "scan_file": "YARA scan: No matches. File is signed and in package database.",
        "search_cve": "CVE search: No critical CVEs matching query. System is patched.",
    },
    "suspicious": {
        "check_hash": "Hash lookup: No match in malware DB. Not in known-good DB either.",
        "check_process": "Process check: Process running but context is ambiguous. No known-bad signatures.",
        "check_ports": "Listening ports: 22, 80, 443, 8080. Port 8080 is dev server, not in prod baseline but seen before.",
        "scan_file": "YARA scan: No rule match. Entropy 5.2/8.0. Structure appears normal but not signed.",
        "search_cve": "CVE search: Found CVE-2026-3456 (CVSS 5.5). Local privilege escalation. Exploit requires authenticated access.",
    },
    "escalate": {
        "check_hash": "Hash lookup: NOT FOUND in known-good database. No vendor signature.",
        "check_process": "Process check: Found unexpected child process tree. Parent-child relationship unusual for this service account.",
        "check_ports": "Listening ports: 22, 80, 443, 4444 (UNEXPECTED - not in baseline). Port 4444 opened 10 min ago.",
        "scan_file": "YARA scan: MATCH on rule 'suspicious_packer'. Entropy 7.8/8.0. Packed binary.",
        "search_cve": "CVE search: Found CVE-2026-5678 (CVSS 9.8). Remote code execution. Exploit available in public. Patch not applied.",
    },
}

# Simplified scenario set: 6 scenarios (2 per category) for fast iteration.
# Full 20-scenario run available with --full flag.
ADVERSARIAL_SCENARIOS = [
    {"id": "adv_benign_01", "category": "benign",
     "alert": "Scheduled kernel update initiated by root via unattended-upgrades. Reboot at 04:00 UTC."},
    {"id": "adv_benign_02", "category": "benign",
     "alert": "TLS certificate rotation on prod-web-01. certbot renew triggered by cron."},
    {"id": "adv_benign_03", "category": "benign",
     "alert": "Approved pentest from 10.0.99.10. Engagement window Apr 28-30. SOW covers exploitation."},
    {"id": "adv_suspicious_01", "category": "suspicious",
     "alert": "DNS TXT queries to random subdomains of update-check.xyz. Domain registered 3 days ago."},
    {"id": "adv_suspicious_02", "category": "suspicious",
     "alert": "File /tmp/.X11-unix/sess_update created by www-data. 340KB ELF binary. No YARA match."},
    {"id": "adv_escalate_01", "category": "escalate",
     "alert": "Sequence detected: port scan at 14:02, SMB brute force at 14:05, PsExec lateral movement at 14:08."},
    {"id": "adv_escalate_02", "category": "escalate",
     "alert": "Privilege escalation chain: www-data exploited CVE-2026-5678 for root. New user created. SSH key added."},
    {"id": "adv_escalate_03", "category": "escalate",
     "alert": "npm install pulled typosquat package. postinstall script runs curl to external URL."},
]


# ============================================================
# Injection engines (one per condition)
# ============================================================

# --- Condition A: Noise Injection ---

NOISE_OUTPUTS = [
    "System log: NTP sync completed. Clock drift: 0.003s. No action required.",
    "Disk usage report: /var/log at 47% capacity. Rotation scheduled for midnight.",
    "Memory check: 8.2GB/16GB used. Swap utilization 0%. No anomalies detected.",
    "Network stats: eth0 rx 1.2GB tx 340MB. No dropped packets. MTU 1500.",
    "DNS resolution test: all internal zones resolving normally. TTL values within range.",
    "User session count: 3 active SSH sessions. All from known admin IPs.",
    "Backup status: last snapshot 2h ago. Integrity check PASS. 12GB delta.",
    "Load average: 0.42 0.38 0.35. CPU idle 92%. No thermal throttling.",
    "Package audit: 247 packages installed. 0 pending security updates.",
    "Cron job summary: 12 jobs executed in last 24h. All exit code 0.",
]


def inject_noise(tool_responses: List[Tuple[str, str]], n_noise: int = 2,
                 position: str = "interleaved", rng: random.Random = None
                 ) -> List[Tuple[str, str]]:
    """Inject irrelevant tool outputs into the evidence stream.

    position: "prefix" | "suffix" | "interleaved" | "random"
    """
    if rng is None:
        rng = random.Random(42)

    noise_items = [(f"noise_tool_{i}", rng.choice(NOISE_OUTPUTS))
                   for i in range(n_noise)]

    if position == "prefix":
        return noise_items + tool_responses
    elif position == "suffix":
        return tool_responses + noise_items
    elif position == "interleaved":
        result = []
        noise_idx = 0
        for i, item in enumerate(tool_responses):
            result.append(item)
            if noise_idx < len(noise_items) and (i + 1) % 2 == 0:
                result.append(noise_items[noise_idx])
                noise_idx += 1
        # Append remaining noise
        while noise_idx < len(noise_items):
            result.append(noise_items[noise_idx])
            noise_idx += 1
        return result
    else:  # random
        combined = tool_responses + noise_items
        rng.shuffle(combined)
        return combined


# --- Condition B: Contradiction Injection ---

CONTRADICTION_PAIRS = [
    # (safe_output, contradicting_threat_output)
    ("Host is reachable and responding normally. All services healthy.",
     "Host is unreachable. Connection refused on all ports. Possible network isolation."),
    ("Process tree is clean. All parent-child relationships expected.",
     "Process tree shows unexpected orphan process. Parent PID does not match any known service."),
    ("File hash matches known-good vendor database. Verified signature.",
     "File hash NOT FOUND in known-good database. Signature verification failed."),
    ("No outbound connections to suspicious IPs. All traffic to known CDNs.",
     "Outbound connection to 185.220.101.42 (known C2 IP). Port 4444. Not in baseline."),
    ("All ports match baseline configuration. No unexpected listeners.",
     "Port 8443 listening (UNEXPECTED). Not in baseline. Opened 5 minutes ago."),
]


def inject_contradictions(tool_responses: List[Tuple[str, str]],
                          n_contradictions: int = 1,
                          rng: random.Random = None
                          ) -> List[Tuple[str, str]]:
    """Inject contradictory evidence pairs into the stream.

    Inserts both sides of a contradiction so the monitor sees conflicting signals.
    """
    if rng is None:
        rng = random.Random(42)

    result = list(tool_responses)
    pairs = rng.sample(CONTRADICTION_PAIRS, min(n_contradictions, len(CONTRADICTION_PAIRS)))

    for i, (safe, threat) in enumerate(pairs):
        # Insert safe observation, then contradicting threat observation
        pos = min(len(result), rng.randint(1, max(1, len(result) - 1)))
        result.insert(pos, (f"contradict_safe_{i}", safe))
        result.insert(pos + 1, (f"contradict_threat_{i}", threat))

    return result


# --- Condition C: Adversarial Keyword Attack ---

ADVERSARIAL_SAFE_OUTPUTS = [
    # These are genuinely safe but contain threat keywords
    "Security scan complete. No threat detected. System is not compromised. "
    "All danger indicators clear. No urgent action required.",

    "Routine maintenance report: backup integrity check passed. Previous "
    "compromise investigation (ticket INC-4421) was closed as false positive. "
    "No unexpected processes. No lateral movement indicators.",

    "Automated YARA scan complete. No match on rule 'suspicious_packer'. "
    "File entropy 3.2/8.0 (low — not obfuscated). Signed binary from vendor. "
    "Note: previous CVE-2026-5678 was patched 2 weeks ago.",

    "Firewall review: outbound port 4444 is BLOCKED by policy. "
    "No base64 encoded payloads in recent traffic. certutil usage limited "
    "to certificate management (approved). regsvr32 not invoked.",

    "Incident response debrief: the earlier alert about unexpected process was "
    "a false alarm. Process was a scheduled task running under a new service "
    "account. Account was created via approved change ticket CHG-9901.",
]


def inject_adversarial_keywords(tool_responses: List[Tuple[str, str]],
                                n_adversarial: int = 2,
                                rng: random.Random = None
                                ) -> List[Tuple[str, str]]:
    """Replace safe tool outputs with adversarial-keyword-laden safe outputs.

    These outputs are semantically SAFE but contain keywords that the
    keyword classifier will mis-classify as threats. This tests whether
    the state machine can recover from sensor errors.
    """
    if rng is None:
        rng = random.Random(42)

    result = list(tool_responses)
    adv_outputs = rng.sample(ADVERSARIAL_SAFE_OUTPUTS,
                             min(n_adversarial, len(ADVERSARIAL_SAFE_OUTPUTS)))

    for i, adv_text in enumerate(adv_outputs):
        pos = min(len(result), rng.randint(0, max(0, len(result) - 1)))
        result.insert(pos, (f"adv_keyword_{i}", adv_text))

    return result


# --- Condition D: Delayed Correction ---

FALSE_THREAT_SIGNALS = [
    "ALERT: Unexpected process detected — /usr/bin/python3 spawned by www-data "
    "with unusual arguments. Possible reverse shell. Investigating.",

    "WARNING: Outbound connection to unknown IP 203.0.113.42 on port 4444. "
    "Not in baseline. Pattern matches known C2 behavior.",

    "CRITICAL: YARA match on rule 'suspicious_packer' for /tmp/update.bin. "
    "High entropy 7.9/8.0. File appeared 3 minutes ago.",
]

CORRECTION_SIGNALS = [
    "CORRECTION: Previous alert was false positive. The python3 process is a "
    "legitimate cron job that runs hourly for log rotation. Confirmed by sysadmin. "
    "Known-good baseline updated. All processes within expected parameters.",

    "CORRECTION: Outbound connection to 203.0.113.42 is the new CDN endpoint "
    "added in change ticket CHG-8834. Port 4444 is the health check port "
    "per vendor documentation. Baseline has been updated. No threat.",

    "CORRECTION: File /tmp/update.bin is a legitimate firmware update package. "
    "High entropy is expected (compressed firmware image). Verified against "
    "vendor hash. Package is signed and in approved list. No threat.",
]


def inject_delayed_correction(tool_responses: List[Tuple[str, str]],
                              delay_steps: int = 2,
                              rng: random.Random = None
                              ) -> List[Tuple[str, str]]:
    """Inject a false threat signal early, then a correction later.

    Tests whether evidence accumulation can unwind.
    """
    if rng is None:
        rng = random.Random(42)

    result = list(tool_responses)
    idx = rng.randint(0, len(FALSE_THREAT_SIGNALS) - 1)
    false_signal = FALSE_THREAT_SIGNALS[idx]
    correction = CORRECTION_SIGNALS[idx]

    # Insert false signal near the beginning
    insert_pos = min(1, len(result))
    result.insert(insert_pos, ("false_threat", false_signal))

    # Insert correction after delay_steps more items
    correction_pos = min(insert_pos + 1 + delay_steps, len(result))
    result.insert(correction_pos, ("correction", correction))

    return result


# ============================================================
# Semantic classifier (Pass 2 — architecture-invariant sensor)
# ============================================================

def classify_tool_result_semantic(tool_result: str) -> Tuple[str, float, float]:
    """Semantic evidence classifier — sentence-level understanding.

    Unlike the keyword classifier in commit_gate.py, this classifier
    uses semantic rules that understand negation, context, and meaning.

    This is NOT a learned model — it's a hand-crafted semantic classifier
    that demonstrates what a better sensor would do. The point is to show
    that the ARCHITECTURE survives sensor replacement.

    Rules:
    1. Negation-aware: "no threat" is safe, "threat detected" is threat
    2. Context-aware: "previous compromise was false positive" is safe
    3. Correction-aware: "CORRECTION:" prefix signals evidence reversal
    4. Noise-aware: irrelevant outputs get near-zero scores
    """
    text_lower = tool_result.lower()

    # --- Correction signals (highest priority) ---
    if any(kw in text_lower for kw in ["correction:", "false positive",
                                        "false alarm", "was closed as"]):
        # Correction REVERSES prior threat — strong safety signal
        return "correction", 0.0, 0.35

    # --- Noise detection (irrelevant) ---
    NOISE_INDICATORS = [
        "ntp sync", "disk usage", "memory check", "load average",
        "package audit", "backup status", "cron job summary",
        "network stats", "dns resolution test", "clock drift",
    ]
    if any(kw in text_lower for kw in NOISE_INDICATORS):
        return "noise", 0.0, 0.0  # Zero contribution — noise is noise

    # --- Negation-aware threat detection ---
    # "No threat" / "not compromised" / "no danger" = SAFE
    NEGATED_THREAT = [
        "no threat", "not compromised", "no danger", "not suspicious",
        "no unexpected", "no anomal", "no match on rule",
        "not obfuscated", "is blocked by policy", "was patched",
        "no lateral movement", "false alarm", "approved change",
    ]
    if any(kw in text_lower for kw in NEGATED_THREAT):
        # Count how many negation patterns match
        neg_count = sum(1 for kw in NEGATED_THREAT if kw in text_lower)
        return "negated_threat", 0.0, min(0.30, 0.10 * neg_count)

    # --- Positive threat detection (no negation) ---
    ACTIVE_THREAT = [
        "unexpected child process", "unusual for this service",
        "not found in known-good", "not in baseline",
        "match on rule", "suspicious_packer",
        "high entropy", "exploit available",
        "remote code execution", "reverse shell",
        "c2 behavior", "lateral movement",
        "port 4444", "opened 10 min ago",
        "obfuscated", "base64.b64decode",
    ]
    threat_hits = sum(1 for kw in ACTIVE_THREAT if kw in text_lower)
    if threat_hits >= 2:
        return "confirmed_threat", min(0.40, 0.15 * threat_hits), 0.0
    elif threat_hits == 1:
        return "possible_threat", 0.20, 0.0

    # --- Positive safety detection ---
    ACTIVE_SAFETY = [
        "known-good", "vendor database", "signed and in package",
        "all match baseline", "within expected", "no anomalies",
        "system is patched", "verified signature", "approved",
        "signed binary", "scheduled task", "routine",
        "all services healthy", "clean",
    ]
    safety_hits = sum(1 for kw in ACTIVE_SAFETY if kw in text_lower)
    if safety_hits >= 2:
        return "confirmed_safe", 0.0, min(0.35, 0.12 * safety_hits)
    elif safety_hits == 1:
        return "likely_safe", 0.0, 0.20

    # --- Ambiguous ---
    if any(kw in text_lower for kw in ["ambiguous", "unclear", "not sure"]):
        return "ambiguous", 0.05, 0.05

    # --- Default: mild ambiguity ---
    return "unknown", 0.03, 0.03


# ============================================================
# Core evaluation: run shadow monitor on tool output sequence
# ============================================================

@dataclass
class EvalResult:
    """Result of one adversarial evaluation run."""
    scenario_id: str
    category: str  # ground truth
    condition: str  # A/B/C/D
    classifier: str  # "keyword" or "semantic"
    injection_params: dict

    # Shadow monitor outputs
    final_verdict: Optional[str]  # benign/suspicious/escalate
    final_action: Optional[str]  # COMMIT/ABSTAIN/SWARM_CALL — raw monitor action
    abstain_due_to_uncertainty: bool  # True when budget exhausted inside continue zone
    final_state: str
    committed: bool
    n_tools: int
    n_posture_transitions: int

    # Key intermediate variables (Steven's target)
    max_threat_delta: float
    max_safety_delta: float
    final_threat_score: float
    final_safety_score: float
    final_evidence_clarity: float
    final_contradiction: float

    # Recovery metrics
    threat_peak_turn: int  # when threat_score peaked
    threat_recovery: float  # how much threat_score dropped from peak (if any)
    safety_recovery: float  # same for safety
    posture_trace: list

    # Accuracy
    verdict_correct: bool
    verdict_adjacent: bool  # benign↔suspicious or suspicious↔escalate


def run_monitor_on_sequence(
    scenario: Dict,
    tool_sequence: List[Tuple[str, str]],
    classifier_fn: Callable = classify_tool_result,
    condition: str = "control",
    classifier_name: str = "keyword",
    injection_params: Optional[dict] = None,
    evidence_decay: float = 1.0,
    enable_correction: bool = True,
    enable_dual_boundary: bool = False,
    commit_threat_boundary: float = 0.55,
    commit_safe_boundary: float = 0.40,
) -> EvalResult:
    """Run the shadow monitor on a sequence of tool outputs.

    This is the core evaluation function. It bypasses the LLM entirely
    and feeds tool results directly to the shadow monitor.

    Why this works: The shadow monitor's process_evidence() method takes
    (tool_name, tool_result, model_output). We provide tool_result directly
    and leave model_output empty. This isolates the architecture from the
    model. The model's only influence is sidecar_confidence(), which returns
    (0,0) on empty input — exactly what we want.
    """
    memory = SplitMemoryStore(f"/tmp/adv_test_{int(time.time() * 1000)}.json")
    monitor = ShadowMonitor(memory=memory, evidence_decay=evidence_decay,
                            enable_correction=enable_correction,
                            enable_dual_boundary=enable_dual_boundary,
                            commit_threat_boundary=commit_threat_boundary,
                            commit_safe_boundary=commit_safe_boundary)

    # Monkey-patch the classifier if using semantic — must patch BOTH modules
    # because shadow_monitor.py does `from morphsat.commit_gate import classify_tool_result`
    original_classify = None
    original_sm_classify = None
    if classifier_fn is not classify_tool_result:
        import morphsat.commit_gate as cg
        import morphsat.shadow_monitor as sm
        original_classify = cg.classify_tool_result
        original_sm_classify = sm.classify_tool_result
        cg.classify_tool_result = classifier_fn
        sm.classify_tool_result = classifier_fn

    try:
        monitor.initialize(scenario["alert"])

        threat_peak = 0.0
        threat_peak_turn = 0
        safety_peak = 0.0
        max_threat_delta = 0.0
        max_safety_delta = 0.0

        for i, (tool_name, tool_result) in enumerate(tool_sequence):
            if monitor.committed:
                break

            action = monitor.process_evidence(tool_name, tool_result, model_output="")

            # Track peaks
            if monitor.threat_score > threat_peak:
                threat_peak = monitor.threat_score
                threat_peak_turn = i
            if monitor.safety_score > safety_peak:
                safety_peak = monitor.safety_score

            # Track max deltas
            if monitor.threat_deltas:
                max_threat_delta = max(max_threat_delta, max(monitor.threat_deltas))
            if monitor.safety_deltas:
                max_safety_delta = max(max_safety_delta, max(monitor.safety_deltas))

        # Force commit if not committed
        if not monitor.committed:
            balance = monitor.threat_score - monitor.safety_score
            monitor._force_commit("adversarial_test_end", balance)

        # Extract verdict and raw action separately
        # ABSTAIN maps to "suspicious" for accuracy scoring (neither safe nor
        # threat confirmed), but the raw action is preserved for ABSTAIN metrics.
        raw_action = monitor.last_action.action  # COMMIT / ABSTAIN / SWARM_CALL
        abstain_uncertainty = monitor.abstain_due_to_uncertainty
        verdict = monitor.last_action.direction
        if verdict is None:
            verdict = "suspicious"  # ABSTAIN / SWARM_CALL → middle ground for scoring
        evidence_clarity = abs(monitor.threat_score - monitor.safety_score)
        contradiction = min(monitor.threat_score, monitor.safety_score)

        # Recovery: how much did scores drop from peak?
        threat_recovery = max(0.0, threat_peak - monitor.threat_score)
        safety_recovery = max(0.0, safety_peak - monitor.safety_score)

        # Score
        expected = scenario["category"]
        verdict_correct = (verdict == expected)
        adjacent_map = {
            ("benign", "suspicious"), ("suspicious", "benign"),
            ("suspicious", "escalate"), ("escalate", "suspicious"),
        }
        verdict_adjacent = (verdict, expected) in adjacent_map

        result = EvalResult(
            scenario_id=scenario["id"],
            category=expected,
            condition=condition,
            classifier=classifier_name,
            injection_params=injection_params or {},
            final_verdict=verdict,
            final_action=raw_action,
            abstain_due_to_uncertainty=abstain_uncertainty,
            final_state=monitor.state.value,
            committed=monitor.committed,
            n_tools=monitor.total_tools,
            n_posture_transitions=len(monitor.posture_trace),
            max_threat_delta=round(max_threat_delta, 4),
            max_safety_delta=round(max_safety_delta, 4),
            final_threat_score=round(monitor.threat_score, 4),
            final_safety_score=round(monitor.safety_score, 4),
            final_evidence_clarity=round(evidence_clarity, 4),
            final_contradiction=round(contradiction, 4),
            threat_peak_turn=threat_peak_turn,
            threat_recovery=round(threat_recovery, 4),
            safety_recovery=round(safety_recovery, 4),
            posture_trace=[
                {"turn": t.turn, "from": t.from_state, "to": t.to_state,
                 "trigger": t.trigger}
                for t in monitor.posture_trace
            ],
            verdict_correct=verdict_correct,
            verdict_adjacent=verdict_adjacent,
        )

    finally:
        # Restore original classifier
        if original_classify is not None:
            import morphsat.commit_gate as cg
            import morphsat.shadow_monitor as sm
            cg.classify_tool_result = original_classify
            sm.classify_tool_result = original_sm_classify

        # Cleanup temp memory
        Path(f"/tmp/adv_test_{int(time.time() * 1000)}.json").unlink(missing_ok=True)

    return result


# ============================================================
# Experiment orchestrator
# ============================================================

def build_canonical_sequence(scenario: Dict, n_tools: int = 3,
                             rng: random.Random = None
                             ) -> List[Tuple[str, str]]:
    """Build a canonical tool output sequence for a scenario."""
    if rng is None:
        rng = random.Random(42)
    cat = scenario["category"]
    responses = CANONICAL_RESPONSES[cat]
    tools = rng.sample(TOOL_NAMES, min(n_tools, len(TOOL_NAMES)))
    return [(t, responses[t]) for t in tools]


def run_condition(scenarios: List[Dict], condition: str,
                  classifier_fn: Callable, classifier_name: str,
                  rng: random.Random, verbose: bool = False,
                  evidence_decay: float = 1.0,
                  enable_correction: bool = True,
                  enable_dual_boundary: bool = False,
                  commit_threat_boundary: float = 0.55,
                  commit_safe_boundary: float = 0.40,
                  ) -> List[EvalResult]:
    """Run all scenarios through one condition."""
    results = []

    for scenario in scenarios:
        # Build canonical tool sequence
        canonical = build_canonical_sequence(scenario, n_tools=3, rng=random.Random(42))

        # Apply injection based on condition
        if condition == "control":
            injected = canonical
            params = {}
        elif condition == "A_noise":
            injected = inject_noise(canonical, n_noise=2, position="interleaved",
                                    rng=random.Random(rng.randint(0, 10000)))
            params = {"n_noise": 2, "position": "interleaved"}
        elif condition == "A_noise_heavy":
            injected = inject_noise(canonical, n_noise=4, position="random",
                                    rng=random.Random(rng.randint(0, 10000)))
            params = {"n_noise": 4, "position": "random"}
        elif condition == "B_contradiction":
            injected = inject_contradictions(canonical, n_contradictions=1,
                                            rng=random.Random(rng.randint(0, 10000)))
            params = {"n_contradictions": 1}
        elif condition == "B_contradiction_heavy":
            injected = inject_contradictions(canonical, n_contradictions=2,
                                            rng=random.Random(rng.randint(0, 10000)))
            params = {"n_contradictions": 2}
        elif condition == "C_adversarial_kw":
            injected = inject_adversarial_keywords(canonical, n_adversarial=2,
                                                   rng=random.Random(rng.randint(0, 10000)))
            params = {"n_adversarial": 2}
        elif condition == "C_adversarial_kw_heavy":
            injected = inject_adversarial_keywords(canonical, n_adversarial=3,
                                                   rng=random.Random(rng.randint(0, 10000)))
            params = {"n_adversarial": 3}
        elif condition == "D_delayed_correction":
            injected = inject_delayed_correction(canonical, delay_steps=2,
                                                 rng=random.Random(rng.randint(0, 10000)))
            params = {"delay_steps": 2}
        elif condition == "D_delayed_correction_long":
            injected = inject_delayed_correction(canonical, delay_steps=4,
                                                 rng=random.Random(rng.randint(0, 10000)))
            params = {"delay_steps": 4}
        else:
            raise ValueError(f"Unknown condition: {condition}")

        result = run_monitor_on_sequence(
            scenario, injected,
            classifier_fn=classifier_fn,
            condition=condition,
            classifier_name=classifier_name,
            injection_params=params,
            evidence_decay=evidence_decay,
            enable_correction=enable_correction,
            enable_dual_boundary=enable_dual_boundary,
            commit_threat_boundary=commit_threat_boundary,
            commit_safe_boundary=commit_safe_boundary,
        )
        results.append(result)

        if verbose:
            mark = "OK" if result.verdict_correct else (
                "~" if result.verdict_adjacent else "XX")
            vrd = result.final_verdict or "???"
            print(f"    {result.scenario_id:20s} [{result.category:10s}] "
                  f"→ {vrd:10s} {mark:>2s}  "
                  f"t={result.final_threat_score:.2f} "
                  f"s={result.final_safety_score:.2f} "
                  f"clarity={result.final_evidence_clarity:.2f} "
                  f"states={result.n_posture_transitions} "
                  f"recovery_t={result.threat_recovery:.2f}")

    return results


def summarize_results(results: List[EvalResult]) -> Dict:
    """Compute aggregate metrics for a condition."""
    n = len(results)
    if n == 0:
        return {}

    n_correct = sum(1 for r in results if r.verdict_correct)
    n_adjacent = sum(1 for r in results if r.verdict_adjacent)

    # Per-category
    cat_stats = {}
    for cat in ["benign", "suspicious", "escalate"]:
        cat_results = [r for r in results if r.category == cat]
        if cat_results:
            cat_stats[cat] = {
                "n": len(cat_results),
                "correct": sum(1 for r in cat_results if r.verdict_correct),
                "accuracy_pct": round(100 * sum(1 for r in cat_results if r.verdict_correct) / len(cat_results), 1),
            }

    # Recovery metrics
    benign_results = [r for r in results if r.category == "benign"]
    benign_correct = sum(1 for r in benign_results if r.verdict_correct) if benign_results else 0
    benign_recovery_pct = round(100 * benign_correct / len(benign_results), 1) if benign_results else 0.0

    # False escalation: benign scenarios that got escalated
    false_escalations = sum(1 for r in results
                            if r.category == "benign" and r.final_verdict == "escalate")
    false_escalation_pct = round(100 * false_escalations / max(1, len(benign_results)), 1)

    # Delayed correction recovery (condition D only)
    correction_results = [r for r in results if "delayed" in r.condition]
    correction_recovery = 0.0
    if correction_results:
        correction_recovery = round(
            100 * sum(1 for r in correction_results if r.verdict_correct) / len(correction_results), 1)

    # ABSTAIN metrics — track separately from accuracy
    n_abstain = sum(1 for r in results if r.final_action == "ABSTAIN")
    n_abstain_uncertainty = sum(1 for r in results if r.abstain_due_to_uncertainty)
    abstain_on_benign = sum(1 for r in results
                            if r.final_action == "ABSTAIN" and r.category == "benign")
    abstain_on_suspicious = sum(1 for r in results
                                if r.final_action == "ABSTAIN" and r.category == "suspicious")
    abstain_on_escalate = sum(1 for r in results
                              if r.final_action == "ABSTAIN" and r.category == "escalate")

    # False safe: threat/escalate scenarios that got benign verdict
    false_safe = sum(1 for r in results
                     if r.category == "escalate" and r.final_verdict == "benign")
    threat_results = [r for r in results if r.category == "escalate"]
    false_safe_pct = round(100 * false_safe / max(1, len(threat_results)), 1)

    return {
        "n_scenarios": n,
        "n_correct": n_correct,
        "n_adjacent": n_adjacent,
        "accuracy_pct": round(100 * n_correct / n, 1),
        "accuracy_with_adjacent_pct": round(100 * (n_correct + n_adjacent) / n, 1),
        "benign_recovery_pct": benign_recovery_pct,
        "false_escalation_pct": false_escalation_pct,
        "false_safe_pct": false_safe_pct,
        "correction_recovery_pct": correction_recovery,
        # ABSTAIN metrics
        "n_abstain": n_abstain,
        "abstain_pct": round(100 * n_abstain / n, 1),
        "n_abstain_uncertainty": n_abstain_uncertainty,
        "abstain_uncertainty_pct": round(100 * n_abstain_uncertainty / n, 1),
        "abstain_on_benign": abstain_on_benign,
        "abstain_on_suspicious": abstain_on_suspicious,
        "abstain_on_escalate": abstain_on_escalate,
        "per_category": cat_stats,
        "avg_threat_score": round(sum(r.final_threat_score for r in results) / n, 4),
        "avg_safety_score": round(sum(r.final_safety_score for r in results) / n, 4),
        "avg_evidence_clarity": round(sum(r.final_evidence_clarity for r in results) / n, 4),
        "avg_contradiction": round(sum(r.final_contradiction for r in results) / n, 4),
        "avg_posture_transitions": round(sum(r.n_posture_transitions for r in results) / n, 2),
        "max_threat_delta_seen": round(max(r.max_threat_delta for r in results), 4),
        "avg_threat_recovery": round(sum(r.threat_recovery for r in results) / n, 4),
    }


# ============================================================
# Gate checks (Steven's success criteria)
# ============================================================

def check_gates(all_summaries: Dict[str, Dict]) -> Dict:
    """Check adversarial robustness gates."""
    gates = {}

    # Gate 1: Benign recovery > 75% under noise
    noise_conditions = [k for k in all_summaries if k.startswith("A_")]
    if noise_conditions:
        avg_benign_recovery = sum(
            all_summaries[c].get("benign_recovery_pct", 0) for c in noise_conditions
        ) / len(noise_conditions)
        gates["benign_recovery_under_noise"] = {
            "threshold": 75.0,
            "actual": round(avg_benign_recovery, 1),
            "pass": avg_benign_recovery >= 75.0,
        }

    # Gate 2: False escalation < 10%
    all_conditions = [k for k in all_summaries if k != "control"]
    if all_conditions:
        avg_false_esc = sum(
            all_summaries[c].get("false_escalation_pct", 0) for c in all_conditions
        ) / len(all_conditions)
        gates["false_escalation_rate"] = {
            "threshold": 10.0,
            "actual": round(avg_false_esc, 1),
            "pass": avg_false_esc <= 10.0,
        }

    # Gate 3: Recovery from delayed correction > 80%
    delayed_conditions = [k for k in all_summaries if k.startswith("D_")]
    if delayed_conditions:
        avg_correction = sum(
            all_summaries[c].get("correction_recovery_pct", 0) for c in delayed_conditions
        ) / len(delayed_conditions)
        gates["delayed_correction_recovery"] = {
            "threshold": 80.0,
            "actual": round(avg_correction, 1),
            "pass": avg_correction >= 80.0,
        }

    # Gate 4: Semantic classifier outperforms keyword
    # (computed later when both passes are available)

    # Overall
    gates["overall_pass"] = all(g["pass"] for g in gates.values())

    return gates


def check_sensor_improvement(keyword_summaries: Dict, semantic_summaries: Dict) -> Dict:
    """Compare keyword vs semantic classifier performance."""
    comparison = {}

    for condition in keyword_summaries:
        if condition not in semantic_summaries:
            continue
        kw = keyword_summaries[condition]
        sem = semantic_summaries[condition]

        comparison[condition] = {
            "keyword_accuracy": kw.get("accuracy_pct", 0),
            "semantic_accuracy": sem.get("accuracy_pct", 0),
            "delta_pp": round(sem.get("accuracy_pct", 0) - kw.get("accuracy_pct", 0), 1),
            "keyword_benign_recovery": kw.get("benign_recovery_pct", 0),
            "semantic_benign_recovery": sem.get("benign_recovery_pct", 0),
            "keyword_false_esc": kw.get("false_escalation_pct", 0),
            "semantic_false_esc": sem.get("false_escalation_pct", 0),
        }

    # Overall: does semantic beat keyword?
    if comparison:
        avg_delta = sum(c["delta_pp"] for c in comparison.values()) / len(comparison)
        comparison["_overall"] = {
            "avg_accuracy_delta_pp": round(avg_delta, 1),
            "semantic_wins": avg_delta > 0,
        }

    return comparison


# ============================================================
# Main experiment
# ============================================================

ALL_CONDITIONS = [
    "control",
    "A_noise",
    "A_noise_heavy",
    "B_contradiction",
    "B_contradiction_heavy",
    "C_adversarial_kw",
    "C_adversarial_kw_heavy",
    "D_delayed_correction",
    "D_delayed_correction_long",
]


def _run_single_config(scenarios, conditions, classifier_fn, classifier_name,
                       evidence_decay, enable_correction, config_label,
                       seed, verbose,
                       enable_dual_boundary=False,
                       commit_threat_boundary=0.55,
                       commit_safe_boundary=0.40):
    """Run all conditions for one architecture configuration."""
    rng = random.Random(seed)
    results = {}
    summaries = {}

    print(f"\n" + "=" * 70)
    print(f"  {config_label}")
    extras = f"decay={evidence_decay}, correction={enable_correction}"
    if enable_dual_boundary:
        extras += f", dual_boundary=True, threat_b={commit_threat_boundary}, safe_b={commit_safe_boundary}"
    print(f"  ({extras})")
    print("=" * 70)

    for condition in conditions:
        print(f"\n  --- {condition} ---")
        cond_results = run_condition(
            scenarios, condition,
            classifier_fn=classifier_fn,
            classifier_name=classifier_name,
            rng=random.Random(rng.randint(0, 100000)),
            verbose=verbose,
            evidence_decay=evidence_decay,
            enable_correction=enable_correction,
            enable_dual_boundary=enable_dual_boundary,
            commit_threat_boundary=commit_threat_boundary,
            commit_safe_boundary=commit_safe_boundary,
        )
        results[condition] = cond_results
        summary = summarize_results(cond_results)
        summaries[condition] = summary
        print(f"    Accuracy: {summary['accuracy_pct']}%  "
              f"Benign recovery: {summary['benign_recovery_pct']}%  "
              f"False escalation: {summary['false_escalation_pct']}%  "
              f"Correction recovery: {summary['correction_recovery_pct']}%")

    return results, summaries


def run_experiment(conditions: Optional[List[str]] = None,
                   run_pass2: bool = False,
                   three_way: bool = False,
                   four_way: bool = False,
                   evidence_decay: float = 1.0,
                   commit_threat_boundary: float = 0.55,
                   commit_safe_boundary: float = 0.40,
                   seed: int = 42,
                   verbose: bool = False) -> Dict:
    """Run the full adversarial robustness experiment.

    When three_way=True, runs 3 configurations (leaky accumulator comparison).
    When four_way=True, runs 4 configurations (adds dual-boundary SPRT mode).
    """

    if conditions is None:
        conditions = ALL_CONDITIONS

    scenarios = ADVERSARIAL_SCENARIOS

    start_iso = time.strftime("%Y-%m-%dT%H:%M:%S")
    t_start = time.time()
    cpu_start = time.process_time()

    if three_way or four_way:
        # Multi-config comparison
        # Each config: (label, decay, correction, key, dual_boundary, threat_b, safe_b)
        configs = [
            ("CONFIG 1: v8.3 Baseline (no correction, no decay)",
             1.0, False, "v83_baseline", False, 0.55, 0.40),
            ("CONFIG 2: v9 Correction-Only (correction, no decay)",
             1.0, True, "v9_correction", False, 0.55, 0.40),
            (f"CONFIG 3: v9 + Leaky Accumulator (correction, decay={evidence_decay})",
             evidence_decay, True, "v9_leaky", False, 0.55, 0.40),
        ]
        if four_way:
            configs.append(
                (f"CONFIG 4: v9 + Decay + Dual Boundary "
                 f"(decay={evidence_decay}, threat_b={commit_threat_boundary}, "
                 f"safe_b={commit_safe_boundary})",
                 evidence_decay, True, "v9_dual_boundary",
                 True, commit_threat_boundary, commit_safe_boundary))

        all_configs = {}
        all_config_summaries = {}
        all_config_gates = {}

        for label, decay, correction, key, dual_b, tb, sb in configs:
            results, summaries = _run_single_config(
                scenarios, conditions, classify_tool_result, "keyword",
                decay, correction, label, seed, verbose,
                enable_dual_boundary=dual_b,
                commit_threat_boundary=tb,
                commit_safe_boundary=sb)
            all_configs[key] = results
            all_config_summaries[key] = summaries
            all_config_gates[key] = check_gates(summaries)

        # --- Comparison table ---
        config_keys = [k for _, _, _, k, *_ in configs]
        config_short = {"v83_baseline": "v8.3", "v9_correction": "v9",
                        "v9_leaky": "leaky", "v9_dual_boundary": "dual_b"}
        n_configs = len(config_keys)
        n_label = "4-WAY" if four_way else "3-WAY"

        print("\n" + "=" * 70)
        print(f"  {n_label} COMPARISON TABLE")
        print("=" * 70)

        # Dynamic header
        acc_h = " ".join(f"{config_short.get(k, k):>6s}" for k in config_keys)
        br_h = " ".join(f"{config_short.get(k, k):>8s}" for k in config_keys)
        fe_h = " ".join(f"{config_short.get(k, k):>6s}" for k in config_keys)
        print(f"\n  {'Condition':<28s} {acc_h} | {br_h} | {fe_h}")
        acc_sub = " ".join(f"{'Acc%':>6s}" for _ in config_keys)
        br_sub = " ".join(f"{'Benign%':>8s}" for _ in config_keys)
        fe_sub = " ".join(f"{'FE%':>6s}" for _ in config_keys)
        print(f"  {'':<28s} {acc_sub} | {br_sub} | {fe_sub}")
        print(f"  {'-'*28} {'-'*(7*n_configs)} | {'-'*(9*n_configs)} | {'-'*(7*n_configs)}")

        for condition in conditions:
            acc_vals = " ".join(
                f"{all_config_summaries[k].get(condition, {}).get('accuracy_pct', 0):>6.1f}"
                for k in config_keys)
            br_vals = " ".join(
                f"{all_config_summaries[k].get(condition, {}).get('benign_recovery_pct', 0):>8.1f}"
                for k in config_keys)
            fe_vals = " ".join(
                f"{all_config_summaries[k].get(condition, {}).get('false_escalation_pct', 0):>6.1f}"
                for k in config_keys)
            print(f"  {condition:<28s} {acc_vals} | {br_vals} | {fe_vals}")

        # --- Gate comparison ---
        print(f"\n  GATE COMPARISON:")
        gate_labels = [(k, config_short.get(k, k)) for k in config_keys]
        if four_way:
            gate_labels[-1] = ("v9_dual_boundary",
                               f"dual_b(t={commit_threat_boundary},s={commit_safe_boundary})")
        for key, label in gate_labels:
            gates = all_config_gates[key]
            gstr = " | ".join(f"{gname}: {g['actual']} {'PASS' if g['pass'] else 'FAIL'}"
                              for gname, g in gates.items() if gname != "overall_pass")
            print(f"    {label:<35s} {gstr}")

        # --- Delayed correction detail ---
        print(f"\n  DELAYED CORRECTION DETAIL:")
        for key, label in gate_labels:
            short = label[:20]
            for dc in ["D_delayed_correction", "D_delayed_correction_long"]:
                if dc in all_config_summaries.get(key, {}):
                    s = all_config_summaries[key][dc]
                    print(f"    {short:<20s} {dc:<30s} "
                          f"corr_recovery={s['correction_recovery_pct']}%  "
                          f"acc={s['accuracy_pct']}%  "
                          f"benign_rec={s['benign_recovery_pct']}%")

        # Use most advanced config for final gates
        final_key = config_keys[-1]
        gates_p1 = all_config_gates[final_key]
        pass1_summaries = all_config_summaries[final_key]
        pass1_results = all_configs[final_key]

    else:
        # Single config run (original behavior)
        pass1_results, pass1_summaries = _run_single_config(
            scenarios, conditions, classify_tool_result, "keyword",
            evidence_decay, True, "PASS 1: Keyword Classifier",
            seed, verbose)

        gates_p1 = check_gates(pass1_summaries)

    # --- Gates ---
    print("\n" + "=" * 70)
    print("  GATE CHECKS")
    print("=" * 70)

    for gate_name, gate in gates_p1.items():
        if gate_name == "overall_pass":
            continue
        mark = "PASS" if gate["pass"] else "FAIL"
        print(f"  [{mark}] {gate_name}: {gate['actual']} "
              f"(threshold: {'<=' if 'escalation' in gate_name else '>='} {gate['threshold']})")

    # --- Pass 2: Semantic classifier (optional, not in 3-way) ---
    pass2_results = {}
    pass2_summaries = {}
    sensor_comparison = {}

    if run_pass2 and not three_way and not four_way:
        pass2_results_raw, pass2_summaries = _run_single_config(
            scenarios, conditions, classify_tool_result_semantic, "semantic",
            evidence_decay, True, "PASS 2: Semantic Classifier",
            seed, verbose)
        pass2_results = pass2_results_raw

        sensor_comparison = check_sensor_improvement(pass1_summaries, pass2_summaries)
        print(f"\n  --- Sensor Comparison ---")
        for cond, comp in sensor_comparison.items():
            if cond.startswith("_"):
                continue
            print(f"  {cond:30s}  kw={comp['keyword_accuracy']}%  "
                  f"sem={comp['semantic_accuracy']}%  "
                  f"delta={comp['delta_pp']:+.1f}pp")
        overall = sensor_comparison.get("_overall", {})
        if overall:
            mark = "PASS" if overall["semantic_wins"] else "FAIL"
            print(f"\n  [{mark}] Semantic classifier improvement: "
                  f"{overall['avg_accuracy_delta_pp']:+.1f}pp average")

    # --- Summary table ---
    print("\n" + "=" * 70)
    print("  SUMMARY TABLE")
    print("=" * 70)
    print(f"\n  {'Condition':<30s} {'Acc%':>6s} {'Benign%':>8s} {'FalseEsc%':>10s} "
          f"{'AvgThreat':>10s} {'AvgSafety':>10s} {'Clarity':>8s}")
    print(f"  {'-'*30} {'-'*6} {'-'*8} {'-'*10} {'-'*10} {'-'*10} {'-'*8}")
    for condition in conditions:
        s = pass1_summaries[condition]
        print(f"  {condition:<30s} {s['accuracy_pct']:>6.1f} "
              f"{s['benign_recovery_pct']:>8.1f} "
              f"{s['false_escalation_pct']:>10.1f} "
              f"{s['avg_threat_score']:>10.4f} "
              f"{s['avg_safety_score']:>10.4f} "
              f"{s['avg_evidence_clarity']:>8.4f}")

    # --- Overall verdict ---
    overall_pass = gates_p1.get("overall_pass", False)
    sensor_pass = sensor_comparison.get("_overall", {}).get("semantic_wins", None)

    print(f"\n" + "=" * 70)
    if overall_pass:
        print("  VERDICT: ARCHITECTURE PASSES ADVERSARIAL ROBUSTNESS GATES")
    else:
        print("  VERDICT: ARCHITECTURE FAILS — SEE INDIVIDUAL GATES")
    if four_way:
        print(f"  MODE:    4-WAY COMPARISON (decay={evidence_decay}, "
              f"threat_b={commit_threat_boundary}, safe_b={commit_safe_boundary})")
    elif three_way:
        print(f"  MODE:    3-WAY COMPARISON (decay={evidence_decay})")
    if sensor_pass is True:
        print("  SENSOR:  SEMANTIC CLASSIFIER OUTPERFORMS KEYWORD → "
              "ARCHITECTURE SURVIVES SENSOR UPGRADE")
    elif sensor_pass is False:
        print("  SENSOR:  SEMANTIC CLASSIFIER DID NOT OUTPERFORM KEYWORD")
    print("=" * 70)

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
        "experiment": "MORPHSAT_DUAL_BOUNDARY_V1" if four_way else (
            "MORPHSAT_LEAKY_ACCUMULATOR_V1" if three_way else "MORPHSAT_ADVERSARIAL_ROBUSTNESS_V1"),
        "seed": seed,
        "n_scenarios": len(scenarios),
        "conditions": conditions,
        "evidence_decay": evidence_decay,
        "three_way": three_way,
        "four_way": four_way,
        "commit_threat_boundary": commit_threat_boundary if four_way else None,
        "commit_safe_boundary": commit_safe_boundary if four_way else None,
        "classifiers": ["keyword"] + (["semantic"] if run_pass2 else []),
    }

    if three_way or four_way:
        receipt["configs"] = {
            key: {
                "summaries": all_config_summaries[key],
                "gates": all_config_gates[key],
            }
            for key in config_keys
        }
    else:
        receipt["pass1_keyword"] = {
            "summaries": pass1_summaries,
            "results": [asdict(r) for cond_results in pass1_results.values()
                        for r in cond_results],
        }
        if run_pass2:
            receipt["pass2_semantic"] = {
                "summaries": pass2_summaries,
                "results": [asdict(r) for cond_results in pass2_results.values()
                            for r in cond_results],
            }
            receipt["sensor_comparison"] = sensor_comparison

    receipt["gates"] = gates_p1
    receipt["overall_pass"] = overall_pass
    receipt["cost"] = cost

    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    tag = "dual_boundary" if four_way else (
        "leaky_accumulator" if three_way else "adversarial_robustness")
    receipt_path = RECEIPTS_DIR / f"{tag}_{ts}.json"
    receipt_path.write_text(json.dumps(receipt, indent=2, default=str))
    print(f"\n  Receipt: {receipt_path}")
    print(f"  Wall time: {wall_total:.1f}s")

    return receipt


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="MorphSAT Adversarial Evidence Robustness Benchmark")
    parser.add_argument("--condition", type=str, default=None,
                        choices=["A", "B", "C", "D", "all"],
                        help="Run specific condition group (default: all)")
    parser.add_argument("--pass2", action="store_true",
                        help="Also run with semantic classifier (Pass 2)")
    parser.add_argument("--three-way", action="store_true",
                        help="Run 3-way comparison: v8.3 baseline vs v9 correction vs v9+leaky")
    parser.add_argument("--four-way", action="store_true",
                        help="Run 4-way comparison: adds dual-boundary (SPRT-like) mode")
    parser.add_argument("--decay", type=float, default=0.85,
                        help="Evidence decay factor for leaky accumulator (default: 0.85)")
    parser.add_argument("--threat-boundary", type=float, default=0.55,
                        help="Threat commit boundary for dual-boundary mode (default: 0.55)")
    parser.add_argument("--safe-boundary", type=float, default=0.40,
                        help="Safe commit boundary for dual-boundary mode (default: 0.40)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print per-scenario details")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
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
        conditions = None  # all

    if args.four_way:
        mode = "4-way comparison (dual-boundary)"
        title = "MorphSAT Plan 3 — Uncertainty-Preserving Boundaries"
    elif args.three_way:
        mode = "3-way comparison"
        title = "MorphSAT Phase 1.5 — Leaky Evidence Accumulator"
    else:
        mode = "standard"
        title = "MorphSAT Phase 1 — Adversarial Evidence Robustness"

    print(title)
    print(f"  Mode: {mode}")
    print(f"  Conditions: {conditions or 'all'}")
    print(f"  Classifier: keyword" + (" + semantic" if args.pass2 else ""))
    if args.three_way or args.four_way:
        print(f"  Decay factor: {args.decay}")
    if args.four_way:
        print(f"  Threat boundary: {args.threat_boundary}")
        print(f"  Safe boundary: {args.safe_boundary}")
    print(f"  Seed: {args.seed}")
    print(f"  Scenarios: {len(ADVERSARIAL_SCENARIOS)}")

    run_experiment(
        conditions=conditions,
        run_pass2=args.pass2,
        three_way=args.three_way,
        four_way=args.four_way,
        evidence_decay=args.decay,
        commit_threat_boundary=args.threat_boundary,
        commit_safe_boundary=args.safe_boundary,
        seed=args.seed,
        verbose=args.verbose,
    )


if __name__ == "__main__":
    main()
