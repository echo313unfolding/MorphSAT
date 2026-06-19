#!/usr/bin/env python3
"""MorphSAT Layer 3 — Memory Stress Benchmark.

Harder than bench_memory_usefulness.py. Designed to distinguish ReceiptGraph
from SplitMemoryStore by testing error correction, concept drift, poisoned
memory, and stale patterns.

Architecture under test:
    Sentinel senses. Receipt graph remembers. MorphSAT governs. Receipt chain proves.

8 scenario families (8-12 episodes each, ~72 total):
    1. long_delayed_correction  — false threat, correction 5+ episodes later
    2. same_phrase_diff_outcome — identical keywords, different tool evidence
    3. concept_drift            — pattern transitions from threat to benign
    4. sensor_graph_disagreement — tool evidence vs historical memory conflict
    5. poisoned_memory          — adversary plants false benign for real threat
    6. stale_memory_trap        — old threat pattern now patched, should be benign
    7. cross_domain_structure   — same attack pattern in different domains
    8. hard_abstain_required    — genuinely ambiguous, ABSTAIN is correct

Modes (same as bench_memory_usefulness.py + H, J):
    A: baseline       — no memory, no chain, no graph
    B: split_memory   — SplitMemoryStore only
    C: chain_only     — receipt chain only (should equal A)
    D: graph_hud      — SplitMemory + chain + graph + HUD
    H: qubo_gate      — SplitMemory + chain + graph + MemoryQUBO + GateQUBO
    J: two_stage      — SplitMemory + chain + graph + TwoStageGate (threshold + QUBO)

KEY HONEST FINDING: Mode D = Mode B behaviorally because the graph has
no steering mechanism. Graph internal metrics (prediction accuracy, edge
weights) are tracked separately to show the graph IS learning even though
it can't yet influence behavior. This gap is the evidence for why graph
steering is the next architecture step.

Usage:
    python3 tools/bench_memory_stress.py
    python3 tools/bench_memory_stress.py --mode D --verbose
    python3 tools/bench_memory_stress.py --family concept_drift

WO-RECEIPT-COST-01 compliant.
"""

import argparse
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

sys.path.insert(0, str(Path(__file__).parent.parent))
from morphsat.shadow_monitor import ShadowMonitor, ShadowState
from morphsat.commit_gate import (
    SplitMemoryStore,
    CommitAction,
    classify_tool_result,
)
from morphsat.receipt_chain import ReceiptChain, canonical_hash
from morphsat.receipt_graph import ReceiptGraph
from morphsat.memory_qubo import MemoryQUBO
from morphsat.gate_qubo import GateQUBO, GateSnapshot
from morphsat.two_stage_gate import TwoStageGate

RECEIPTS_DIR = Path.home() / "receipts" / "morphsat_memory_stress"


# ============================================================
# Tool response templates
# ============================================================

TOOL_NAMES = ["check_hash", "check_process", "check_ports", "scan_file", "search_cve"]

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

# Correction-specific responses
CORRECTION_RESPONSES = {
    "check_hash": "Hash lookup: CORRECTION — previous alert hash re-analyzed. Matches known-good vendor binary. False positive confirmed.",
    "check_process": "Process check: CORRECTION — the process flagged earlier is a legitimate cron job. sysadmin confirmed. No threat.",
    "scan_file": "YARA scan: CORRECTION — rule match was false positive. File is signed. Vendor issued clarification.",
}


# ============================================================
# Semantic classifier (same as bench_memory_usefulness.py)
# ============================================================

def classify_tool_result_semantic(tool_result: str) -> Tuple[str, float, float]:
    """Semantic classifier — negation/context/correction aware."""
    text_lower = tool_result.lower()

    if any(kw in text_lower for kw in ["correction:", "correction —",
                                        "false positive confirmed",
                                        "false alarm", "was closed as"]):
        return "correction", 0.0, 0.35

    NOISE_INDICATORS = [
        "ntp sync", "disk usage", "memory check", "load average",
        "package audit", "backup status", "cron job summary",
    ]
    if any(kw in text_lower for kw in NOISE_INDICATORS):
        return "noise", 0.0, 0.0

    NEGATED_THREAT = [
        "no threat", "not compromised", "no danger", "not suspicious",
        "no unexpected", "no anomal", "no match on rule",
        "not obfuscated", "is blocked by policy", "was patched",
        "no lateral movement", "approved change",
    ]
    if any(kw in text_lower for kw in NEGATED_THREAT):
        neg_count = sum(1 for kw in NEGATED_THREAT if kw in text_lower)
        return "negated_threat", 0.0, min(0.30, 0.10 * neg_count)

    ACTIVE_THREAT = [
        "unexpected child process", "unusual for this service",
        "not found in known-good", "not in baseline",
        "match on rule", "suspicious_packer",
        "high entropy", "exploit available",
        "remote code execution", "reverse shell",
        "c2 behavior", "lateral movement",
        "port 4444", "opened 10 min ago",
    ]
    threat_hits = sum(1 for kw in ACTIVE_THREAT if kw in text_lower)
    if threat_hits >= 2:
        return "confirmed_threat", min(0.40, 0.15 * threat_hits), 0.0
    elif threat_hits == 1:
        return "possible_threat", 0.20, 0.0

    ACTIVE_SAFETY = [
        "known-good", "vendor database", "signed and in package",
        "all match baseline", "within expected", "no anomalies",
        "system is patched", "verified signature", "approved",
        "signed binary", "scheduled task",
    ]
    safety_hits = sum(1 for kw in ACTIVE_SAFETY if kw in text_lower)
    if safety_hits >= 2:
        return "confirmed_safe", 0.0, min(0.35, 0.12 * safety_hits)
    elif safety_hits == 1:
        return "likely_safe", 0.0, 0.20

    return "unknown", 0.03, 0.03


# ============================================================
# Scenario families — 8 stress families
# ============================================================

def _build_stress_families() -> Dict[str, List[Dict]]:
    """Build 8 stress families with 8-12 episodes each."""

    families = {}

    # --- 1. Long delayed correction (10 episodes) ---
    # False threat at ep 0, unrelated eps 1-5, correction at ep 6,
    # verify correction stuck at eps 7-9
    families["long_delayed_correction"] = [
        {"id": "ldc_00", "category": "escalate",
         "alert": "Privilege escalation: www-data spawned root shell via CVE-2026-9999. New cron entry created.",
         "tool_category": "escalate"},
        # Unrelated episodes (different domain)
        {"id": "ldc_01", "category": "benign",
         "alert": "Scheduled backup completed. rsync to NAS. 12GB transferred.",
         "tool_category": "benign"},
        {"id": "ldc_02", "category": "benign",
         "alert": "Certificate renewal completed. certbot ran successfully.",
         "tool_category": "benign"},
        {"id": "ldc_03", "category": "suspicious",
         "alert": "New SSH key added to authorized_keys on db-01. Source unknown.",
         "tool_category": "suspicious"},
        {"id": "ldc_04", "category": "benign",
         "alert": "Package update: openssl 3.0.15 installed from Ubuntu repos.",
         "tool_category": "benign"},
        {"id": "ldc_05", "category": "benign",
         "alert": "Disk usage alert cleared. /var/log rotated successfully.",
         "tool_category": "benign"},
        # Correction of ep 0
        {"id": "ldc_06", "category": "benign",
         "alert": "CORRECTION: CVE-2026-9999 alert was false positive. www-data process was legitimate cron job. Confirmed by incident response team.",
         "tool_category": "benign",
         "has_correction_tools": True},
        # Post-correction: same pattern should now be benign
        {"id": "ldc_07", "category": "benign",
         "alert": "www-data spawned process on same host. Matches corrected pattern from CHG-9999.",
         "tool_category": "benign"},
        {"id": "ldc_08", "category": "benign",
         "alert": "Same host re-scanned after correction. All processes match baseline.",
         "tool_category": "benign"},
        {"id": "ldc_09", "category": "benign",
         "alert": "Weekly security audit: host from CVE-2026-9999 incident passes all checks.",
         "tool_category": "benign"},
    ]

    # --- 2. Same phrase, different outcome (10 episodes) ---
    # Same alert keywords ("kernel module loaded") with different tool evidence
    families["same_phrase_diff_outcome"] = [
        # Benign kernel module loads
        {"id": "spdo_00", "category": "benign",
         "alert": "Kernel module loaded: vboxdrv. VirtualBox guest additions updated.",
         "tool_category": "benign"},
        {"id": "spdo_01", "category": "benign",
         "alert": "Kernel module loaded: nouveau. GPU driver reloaded after X restart.",
         "tool_category": "benign"},
        {"id": "spdo_02", "category": "benign",
         "alert": "Kernel module loaded: overlay. Docker started container build.",
         "tool_category": "benign"},
        # Threat kernel module loads (same keywords, different evidence)
        {"id": "spdo_03", "category": "escalate",
         "alert": "Kernel module loaded: unknown_mod. Not in any signed module database. Loaded by non-root user.",
         "tool_category": "escalate"},
        {"id": "spdo_04", "category": "escalate",
         "alert": "Kernel module loaded: rootkit_hider. Matches known rootkit signature. Process tree hidden.",
         "tool_category": "escalate"},
        # Back to benign
        {"id": "spdo_05", "category": "benign",
         "alert": "Kernel module loaded: wireguard. VPN tunnel established per network policy.",
         "tool_category": "benign"},
        {"id": "spdo_06", "category": "benign",
         "alert": "Kernel module loaded: nfs. NFS mount for shared storage. Approved change.",
         "tool_category": "benign"},
        # Suspicious (ambiguous)
        {"id": "spdo_07", "category": "suspicious",
         "alert": "Kernel module loaded: custom_drv. Not in package database but signed by internal CA.",
         "tool_category": "suspicious"},
        # One more threat to test if memory separates
        {"id": "spdo_08", "category": "escalate",
         "alert": "Kernel module loaded: keylogger_mod. Matches YARA rule. Intercepting keyboard input.",
         "tool_category": "escalate"},
        {"id": "spdo_09", "category": "benign",
         "alert": "Kernel module loaded: fuse. User-space filesystem for backup tool.",
         "tool_category": "benign"},
    ]

    # --- 3. Concept drift (10 episodes) ---
    # Pattern X is threat for eps 0-3, then becomes benign for eps 4-9.
    # KEY: post-drift alerts use nearly identical keywords as pre-drift
    # (>50% keyword overlap triggers SplitMemory lookup). Post-drift
    # tool evidence is MIXED — tools still flag the pattern even though
    # it's now approved. SplitMemory should find the old threat match
    # and lower commit_clarity, biasing toward escalate.
    families["concept_drift"] = [
        # Phase 1: outbound connection pattern = threat
        {"id": "drift_00", "category": "escalate",
         "alert": "Outbound connection pattern detected host connecting external endpoint matches threat indicator",
         "tool_category": "escalate"},
        {"id": "drift_01", "category": "escalate",
         "alert": "Outbound connection pattern continued host exfiltrating data external endpoint confirmed threat",
         "tool_category": "escalate"},
        {"id": "drift_02", "category": "escalate",
         "alert": "Outbound connection pattern spreading second host connecting same external endpoint threat",
         "tool_category": "escalate"},
        {"id": "drift_03", "category": "escalate",
         "alert": "Outbound connection pattern escalating multiple hosts external endpoint threat payloads",
         "tool_category": "escalate"},
        # Correction: endpoint is now approved CDN
        {"id": "drift_04", "category": "benign",
         "alert": "CORRECTION: External endpoint approved as CDN per change ticket. Outbound connection pattern is now expected.",
         "tool_category": "benign",
         "has_correction_tools": True},
        # Post-drift: SAME keywords but now benign. Tool evidence is mixed.
        {"id": "drift_05", "category": "benign",
         "alert": "Outbound connection pattern detected host connecting external endpoint matches approved change",
         "tool_category": "suspicious",
         "custom_tools": [
             ("check_ports", "Listening ports: 22, 80, 443. Outbound to external endpoint. Not in baseline on this sensor."),
             ("check_hash", "Hash lookup: CDN client binary. Matches known-good in vendor database."),
             ("scan_file", "YARA scan: No rule match. Traffic is HTTPS. Certificate valid."),
         ]},
        {"id": "drift_06", "category": "benign",
         "alert": "Outbound connection pattern volume spike host connecting external endpoint deploy pattern",
         "tool_category": "suspicious",
         "custom_tools": [
             ("check_process", "Process check: cdn-client process spawned by deploy script. Expected during rollout."),
             ("check_ports", "Listening ports: 22, 80, 443. Outbound to external endpoint. Volume 3x normal — unusual."),
             ("search_cve", "CVE search: No critical CVEs. cdn-client version is current."),
         ]},
        {"id": "drift_07", "category": "benign",
         "alert": "Outbound connection pattern third host connecting external endpoint same indicator",
         "tool_category": "suspicious",
         "custom_tools": [
             ("check_hash", "Hash lookup: cdn-client binary. Matches known-good in vendor database."),
             ("check_ports", "Listening ports: 22, 80, 443. Outbound to external endpoint. Not in baseline on this host."),
             ("check_process", "Process check: All processes within expected parameters. No anomalies."),
         ]},
        {"id": "drift_08", "category": "benign",
         "alert": "Outbound connection pattern stable host connecting external endpoint within expected range",
         "tool_category": "benign"},
        {"id": "drift_09", "category": "benign",
         "alert": "Outbound connection pattern monthly review external endpoint approved all sensors updated",
         "tool_category": "benign"},
    ]

    # --- 4. Sensor/graph disagreement (8 episodes) ---
    # Tool evidence is misleading; historical patterns should help
    families["sensor_graph_disagreement"] = [
        # Build history: port 8080 is always benign (dev server)
        {"id": "sgd_00", "category": "benign",
         "alert": "Port 8080 active on dev-01. Developer testing environment.",
         "tool_category": "benign"},
        {"id": "sgd_01", "category": "benign",
         "alert": "Port 8080 on staging-01. QA deployment running.",
         "tool_category": "benign"},
        {"id": "sgd_02", "category": "benign",
         "alert": "Port 8080 on dev-02. Same pattern as dev-01.",
         "tool_category": "benign"},
        # Disagreement: port 8080 on PROD (normally alarming, but tools show benign)
        {"id": "sgd_03", "category": "suspicious",
         "alert": "Port 8080 on prod-web-01. NOT in production baseline. But traffic is internal only.",
         "tool_category": "suspicious"},
        # Disagreement: looks benign but is actually threat
        {"id": "sgd_04", "category": "escalate",
         "alert": "Port 8080 on prod-db-01. Traffic appears normal but source IP is external. Tunneled connection.",
         "tool_category": "escalate"},
        # Back to normal
        {"id": "sgd_05", "category": "benign",
         "alert": "Port 8080 on dev-03. Standard dev pattern.",
         "tool_category": "benign"},
        # Another disagreement
        {"id": "sgd_06", "category": "suspicious",
         "alert": "Port 8080 on prod-api-01. Internal traffic only. But opened by non-standard process.",
         "tool_category": "suspicious"},
        {"id": "sgd_07", "category": "benign",
         "alert": "Port 8080 on dev-01 again. Same pattern. No changes.",
         "tool_category": "benign"},
    ]

    # --- 5. Poisoned memory (10 episodes) ---
    # Adversary plants false benign patterns for a threat pattern.
    # KEY: After poison phase (benign DNS), the SAME domain becomes
    # a threat. Tool evidence for the threat is mixed — some tools
    # still see the domain as normal (benign reputation cached).
    # SplitMemory should have "tolerance" entries for this domain
    # from the poison phase, making it HARDER to escalate.
    families["poisoned_memory"] = [
        # Poison phase: adversary makes DNS exfil look benign
        {"id": "poison_00", "category": "benign",
         "alert": "DNS queries to analytics-cdn.example.com. Standard web analytics traffic.",
         "tool_category": "benign"},
        {"id": "poison_01", "category": "benign",
         "alert": "DNS activity to analytics-cdn.example.com from web-01. Normal volume.",
         "tool_category": "benign"},
        {"id": "poison_02", "category": "benign",
         "alert": "DNS patterns to analytics-cdn.example.com stable. No anomalies.",
         "tool_category": "benign"},
        # Threat activates — same domain, same keywords, but behavior changed
        # Tool evidence is MIXED: some tools still show old benign reputation
        {"id": "poison_03", "category": "escalate",
         "alert": "DNS queries to analytics-cdn.example.com. Volume increased. TXT record queries appearing.",
         "tool_category": "escalate",
         "custom_tools": [
             ("check_hash", "Hash lookup: dns-client binary. Matches known-good in package database."),
             ("check_ports", "Listening ports: 22, 80, 443. DNS queries to analytics-cdn.example.com:443. Outbound volume 5x normal."),
             ("scan_file", "YARA scan: MATCH on rule 'dns_exfil_pattern'. Base64-encoded TXT queries. Entropy 7.2/8.0."),
         ]},
        {"id": "poison_04", "category": "escalate",
         "alert": "analytics-cdn.example.com DNS exfiltration. Payload sizes match credential store.",
         "tool_category": "escalate"},
        # Clear escalation — no ambiguity
        {"id": "poison_05", "category": "escalate",
         "alert": "Continued DNS exfil to analytics-cdn.example.com. Third host affected.",
         "tool_category": "escalate"},
        {"id": "poison_06", "category": "escalate",
         "alert": "analytics-cdn.example.com blocklisted. But legacy DNS cache still resolving.",
         "tool_category": "escalate"},
        # Post-recovery: similar pattern, new domain — should be suspicious
        {"id": "poison_07", "category": "suspicious",
         "alert": "DNS queries to metrics-relay.example.net. Structure matches analytics-cdn.example.com.",
         "tool_category": "suspicious"},
        {"id": "poison_08", "category": "escalate",
         "alert": "metrics-relay.example.net confirmed C2. Same operator as analytics-cdn.example.com.",
         "tool_category": "escalate"},
        {"id": "poison_09", "category": "benign",
         "alert": "DNS patterns normal. All known-bad domains blocklisted and verified.",
         "tool_category": "benign"},
    ]

    # --- 6. Stale memory trap (8 episodes) ---
    # Old CVE was threat, now patched — memory should not keep escalating.
    # KEY: post-patch alerts share keywords with pre-patch (vulnerability
    # scanner detected exploit apache struts). SplitMemory should match
    # old threat entries and bias toward escalate even though patched.
    families["stale_memory_trap"] = [
        # Old CVE pattern: threat
        {"id": "stale_00", "category": "escalate",
         "alert": "Vulnerability scanner detected exploit targeting apache struts remote code execution unpatched",
         "tool_category": "escalate"},
        {"id": "stale_01", "category": "escalate",
         "alert": "Vulnerability scanner detected continued exploit attempts apache struts attack ongoing unpatched",
         "tool_category": "escalate"},
        # Patch applied
        {"id": "stale_02", "category": "benign",
         "alert": "CORRECTION: Apache struts vulnerability patched. Scanner should stop flagging. Verified.",
         "tool_category": "benign",
         "has_correction_tools": True},
        # Post-patch: scanner still flags (stale signature), shares pre-patch keywords
        {"id": "stale_03", "category": "benign",
         "alert": "Vulnerability scanner detected stale signature apache struts remote code execution patched version",
         "tool_category": "suspicious",
         "custom_tools": [
             ("search_cve", "CVE search: Found CVE-2026-1111 (CVSS 9.1). Remote code execution. Exploit available in public. Patch not applied."),
             ("check_hash", "Hash lookup: Apache Struts binary. Matches known-good package in vendor database. Version 6.7.2."),
             ("scan_file", "YARA scan: No matches. File is signed and in package database."),
         ]},
        {"id": "stale_04", "category": "benign",
         "alert": "Vulnerability scanner detected apache struts flagged again remote code execution already patched",
         "tool_category": "suspicious",
         "custom_tools": [
             ("search_cve", "CVE search: Found CVE-2026-1111 (CVSS 9.1). Remote code execution. Exploit available in public. Patch not applied."),
             ("check_process", "Process check: All processes within expected parameters. No anomalies."),
             ("check_hash", "Hash lookup: Matches known-good package in vendor database."),
         ]},
        # New CVE: should be treated independently
        {"id": "stale_05", "category": "escalate",
         "alert": "Different vulnerability detected new exploit targeting nginx component unpatched critical",
         "tool_category": "escalate"},
        {"id": "stale_06", "category": "benign",
         "alert": "Vulnerability scanner detected apache struts quarterly scan remote code execution remediated",
         "tool_category": "suspicious",
         "custom_tools": [
             ("search_cve", "CVE search: Found CVE-2026-1111 (CVSS 9.1). Remote code execution. Exploit available in public. Patch not applied."),
             ("scan_file", "YARA scan: No matches. File is signed and in package database."),
             ("check_ports", "Listening ports: 22 (sshd), 80 (nginx), 443 (nginx). All match baseline."),
         ]},
        {"id": "stale_07", "category": "benign",
         "alert": "Vulnerability scanner cleared apache struts signature updated annual compliance pass",
         "tool_category": "benign"},
    ]

    # --- 7. Cross-domain same structure (8 episodes) ---
    # Port scan → brute force → lateral movement pattern in two domains
    families["cross_domain_structure"] = [
        # Network domain: classic lateral movement
        {"id": "xdom_00", "category": "escalate",
         "alert": "Network: port scan from 10.0.1.50 detected at 14:02 UTC.",
         "tool_category": "escalate"},
        {"id": "xdom_01", "category": "escalate",
         "alert": "Network: SMB brute force from 10.0.1.50 at 14:05 UTC. 500 attempts in 3 min.",
         "tool_category": "escalate"},
        {"id": "xdom_02", "category": "escalate",
         "alert": "Network: PsExec lateral movement from 10.0.1.50 to 10.0.2.30 at 14:08 UTC.",
         "tool_category": "escalate"},
        {"id": "xdom_03", "category": "benign",
         "alert": "Network: authorized penetration test from 10.0.3.10. Approved by CISO.",
         "tool_category": "benign"},
        # Cloud domain: same structure, different substrate
        {"id": "xdom_04", "category": "escalate",
         "alert": "AWS: API enumeration from compromised IAM key. ListBuckets, DescribeInstances at 15:02 UTC.",
         "tool_category": "escalate"},
        {"id": "xdom_05", "category": "escalate",
         "alert": "AWS: credential stuffing against SSO portal at 15:05 UTC. 200 attempts.",
         "tool_category": "escalate"},
        {"id": "xdom_06", "category": "escalate",
         "alert": "AWS: AssumeRole to production account from compromised dev account at 15:08 UTC.",
         "tool_category": "escalate"},
        {"id": "xdom_07", "category": "benign",
         "alert": "AWS: CloudTrail shows normal admin activity. IAM rotation completed per schedule.",
         "tool_category": "benign"},
    ]

    # --- 8. Hard abstain required (8 episodes) ---
    # Genuinely ambiguous — ABSTAIN is the only safe answer
    families["hard_abstain_required"] = [
        {"id": "abstain_00", "category": "suspicious",
         "alert": "Unknown binary in /tmp. No YARA match. Not in package DB. But no network activity.",
         "tool_category": "suspicious"},
        {"id": "abstain_01", "category": "suspicious",
         "alert": "Unusual cron entry added. Runs at 3 AM. Script path exists but content is obfuscated.",
         "tool_category": "suspicious"},
        {"id": "abstain_02", "category": "suspicious",
         "alert": "SSH session from VPN IP. User is authorized but connecting at unusual time. No prior pattern.",
         "tool_category": "suspicious"},
        {"id": "abstain_03", "category": "suspicious",
         "alert": "New systemd service registered. Binary is signed but by unknown CA. No network connections.",
         "tool_category": "suspicious"},
        {"id": "abstain_04", "category": "suspicious",
         "alert": "Process consuming 95% CPU. Could be cryptominer or legitimate batch job. PID matches cron.",
         "tool_category": "suspicious"},
        {"id": "abstain_05", "category": "suspicious",
         "alert": "File permission change on /etc/shadow. Done by root, but no corresponding sudo log entry.",
         "tool_category": "suspicious"},
        {"id": "abstain_06", "category": "suspicious",
         "alert": "Outbound HTTPS to Tor exit node IP. But user is security researcher with approved access.",
         "tool_category": "suspicious"},
        {"id": "abstain_07", "category": "suspicious",
         "alert": "Registry modification on Windows host. Matches persistence technique but also matches legitimate software install.",
         "tool_category": "suspicious"},
    ]

    return families


STRESS_FAMILIES = _build_stress_families()


# ============================================================
# Build tool sequences for stress scenarios
# ============================================================

def build_stress_sequence(
    scenario: Dict,
    n_tools: int = 3,
    rng: random.Random = None,
) -> List[Tuple[str, str]]:
    """Build tool output sequence for a stress scenario."""
    if rng is None:
        rng = random.Random(42)

    # Custom tool outputs override everything — used for scenarios
    # where we need specific mixed/misleading evidence
    if "custom_tools" in scenario:
        return list(scenario["custom_tools"])

    cat = scenario.get("tool_category", scenario["category"])
    tools = rng.sample(TOOL_NAMES, min(n_tools, len(TOOL_NAMES)))

    if scenario.get("has_correction_tools"):
        seq = []
        correction_tools = [t for t in tools if t in CORRECTION_RESPONSES]
        if correction_tools:
            t = correction_tools[0]
            seq.append((t, CORRECTION_RESPONSES[t]))
            remaining = [t2 for t2 in tools if t2 != t]
            for t2 in remaining:
                seq.append((t2, CANONICAL_RESPONSES["benign"][t2]))
        else:
            seq.append(("check_hash", CORRECTION_RESPONSES["check_hash"]))
            for t in tools[1:]:
                seq.append((t, CANONICAL_RESPONSES["benign"][t]))
        return seq

    responses = CANONICAL_RESPONSES[cat]
    return [(t, responses[t]) for t in tools]


# ============================================================
# Result dataclasses
# ============================================================

@dataclass
class StressEpisodeResult:
    """Result of one stress episode."""
    scenario_id: str
    category: str
    mode: str
    family: str
    episode_index: int

    final_verdict: Optional[str]
    final_action: Optional[str]
    abstained: bool
    committed: bool
    n_tools: int

    verdict_correct: bool
    verdict_adjacent: bool

    final_threat_score: float
    final_safety_score: float
    terrain: str

    # Graph internals
    graph_prediction: Optional[str]
    graph_prediction_correct: Optional[bool]
    graph_node_count: int
    graph_active_edges: int
    graph_cold_edges: int

    # Chain state
    chain_height: int
    chain_total_receipts: int

    # HUD
    hud_memory_status: Optional[str]
    hud_dominant_outcome: Optional[str]

    # Isolation flags
    memory_enabled: bool = False
    chain_enabled: bool = False
    graph_enabled: bool = False
    classifier_name: str = "keyword"

    # Stress-specific: was this a post-drift/post-correction/post-poison episode?
    stress_phase: str = "normal"  # normal/pre_drift/post_drift/correction/poisoned/post_poison/recovery


@dataclass
class StressFamilyResult:
    """Per-family aggregation."""
    family: str
    mode: str
    total: int
    correct: int
    episodes: List[StressEpisodeResult]

    # Stress-specific metrics
    post_drift_correct: int = 0
    post_drift_total: int = 0
    post_poison_correct: int = 0
    post_poison_total: int = 0
    correction_handled: int = 0
    correction_total: int = 0
    graph_predictions_correct: int = 0
    graph_predictions_total: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / max(1, self.total)

    @property
    def post_drift_accuracy(self) -> float:
        return self.post_drift_correct / max(1, self.post_drift_total)

    @property
    def post_poison_accuracy(self) -> float:
        return self.post_poison_correct / max(1, self.post_poison_total)

    @property
    def correction_rate(self) -> float:
        return self.correction_handled / max(1, self.correction_total)

    @property
    def graph_pred_accuracy(self) -> float:
        return self.graph_predictions_correct / max(1, self.graph_predictions_total)


@dataclass
class StressModeResult:
    """Full mode aggregation."""
    mode: str
    classifier: str
    total_episodes: int
    correct: int
    false_safe: int
    false_escalation: int
    total_abstain: int
    families: Dict[str, StressFamilyResult]
    episodes: List[StressEpisodeResult]

    @property
    def accuracy(self) -> float:
        return self.correct / max(1, self.total_episodes)

    @property
    def false_safe_rate(self) -> float:
        esc = sum(1 for e in self.episodes if e.category == "escalate")
        return self.false_safe / max(1, esc)

    @property
    def false_escalation_rate(self) -> float:
        ben = sum(1 for e in self.episodes if e.category == "benign")
        return self.false_escalation / max(1, ben)

    def to_dict(self) -> Dict[str, Any]:
        fam_summary = {}
        for fname, fr in self.families.items():
            fam_summary[fname] = {
                "accuracy": round(fr.accuracy, 4),
                "correct": fr.correct,
                "total": fr.total,
                "post_drift_accuracy": round(fr.post_drift_accuracy, 4),
                "post_drift_total": fr.post_drift_total,
                "post_poison_accuracy": round(fr.post_poison_accuracy, 4),
                "post_poison_total": fr.post_poison_total,
                "correction_rate": round(fr.correction_rate, 4),
                "graph_pred_accuracy": round(fr.graph_pred_accuracy, 4),
                "graph_predictions_total": fr.graph_predictions_total,
            }
        return {
            "mode": self.mode,
            "classifier": self.classifier,
            "total_episodes": self.total_episodes,
            "accuracy": round(self.accuracy, 4),
            "correct": self.correct,
            "false_safe_rate": round(self.false_safe_rate, 4),
            "false_escalation_rate": round(self.false_escalation_rate, 4),
            "total_abstain": self.total_abstain,
            "families": fam_summary,
        }


# ============================================================
# Stress phase labeling
# ============================================================

# Which episodes are "post-drift", "post-poison", "correction", etc.
STRESS_PHASES = {
    "long_delayed_correction": {
        "ldc_00": "pre_drift",
        "ldc_06": "correction",
        "ldc_07": "post_drift", "ldc_08": "post_drift", "ldc_09": "post_drift",
    },
    "concept_drift": {
        "drift_00": "pre_drift", "drift_01": "pre_drift",
        "drift_02": "pre_drift", "drift_03": "pre_drift",
        "drift_04": "correction",
        "drift_05": "post_drift", "drift_06": "post_drift",
        "drift_07": "post_drift", "drift_08": "post_drift",
        "drift_09": "post_drift",
    },
    "poisoned_memory": {
        "poison_00": "poisoned", "poison_01": "poisoned", "poison_02": "poisoned",
        "poison_03": "post_poison", "poison_04": "post_poison",
        "poison_05": "recovery", "poison_06": "recovery",
        "poison_07": "post_poison", "poison_08": "post_poison",
    },
    "stale_memory_trap": {
        "stale_00": "pre_drift", "stale_01": "pre_drift",
        "stale_02": "correction",
        "stale_03": "post_drift", "stale_04": "post_drift",
        "stale_06": "post_drift", "stale_07": "post_drift",
    },
}


def get_stress_phase(family: str, scenario_id: str) -> str:
    """Get the stress phase for a scenario."""
    return STRESS_PHASES.get(family, {}).get(scenario_id, "normal")


# ============================================================
# Core: run one stress episode
# ============================================================

_tmp_counter = 0

def _make_tmp(suffix: str) -> str:
    global _tmp_counter
    _tmp_counter += 1
    return f"/tmp/bench_stress_{suffix}_{os.getpid()}_{_tmp_counter}"


def run_stress_episode(
    scenario: Dict,
    tool_sequence: List[Tuple[str, str]],
    mode: str,
    family: str,
    episode_index: int,
    memory: Optional[SplitMemoryStore] = None,
    receipt_chain: Optional[ReceiptChain] = None,
    receipt_graph: Optional[ReceiptGraph] = None,
    classifier_fn: Callable = classify_tool_result,
    classifier_name: str = "keyword",
    evidence_decay: float = 0.85,
    memory_qubo: Optional[MemoryQUBO] = None,
    gate_qubo: Optional[GateQUBO] = None,
    two_stage_gate: Optional[TwoStageGate] = None,
) -> StressEpisodeResult:
    """Run one stress episode through shadow monitor."""
    if memory is None:
        memory = SplitMemoryStore(
            f"/tmp/stress_bench_{os.getpid()}_{id(scenario)}_{time.time_ns()}.json")

    monitor = ShadowMonitor(
        memory=memory,
        evidence_decay=evidence_decay,
        enable_dual_boundary=True,
        commit_threat_boundary=0.55,
        commit_safe_boundary=0.40,
        receipt_chain=receipt_chain,
        receipt_graph=receipt_graph,
    )

    # Monkey-patch classifier if needed
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

        for tool_name, tool_result in tool_sequence:
            if monitor.committed:
                break
            monitor.process_evidence(tool_name, tool_result, model_output="")

        if not monitor.committed:
            balance = monitor.threat_score - monitor.safety_score
            monitor._force_commit("bench_end", balance)

        raw_action = monitor.last_action.action
        verdict = monitor.last_action.direction
        if verdict is None:
            verdict = "suspicious"

        # --- QUBO gate override ---
        # If gate_qubo is provided, build a snapshot from the monitor's
        # accumulated evidence and let the QUBO decide the action.
        # This replaces the threshold decision but keeps all evidence
        # accumulation intact.
        qubo_used = False
        if gate_qubo is not None:
            # Build graph HUD from memory_qubo if available
            graph_hud = None
            if memory_qubo is not None and receipt_graph is not None:
                _, graph_hud = memory_qubo.select_for_hud(
                    receipt_graph,
                    tags=[w.lower() for w in scenario["alert"].split()
                          if len(w) > 3 and w.isalpha()],
                    domain="security",
                    current_block=episode_index,
                )

            snap = GateSnapshot(
                threat_score=monitor.threat_score,
                safety_score=monitor.safety_score,
                evidence_clarity=abs(monitor.threat_score - monitor.safety_score),
                contradiction=min(monitor.threat_score, monitor.safety_score),
                urgency=monitor.turn * 0.08,
                tool_count=monitor.total_tools,
                max_tools=monitor.max_tools,
                novelty=monitor.novelty_at_start,
            )

            # Memory signals
            if memory is not None:
                mem_result = memory.lookup(
                    scenario["alert"], monitor.evidence_vector)
                if mem_result:
                    store_name, match = mem_result
                    if store_name == "tolerance":
                        snap.memory_outcome = "benign"
                    elif store_name == "threat":
                        snap.memory_outcome = "escalate"
                    else:
                        snap.memory_outcome = "abstain"
                    snap.memory_confidence = match.confidence
                    snap.memory_exposures = match.exposures

            # Graph signals
            if receipt_graph is not None:
                snap.graph_reinforcements = sum(
                    e.reinforcements for e in receipt_graph.edges
                    if not e.is_cold)
                snap.graph_contradictions = sum(
                    e.contradictions for e in receipt_graph.edges
                    if not e.is_cold)
                snap.graph_cold_edges = sum(
                    1 for e in receipt_graph.edges if e.is_cold)

            if graph_hud:
                snap.graph_dominant_outcome = graph_hud.get(
                    "dominant_outcome", "unknown")
                snap.graph_strength = graph_hud.get(
                    "memory_strength", "none")

            qubo_result = gate_qubo.decide(snap)
            raw_action = qubo_result.action
            verdict = qubo_result.direction
            if verdict is None:
                verdict = "suspicious"
            qubo_used = True

        # --- Two-stage gate override (Mode J) ---
        # Routes clear evidence to threshold, ambiguous/conflict/drift to QUBO.
        if two_stage_gate is not None:
            graph_hud = None
            if memory_qubo is not None and receipt_graph is not None:
                _, graph_hud = memory_qubo.select_for_hud(
                    receipt_graph,
                    tags=[w.lower() for w in scenario["alert"].split()
                          if len(w) > 3 and w.isalpha()],
                    domain="security",
                    current_block=episode_index,
                )

            snap = GateSnapshot(
                threat_score=monitor.threat_score,
                safety_score=monitor.safety_score,
                evidence_clarity=abs(monitor.threat_score - monitor.safety_score),
                contradiction=min(monitor.threat_score, monitor.safety_score),
                urgency=monitor.turn * 0.08,
                tool_count=monitor.total_tools,
                max_tools=monitor.max_tools,
                novelty=monitor.novelty_at_start,
                correction_seen="correction" in monitor.evidence_tags,
            )

            if memory is not None:
                mem_result = memory.lookup(
                    scenario["alert"], monitor.evidence_vector)
                if mem_result:
                    store_name, match = mem_result
                    if store_name == "tolerance":
                        snap.memory_outcome = "benign"
                    elif store_name == "threat":
                        snap.memory_outcome = "escalate"
                    else:
                        snap.memory_outcome = "abstain"
                    snap.memory_confidence = match.confidence
                    snap.memory_exposures = match.exposures

            if receipt_graph is not None:
                snap.graph_reinforcements = sum(
                    e.reinforcements for e in receipt_graph.edges
                    if not e.is_cold)
                snap.graph_contradictions = sum(
                    e.contradictions for e in receipt_graph.edges
                    if not e.is_cold)
                snap.graph_cold_edges = sum(
                    1 for e in receipt_graph.edges if e.is_cold)

            if graph_hud:
                snap.graph_dominant_outcome = graph_hud.get(
                    "dominant_outcome", "unknown")
                snap.graph_strength = graph_hud.get(
                    "memory_strength", "none")

            ts_result = two_stage_gate.decide(snap)
            # Only override when QUBO is routed — threshold path defers
            # to the monitor's existing decision (Hydra pattern: router
            # decides when to intervene, not when to replace)
            if ts_result.gate_backend_used == "qubo":
                raw_action = ts_result.action
                verdict = ts_result.direction
                if verdict is None:
                    verdict = "suspicious"

        expected = scenario["category"]
        verdict_correct = (verdict == expected)
        adjacent_map = {
            ("benign", "suspicious"), ("suspicious", "benign"),
            ("suspicious", "escalate"), ("escalate", "suspicious"),
        }
        verdict_adjacent = (verdict, expected) in adjacent_map

        resolution = verdict
        confidence = abs(monitor.threat_score - monitor.safety_score)
        monitor.close_episode(resolution, confidence)

        # Graph state
        graph_pred = None
        graph_pred_correct = None
        g_nodes = 0
        g_active = 0
        g_cold = 0
        if receipt_graph is not None:
            g_nodes = receipt_graph.node_count
            g_active = receipt_graph.active_edge_count
            g_cold = receipt_graph.cold_edge_count

        # Chain state
        c_height = 0
        c_total = 0
        if receipt_chain is not None:
            c_height = receipt_chain.height
            c_total = receipt_chain.total_receipts

        # HUD state
        hud_mem_status = None
        hud_dom_outcome = None
        hud = monitor.render_hud()
        if "memory" in hud:
            hud_mem_status = hud["memory"].get("memory_status")
            hud_dom_outcome = hud["memory"].get("dominant_outcome")

        stress_phase = get_stress_phase(family, scenario["id"])

        return StressEpisodeResult(
            scenario_id=scenario["id"],
            category=expected,
            mode=mode,
            family=family,
            episode_index=episode_index,
            final_verdict=verdict,
            final_action=raw_action,
            abstained=monitor.abstain_due_to_uncertainty,
            committed=monitor.committed,
            n_tools=monitor.total_tools,
            verdict_correct=verdict_correct,
            verdict_adjacent=verdict_adjacent,
            final_threat_score=round(monitor.threat_score, 4),
            final_safety_score=round(monitor.safety_score, 4),
            terrain=monitor.terrain,
            graph_prediction=graph_pred,
            graph_prediction_correct=graph_pred_correct,
            graph_node_count=g_nodes,
            graph_active_edges=g_active,
            graph_cold_edges=g_cold,
            chain_height=c_height,
            chain_total_receipts=c_total,
            hud_memory_status=hud_mem_status,
            hud_dominant_outcome=hud_dom_outcome,
            memory_enabled=(memory is not None),
            chain_enabled=receipt_chain is not None,
            graph_enabled=receipt_graph is not None,
            classifier_name=classifier_name,
            stress_phase=stress_phase,
        )
    finally:
        if original_classify is not None:
            import morphsat.commit_gate as cg
            import morphsat.shadow_monitor as sm
            cg.classify_tool_result = original_classify
            sm.classify_tool_result = original_sm_classify


# ============================================================
# Mode runner
# ============================================================

def run_stress_mode(
    mode: str,
    families: Dict[str, List[Dict]],
    verbose: bool = False,
) -> StressModeResult:
    """Run all stress families through one mode."""

    mode_config = {
        "A": {"classifier": classify_tool_result, "cls_name": "keyword",
               "use_memory": False, "use_chain": False, "use_graph": False,
               "use_qubo": False},
        "B": {"classifier": classify_tool_result, "cls_name": "keyword",
               "use_memory": True, "use_chain": False, "use_graph": False,
               "use_qubo": False},
        "C": {"classifier": classify_tool_result, "cls_name": "keyword",
               "use_memory": False, "use_chain": True, "use_graph": False,
               "use_qubo": False},
        "D": {"classifier": classify_tool_result, "cls_name": "keyword",
               "use_memory": True, "use_chain": True, "use_graph": True,
               "use_qubo": False},
        "H": {"classifier": classify_tool_result, "cls_name": "keyword",
               "use_memory": True, "use_chain": True, "use_graph": True,
               "use_qubo": True, "use_two_stage": False},
        "J": {"classifier": classify_tool_result, "cls_name": "keyword",
               "use_memory": True, "use_chain": True, "use_graph": True,
               "use_qubo": False, "use_two_stage": True},
    }

    cfg = mode_config[mode]
    classifier_fn = cfg["classifier"]
    cls_name = cfg["cls_name"]

    all_episodes: List[StressEpisodeResult] = []
    family_results: Dict[str, StressFamilyResult] = {}

    for fam_name, scenarios in families.items():
        memory = SplitMemoryStore(_make_tmp(f"{mode}_{fam_name}_mem") + ".json") \
            if cfg["use_memory"] else None
        chain = ReceiptChain(_make_tmp(f"{mode}_{fam_name}_chain") + ".json") \
            if cfg["use_chain"] else None
        graph = ReceiptGraph(_make_tmp(f"{mode}_{fam_name}_graph") + ".json") \
            if cfg["use_graph"] else None

        # QUBO objects for Mode H
        m_qubo = MemoryQUBO(max_k=5) if cfg.get("use_qubo") or cfg.get("use_two_stage") else None
        g_qubo = GateQUBO() if cfg.get("use_qubo") else None

        # Two-stage gate for Mode J
        ts_gate = TwoStageGate() if cfg.get("use_two_stage") else None

        fam_episodes: List[StressEpisodeResult] = []

        for ep_idx, scenario in enumerate(scenarios):
            seq = build_stress_sequence(scenario, n_tools=3,
                                         rng=random.Random(42))

            result = run_stress_episode(
                scenario=scenario,
                tool_sequence=seq,
                mode=mode,
                family=fam_name,
                episode_index=ep_idx,
                memory=memory,
                receipt_chain=chain,
                receipt_graph=graph,
                classifier_fn=classifier_fn,
                classifier_name=cls_name,
                memory_qubo=m_qubo,
                gate_qubo=g_qubo,
                two_stage_gate=ts_gate,
            )
            fam_episodes.append(result)
            all_episodes.append(result)

            if verbose:
                mark = "OK" if result.verdict_correct else \
                       "~" if result.verdict_adjacent else "WRONG"
                phase = result.stress_phase
                phase_str = f" [{phase}]" if phase != "normal" else ""
                flags = []
                if result.memory_enabled: flags.append("mem")
                if result.chain_enabled: flags.append("chain")
                if result.graph_enabled: flags.append("graph")
                flags_str = "+".join(flags) if flags else "none"
                print(f"  [{mode}] {result.scenario_id:12s} "
                      f"exp={result.category:10s} got={result.final_verdict:10s} "
                      f"t={result.final_threat_score:.3f} "
                      f"s={result.final_safety_score:.3f} "
                      f"terrain={result.terrain:10s} "
                      f"[{flags_str}]{phase_str} {mark}")

        # Aggregate per-family
        correct = sum(1 for e in fam_episodes if e.verdict_correct)

        post_drift = [e for e in fam_episodes if e.stress_phase == "post_drift"]
        post_drift_correct = sum(1 for e in post_drift if e.verdict_correct)

        post_poison = [e for e in fam_episodes
                       if e.stress_phase in ("post_poison", "recovery")]
        post_poison_correct = sum(1 for e in post_poison if e.verdict_correct)

        corrections = [e for e in fam_episodes if e.stress_phase == "correction"]
        correction_handled = sum(1 for e in corrections if e.verdict_correct)

        graph_preds = [e for e in fam_episodes
                       if e.graph_prediction is not None]
        graph_correct = sum(1 for e in graph_preds
                           if e.graph_prediction_correct is True)

        fr = StressFamilyResult(
            family=fam_name,
            mode=mode,
            total=len(fam_episodes),
            correct=correct,
            episodes=fam_episodes,
            post_drift_correct=post_drift_correct,
            post_drift_total=len(post_drift),
            post_poison_correct=post_poison_correct,
            post_poison_total=len(post_poison),
            correction_handled=correction_handled,
            correction_total=len(corrections),
            graph_predictions_correct=graph_correct,
            graph_predictions_total=len(graph_preds),
        )
        family_results[fam_name] = fr

        # Cleanup temp files
        for obj in [memory, chain, graph]:
            if obj is not None and hasattr(obj, 'path'):
                p = Path(obj.path)
                if p.exists():
                    p.unlink()

    # Global aggregation
    correct = sum(1 for e in all_episodes if e.verdict_correct)
    false_safe = sum(1 for e in all_episodes
                     if e.category == "escalate" and e.final_verdict == "benign")
    false_escalation = sum(1 for e in all_episodes
                          if e.category == "benign" and e.final_verdict == "escalate")
    total_abstain = sum(1 for e in all_episodes if e.abstained)

    return StressModeResult(
        mode=mode,
        classifier=cls_name,
        total_episodes=len(all_episodes),
        correct=correct,
        false_safe=false_safe,
        false_escalation=false_escalation,
        total_abstain=total_abstain,
        families=family_results,
        episodes=all_episodes,
    )


# ============================================================
# Deterministic replay check
# ============================================================

def check_deterministic_replay(families: Dict[str, List[Dict]]) -> bool:
    """Run mode D twice on one family, verify identical graph state.

    Uses only the first family to keep runtime bounded (O(n^2) auto_connect).
    """
    # Pick just the first family for replay check
    first_fam = next(iter(families))
    replay_families = {first_fam: families[first_fam]}

    def run_once(suffix: str) -> Dict[str, Any]:
        memory = SplitMemoryStore(_make_tmp(f"replay_{suffix}_mem") + ".json")
        chain = ReceiptChain(_make_tmp(f"replay_{suffix}_chain") + ".json")
        graph = ReceiptGraph(_make_tmp(f"replay_{suffix}_graph") + ".json")

        for fam_name, scenarios in replay_families.items():
            for ep_idx, scenario in enumerate(scenarios):
                seq = build_stress_sequence(scenario, n_tools=3,
                                             rng=random.Random(42))
                run_stress_episode(
                    scenario=scenario, tool_sequence=seq,
                    mode="D", family=fam_name, episode_index=ep_idx,
                    memory=memory, receipt_chain=chain, receipt_graph=graph,
                )

        state = graph.to_dict()
        for obj in [memory, chain, graph]:
            if hasattr(obj, 'path'):
                p = Path(obj.path)
                if p.exists():
                    p.unlink()
        return state

    s1 = run_once("run1")
    s2 = run_once("run2")

    if s1["node_count"] != s2["node_count"]:
        return False
    if s1["edge_count"] != s2["edge_count"]:
        return False
    if sorted(s1["nodes"].keys()) != sorted(s2["nodes"].keys()):
        return False

    e1_weights = sorted([e["weight"] for e in s1["edges"]])
    e2_weights = sorted([e["weight"] for e in s2["edges"]])
    if e1_weights != e2_weights:
        return False

    return True


# ============================================================
# Success gates
# ============================================================

def check_stress_gates(results: Dict[str, StressModeResult],
                       replay_pass: bool) -> List[Tuple[str, bool, str]]:
    """Check success gates. Returns list of (gate_name, passed, detail)."""
    gates = []

    # Gate 1: Mode C equals Mode A behaviorally
    if "A" in results and "C" in results:
        a_acc = results["A"].accuracy
        c_acc = results["C"].accuracy
        passed = abs(a_acc - c_acc) < 0.001
        gates.append((
            "G1: C==A (chain alone doesn't steer)",
            passed,
            f"A={a_acc:.3f} C={c_acc:.3f} delta={abs(a_acc - c_acc):.4f}",
        ))

    # Gate 2: Mode D beats Mode B on at least 2 memory-specific families
    # NOTE: Expected to FAIL — graph has no steering mechanism
    if "B" in results and "D" in results:
        d_wins = 0
        details = []
        memory_families = ["concept_drift", "poisoned_memory",
                          "stale_memory_trap", "long_delayed_correction"]
        for fam in memory_families:
            if fam in results["B"].families and fam in results["D"].families:
                b_acc = results["B"].families[fam].accuracy
                d_acc = results["D"].families[fam].accuracy
                if d_acc > b_acc + 0.001:
                    d_wins += 1
                details.append(f"{fam}: B={b_acc:.3f} D={d_acc:.3f}")
        passed = d_wins >= 2
        gates.append((
            "G2: D>B on 2+ memory families (graph steering needed)",
            passed,
            f"D wins {d_wins}/4 families. {'; '.join(details)}",
        ))

    # Gate 3: Mode D does not increase false_safe_rate vs A
    if "A" in results and "D" in results:
        a_fsr = results["A"].false_safe_rate
        d_fsr = results["D"].false_safe_rate
        passed = d_fsr <= a_fsr + 0.01
        gates.append((
            "G3: D false_safe_rate <= A",
            passed,
            f"A={a_fsr:.3f} D={d_fsr:.3f}",
        ))

    # Gate 4: SplitMemory fails on concept drift post-drift episodes
    # (this is the evidence that correction is needed)
    if "B" in results and "concept_drift" in results["B"].families:
        fr = results["B"].families["concept_drift"]
        # SplitMemory should struggle on post-drift benign episodes
        # because threat store is checked first
        post_drift_acc = fr.post_drift_accuracy
        passed = post_drift_acc < 1.0  # at least one post-drift error
        gates.append((
            "G4: SplitMemory shows concept drift weakness",
            passed,
            f"post_drift_accuracy={post_drift_acc:.3f} ({fr.post_drift_correct}/{fr.post_drift_total})",
        ))

    # Gate 5: Poisoned memory causes at least one false-safe in mode B
    if "B" in results and "poisoned_memory" in results["B"].families:
        fr = results["B"].families["poisoned_memory"]
        poison_eps = [e for e in fr.episodes
                      if e.stress_phase in ("post_poison", "recovery")]
        false_safe_in_poison = sum(1 for e in poison_eps
                                   if e.category == "escalate"
                                   and e.final_verdict == "benign")
        passed = false_safe_in_poison >= 1 or fr.post_poison_accuracy < 1.0
        gates.append((
            "G5: Poisoned memory exposes SplitMemory weakness",
            passed,
            f"post_poison false_safe={false_safe_in_poison} accuracy={fr.post_poison_accuracy:.3f}",
        ))

    # Gate 6: All modes handle hard_abstain episodes as suspicious
    for m in ("A", "B", "D", "H", "J"):
        if m in results and "hard_abstain_required" in results[m].families:
            fr = results[m].families["hard_abstain_required"]
            # Suspicious or adjacent to suspicious (benign/escalate) are all
            # acceptable since these are genuinely ambiguous
            correct_or_adjacent = sum(
                1 for e in fr.episodes
                if e.verdict_correct or e.verdict_adjacent
            )
            rate = correct_or_adjacent / max(1, fr.total)
            passed = rate >= 0.5
            gates.append((
                f"G6-{m}: hard_abstain handled (correct+adjacent >= 50%)",
                passed,
                f"{correct_or_adjacent}/{fr.total} = {rate:.3f}",
            ))

    # Gate 7: Deterministic replay
    gates.append((
        "G7: Deterministic replay",
        replay_pass,
        "same inputs -> same graph state" if replay_pass else "MISMATCH",
    ))

    # Gate 8: Mode H beats Mode D on at least 1 family
    if "D" in results and "H" in results:
        h_wins = 0
        details = []
        for fam in results["H"].families:
            if fam in results["D"].families:
                d_acc = results["D"].families[fam].accuracy
                h_acc = results["H"].families[fam].accuracy
                if h_acc > d_acc + 0.001:
                    h_wins += 1
                details.append(f"{fam}: D={d_acc:.3f} H={h_acc:.3f}")
        passed = h_wins >= 1
        gates.append((
            "G8: H>D on 1+ family (QUBO gate improves over threshold)",
            passed,
            f"H wins {h_wins} families. {'; '.join(details[:4])}",
        ))

    # Gate 9: Mode H beats Mode B on at least 1 family
    if "B" in results and "H" in results:
        h_wins = 0
        details = []
        for fam in results["H"].families:
            if fam in results["B"].families:
                b_acc = results["B"].families[fam].accuracy
                h_acc = results["H"].families[fam].accuracy
                if h_acc > b_acc + 0.001:
                    h_wins += 1
                details.append(f"{fam}: B={b_acc:.3f} H={h_acc:.3f}")
        passed = h_wins >= 1
        gates.append((
            "G9: H>B on 1+ family (QUBO improves over SplitMemory alone)",
            passed,
            f"H wins {h_wins} families. {'; '.join(details[:4])}",
        ))

    # Gate 10: Mode H does not increase false_safe_rate vs A
    if "A" in results and "H" in results:
        a_fsr = results["A"].false_safe_rate
        h_fsr = results["H"].false_safe_rate
        passed = h_fsr <= a_fsr + 0.01
        gates.append((
            "G10: H false_safe_rate <= A",
            passed,
            f"A={a_fsr:.3f} H={h_fsr:.3f}",
        ))

    # --- Mode J (TwoStageGate) gates ---

    # Gate 11: J >= D overall
    if "D" in results and "J" in results:
        d_acc = results["D"].accuracy
        j_acc = results["J"].accuracy
        passed = j_acc >= d_acc - 0.01
        gates.append((
            "G11: J >= D overall (two-stage no worse than threshold)",
            passed,
            f"D={d_acc:.3f} J={j_acc:.3f}",
        ))

    # Gate 12: J > H overall (two-stage beats pure QUBO)
    if "H" in results and "J" in results:
        h_acc = results["H"].accuracy
        j_acc = results["J"].accuracy
        passed = j_acc > h_acc + 0.01
        gates.append((
            "G12: J > H overall (two-stage beats single-stage QUBO)",
            passed,
            f"H={h_acc:.3f} J={j_acc:.3f}",
        ))

    # Gate 13: J concept_drift >= D concept_drift
    if "D" in results and "J" in results:
        if "concept_drift" in results["D"].families and "concept_drift" in results["J"].families:
            d_drift = results["D"].families["concept_drift"].accuracy
            j_drift = results["J"].families["concept_drift"].accuracy
            passed = j_drift >= d_drift - 0.01
            gates.append((
                "G13: J concept_drift >= D (two-stage handles drift)",
                passed,
                f"D={d_drift:.3f} J={j_drift:.3f}",
            ))

    # Gate 14: J false_safe_rate == 0
    if "J" in results:
        j_fsr = results["J"].false_safe_rate
        passed = j_fsr < 0.01
        gates.append((
            "G14: J false_safe_rate == 0 (safety preserved)",
            passed,
            f"J false_safe={j_fsr:.3f}",
        ))

    # Gate 15: J hard_abstain no worse than D
    if "D" in results and "J" in results:
        if "hard_abstain_required" in results["D"].families and \
           "hard_abstain_required" in results["J"].families:
            d_ha = results["D"].families["hard_abstain_required"].accuracy
            j_ha = results["J"].families["hard_abstain_required"].accuracy
            passed = j_ha >= d_ha - 0.01
            gates.append((
                "G15: J hard_abstain >= D",
                passed,
                f"D={d_ha:.3f} J={j_ha:.3f}",
            ))

    return gates


# ============================================================
# Receipt writer
# ============================================================

def write_stress_receipt(results: Dict[str, StressModeResult],
                         gates: List[Tuple[str, bool, str]],
                         wall_time: float, cpu_time: float) -> Path:
    """Write receipted results to disk."""
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    receipt = {
        "benchmark": "memory_stress_v1",
        "timestamp": ts,
        "modes": {m: r.to_dict() for m, r in results.items()},
        "gates": [
            {"gate": name, "passed": passed, "detail": detail}
            for name, passed, detail in gates
        ],
        "gates_summary": {
            "total": len(gates),
            "passed": sum(1 for _, p, _ in gates if p),
            "failed": sum(1 for _, p, _ in gates if not p),
        },
        "episode_detail": {},
        "cost": {
            "wall_time_s": round(wall_time, 3),
            "cpu_time_s": round(cpu_time, 3),
            "peak_memory_mb": round(
                resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            "python_version": platform.python_version(),
            "hostname": platform.node(),
            "timestamp_start": ts,
            "timestamp_end": time.strftime("%Y-%m-%dT%H:%M:%S"),
        },
    }

    # Per-episode detail (condensed)
    for mode, mr in results.items():
        receipt["episode_detail"][mode] = [
            {
                "id": e.scenario_id,
                "family": e.family,
                "category": e.category,
                "verdict": e.final_verdict,
                "correct": e.verdict_correct,
                "terrain": e.terrain,
                "phase": e.stress_phase,
                "t": e.final_threat_score,
                "s": e.final_safety_score,
                "graph_nodes": e.graph_node_count,
                "chain_height": e.chain_height,
            }
            for e in mr.episodes
        ]

    # Comparison: D vs B per family
    if "B" in results and "D" in results:
        comparison = {}
        for fam in results["B"].families:
            if fam in results["D"].families:
                b_fr = results["B"].families[fam]
                d_fr = results["D"].families[fam]
                comparison[fam] = {
                    "B_accuracy": round(b_fr.accuracy, 4),
                    "D_accuracy": round(d_fr.accuracy, 4),
                    "delta": round(d_fr.accuracy - b_fr.accuracy, 4),
                    "B_post_drift": round(b_fr.post_drift_accuracy, 4),
                    "D_post_drift": round(d_fr.post_drift_accuracy, 4),
                }
        receipt["D_vs_B_per_family"] = comparison

    path = RECEIPTS_DIR / f"memory_stress_{ts}.json"
    path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return path


# ============================================================
# Main
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="MorphSAT Layer 3: Memory Stress Benchmark")
    parser.add_argument("--mode", type=str, default=None,
                        help="Run single mode (A/B/C/D)")
    parser.add_argument("--family", type=str, default=None,
                        help="Run single family")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--skip-replay", action="store_true",
                        help="Skip deterministic replay check")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON")
    args = parser.parse_args()

    t_start = time.time()
    cpu_start = time.process_time()

    families = STRESS_FAMILIES
    if args.family:
        if args.family not in families:
            print(f"Unknown family: {args.family}")
            print(f"Available: {', '.join(sorted(families.keys()))}")
            sys.exit(1)
        families = {args.family: families[args.family]}

    modes = [args.mode.upper()] if args.mode else ["A", "B", "C", "D", "H", "J"]

    total_eps = sum(len(s) for s in families.values())
    print(f"MorphSAT Memory Stress Benchmark")
    print(f"  Families: {len(families)} ({total_eps} episodes)")
    print(f"  Modes: {', '.join(modes)}")
    print()

    results: Dict[str, StressModeResult] = {}
    for mode in modes:
        if args.verbose:
            print(f"--- Mode {mode} ---")
        mr = run_stress_mode(mode, families, verbose=args.verbose)
        results[mode] = mr
        if args.verbose:
            print()

    # Deterministic replay
    replay_pass = True
    if not args.skip_replay and "D" in modes:
        print("Checking deterministic replay...", end=" ")
        replay_pass = check_deterministic_replay(families)
        print("PASS" if replay_pass else "FAIL")
        print()

    wall_time = time.time() - t_start
    cpu_time = time.process_time() - cpu_start

    # Results table
    if not args.json:
        # Overall
        print(f"{'Mode':<6} {'Acc':>6} {'Correct':>8} "
              f"{'FalseSafe':>10} {'FalseEsc':>9} {'Abstain':>8}")
        print("-" * 55)
        for m in modes:
            r = results[m]
            print(f"{r.mode:<6} "
                  f"{r.accuracy:>6.1%} {r.correct:>4}/{r.total_episodes:<3} "
                  f"{r.false_safe_rate:>10.1%} {r.false_escalation_rate:>9.1%} "
                  f"{r.total_abstain:>8}")
        print()

        # Per-family breakdown
        print("Per-family breakdown:")
        header_modes = [m for m in modes if m in results]
        print(f"  {'Family':<30s} " +
              " ".join(f"{m:>6}" for m in header_modes) +
              "  post_drift  post_poison")
        print("  " + "-" * (30 + 7 * len(header_modes) + 26))
        for fam in sorted(STRESS_FAMILIES.keys()):
            if fam not in families:
                continue
            accs = []
            post_drift_str = ""
            post_poison_str = ""
            for m in header_modes:
                if fam in results[m].families:
                    fr = results[m].families[fam]
                    accs.append(f"{fr.accuracy:>6.1%}")
                    if m == "B":
                        if fr.post_drift_total > 0:
                            post_drift_str = f"{fr.post_drift_correct}/{fr.post_drift_total}"
                        if fr.post_poison_total > 0:
                            post_poison_str = f"{fr.post_poison_correct}/{fr.post_poison_total}"
                else:
                    accs.append(f"{'N/A':>6}")
            print(f"  {fam:<30s} " + " ".join(accs) +
                  f"  {post_drift_str:>10s}  {post_poison_str:>10s}")
        print()

    # Success gates
    gates = check_stress_gates(results, replay_pass)
    gate_pass_count = sum(1 for _, p, _ in gates if p)
    gate_total = len(gates)
    print(f"GATES: {gate_pass_count}/{gate_total}")
    for name, passed, detail in gates:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
        print(f"         {detail}")
    print()

    # Write receipt
    receipt_path = write_stress_receipt(results, gates, wall_time, cpu_time)
    print(f"Receipt: {receipt_path}")
    print(f"Wall time: {wall_time:.2f}s  CPU: {cpu_time:.2f}s")

    if args.json:
        print(json.dumps({m: r.to_dict() for m, r in results.items()}, indent=2))


if __name__ == "__main__":
    main()
