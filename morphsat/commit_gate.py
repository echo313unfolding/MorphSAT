"""
MorphSAT v6 Commit Gate — metacognitive commit control for local agents.

The research question: When should an agent stop gathering evidence and commit?

Architecture:
    FSA = legal lifecycle skeleton (what transitions are allowed)
    CommitGate = decision timing (when to stop investigating)
    Memory = learned context (threat patterns + tolerance patterns)
    Receipt = proof of why the gate fired (the strange loop closes here)

The strange loop (Hofstadter / AGI equation lineage):
    agent acts → gate records receipt → memory learns pattern
    → future threshold modulated by memory → different behavior → new receipt

Three actions:
    CONTINUE  — evidence incomplete, keep investigating
    COMMIT    — enough evidence for verdict (benign/suspicious/escalate)
    ABSTAIN   — contradictory evidence, defer to human/escalate

Bidirectional pressure:
    threat evidence  → threat_score ↑
    safety evidence  → safety_score ↑
    urgency         → commit_pressure ↑ (time cost of continuing)
    coincidence     → boost when multiple signals converge

Commit logic:
    commit_pressure = urgency + evidence_clarity + coincidence
    evidence_clarity = |threat_score - safety_score|
    contradiction = min(threat_score, safety_score)

    if commit_pressure >= threshold:
        if contradiction >= contradiction_threshold → ABSTAIN
        elif threat_score > safety_score → COMMIT(escalate)
        elif safety_score > threat_score → COMMIT(benign)
        else → COMMIT(suspicious)

Lineage: AGI equation Ξ(t) → GuardianCell Θ(cᵢ) → MorphSAT FSA
         → PressureGate v4 → PatternMemory v5 → CommitGate v6
"""

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Memory Stores (split threat / tolerance)
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    """One learned pattern in threat or tolerance memory."""
    pattern_hash: str
    resolution: str             # benign | suspicious | escalate | abstain
    confidence: float           # 0.0-1.0
    exposures: int = 1
    first_seen: str = ""
    last_seen: str = ""
    evidence_signature: List = field(default_factory=list)
    alert_keywords: List[str] = field(default_factory=list)
    avg_turns_to_resolve: float = 0.0
    avg_threat_score: float = 0.0
    avg_safety_score: float = 0.0


class SplitMemoryStore:
    """Separate threat memory from tolerance memory.

    v5 failed because it learned 7 escalate / 0 benign patterns.
    v6 splits the store so tolerance can accumulate independently.
    """

    def __init__(self, store_path: str = "commit_gate_memory.json"):
        self.store_path = Path(store_path)
        self.threat: Dict[str, MemoryEntry] = {}
        self.tolerance: Dict[str, MemoryEntry] = {}
        self.abstain: Dict[str, MemoryEntry] = {}
        self._load()

    def _load(self):
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
                for section, store in [
                    ("threat", self.threat),
                    ("tolerance", self.tolerance),
                    ("abstain", self.abstain),
                ]:
                    for h, entry in data.get(section, {}).items():
                        if "evidence_signature" in entry:
                            entry["evidence_signature"] = [
                                tuple(x) if isinstance(x, list) else x
                                for x in entry["evidence_signature"]
                            ]
                        store[h] = MemoryEntry(**entry)
            except (json.JSONDecodeError, TypeError):
                pass

    def _save(self):
        data = {"threat": {}, "tolerance": {}, "abstain": {}}
        for section, store in [
            ("threat", self.threat),
            ("tolerance", self.tolerance),
            ("abstain", self.abstain),
        ]:
            for h, entry in store.items():
                d = asdict(entry)
                d["evidence_signature"] = [
                    list(x) if isinstance(x, tuple) else x
                    for x in d["evidence_signature"]
                ]
                data[section][h] = d
        self.store_path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def hash_evidence(evidence_signature: List[Tuple[str, str]]) -> str:
        canonical = sorted(evidence_signature)
        blob = json.dumps(canonical, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def lookup(self, alert_text: str,
               evidence_so_far: List[Tuple[str, str]]) -> Optional[Tuple[str, MemoryEntry]]:
        """Look up pattern across all stores. Returns (store_name, entry) or None."""
        if evidence_so_far:
            h = self.hash_evidence(evidence_so_far)
            for name, store in [("threat", self.threat),
                                ("tolerance", self.tolerance),
                                ("abstain", self.abstain)]:
                if h in store:
                    return (name, store[h])

        # Fuzzy match on keywords
        alert_lower = alert_text.lower()
        best_match = None
        best_overlap = 0
        best_store = None
        for name, store in [("threat", self.threat),
                            ("tolerance", self.tolerance),
                            ("abstain", self.abstain)]:
            for entry in store.values():
                if not entry.alert_keywords:
                    continue
                overlap = sum(1 for kw in entry.alert_keywords if kw in alert_lower)
                ratio = overlap / max(len(entry.alert_keywords), 1)
                if ratio > 0.5 and overlap > best_overlap:
                    best_overlap = overlap
                    best_match = entry
                    best_store = name
        if best_match:
            return (best_store, best_match)
        return None

    def novelty_distance(self, alert_text: str) -> float:
        """How far from nearest known pattern (0.0=identical, 1.0=completely novel)."""
        all_entries = list(self.threat.values()) + list(self.tolerance.values()) + list(self.abstain.values())
        if not all_entries:
            return 1.0
        alert_lower = alert_text.lower()
        best_overlap = 0.0
        for entry in all_entries:
            if not entry.alert_keywords:
                continue
            overlap = sum(1 for kw in entry.alert_keywords if kw in alert_lower)
            ratio = overlap / max(len(entry.alert_keywords), 1)
            best_overlap = max(best_overlap, ratio)
        return 1.0 - best_overlap

    def record_episode(self, evidence_signature: List[Tuple[str, str]],
                       resolution: str, confidence: float,
                       alert_text: str, threat_score: float,
                       safety_score: float, turns: int):
        """Write pattern to the appropriate store after episode resolves.

        This is where the strange loop closes:
        receipt → memory → future behavior change.
        """
        h = self.hash_evidence(evidence_signature)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        keywords = [w.lower() for w in alert_text.split()
                    if len(w) > 3 and w.isalpha()]

        # Route to correct store
        if resolution == "abstain":
            store = self.abstain
        elif resolution == "benign":
            store = self.tolerance
        else:  # suspicious or escalate
            store = self.threat

        if h in store:
            entry = store[h]
            entry.exposures += 1
            entry.last_seen = now
            n = entry.exposures
            entry.confidence = (entry.confidence * (n - 1) + confidence) / n
            entry.avg_turns_to_resolve = (entry.avg_turns_to_resolve * (n - 1) + turns) / n
            entry.avg_threat_score = (entry.avg_threat_score * (n - 1) + threat_score) / n
            entry.avg_safety_score = (entry.avg_safety_score * (n - 1) + safety_score) / n
            existing_kw = set(entry.alert_keywords)
            entry.alert_keywords = list(existing_kw | set(keywords))
        else:
            store[h] = MemoryEntry(
                pattern_hash=h,
                resolution=resolution,
                confidence=confidence,
                exposures=1,
                first_seen=now,
                last_seen=now,
                evidence_signature=evidence_signature,
                alert_keywords=keywords,
                avg_turns_to_resolve=float(turns),
                avg_threat_score=threat_score,
                avg_safety_score=safety_score,
            )
        self._save()

    def clear(self):
        self.threat = {}
        self.tolerance = {}
        self.abstain = {}
        if self.store_path.exists():
            self.store_path.unlink()

    def to_receipt(self) -> dict:
        return {
            "threat_patterns": len(self.threat),
            "tolerance_patterns": len(self.tolerance),
            "abstain_patterns": len(self.abstain),
            "total_exposures": sum(
                e.exposures for store in [self.threat, self.tolerance, self.abstain]
                for e in store.values()
            ),
        }


# ---------------------------------------------------------------------------
# Evidence Sensors (bidirectional)
# ---------------------------------------------------------------------------

# Threat indicators — push threat_score UP
THREAT_SIGNALS = {
    "yara_match": 0.35,
    "unexpected": 0.25,
    "outbound_port": 0.30,
    "critical_cve": 0.35,
    "not_in_known_good": 0.20,
    "unsigned": 0.15,
    "obfuscated": 0.30,
    "persistence": 0.25,
    "lateral_movement": 0.30,
}

# Safety indicators — push safety_score UP
SAFETY_SIGNALS = {
    "baseline_match": 0.30,
    "known_good": 0.30,
    "signed_binary": 0.25,
    "scheduled_task": 0.20,
    "expected_port": 0.20,
    "clean": 0.20,
    "approved_user": 0.25,
    "normal_parent": 0.20,
    "patched": 0.15,
}

# Ambiguous — adds to both slightly (increases contradiction)
AMBIGUOUS_SIGNALS = {
    "ambiguous": (0.05, 0.05),
    "moderate_signal": (0.10, 0.05),
    "unknown": (0.05, 0.05),
}


def classify_tool_result(tool_result: str) -> Tuple[str, float, float]:
    """Classify a tool result into (category, threat_delta, safety_delta).

    Returns bidirectional scores — threat evidence and safety evidence
    are tracked separately, not as a single axis.

    IMPORTANT: Threat signals are checked FIRST because negation-containing
    strings like "unexpected" would false-match safety patterns like "expected".
    Order: threat → negation-safe safety → ambiguous → default.
    """
    text_lower = tool_result.lower()

    # --- THREAT signals first (catches negations before safety) ---
    # Specific indicators BEFORE generic "unexpected" to avoid over-collapsing

    if any(kw in text_lower for kw in ["yara", "suspicious_packer"]):
        return "yara_match", THREAT_SIGNALS["yara_match"], 0.0

    if any(kw in text_lower for kw in ["4444", "not in baseline"]):
        return "outbound_port", THREAT_SIGNALS["outbound_port"], 0.0

    if any(kw in text_lower for kw in ["unexpected", "unusual", "anomalous"]):
        return "unexpected", THREAT_SIGNALS["unexpected"], 0.0

    if any(kw in text_lower for kw in ["cvss 9", "exploit available", "remote code"]):
        return "critical_cve", THREAT_SIGNALS["critical_cve"], 0.0

    if any(kw in text_lower for kw in ["not found in known-good", "not in known-good"]):
        return "not_in_known_good", THREAT_SIGNALS["not_in_known_good"], 0.0

    if any(kw in text_lower for kw in ["not signed", "unsigned"]):
        return "unsigned", THREAT_SIGNALS["unsigned"], 0.0

    if any(kw in text_lower for kw in ["obfuscated", "base64", "encoded"]):
        return "obfuscated", THREAT_SIGNALS["obfuscated"], 0.0

    # --- SAFETY signals (only after threat negations ruled out) ---

    if any(kw in text_lower for kw in [
        "all match baseline", "all processes within expected",
        "no anomalies", "within expected"
    ]):
        return "baseline_match", 0.0, SAFETY_SIGNALS["baseline_match"]

    if any(kw in text_lower for kw in [
        "known-good", "signed and in package", "package database",
        "matches known-good"
    ]):
        return "known_good", 0.0, SAFETY_SIGNALS["known_good"]

    if any(kw in text_lower for kw in ["verified signature"]):
        return "signed_binary", 0.0, SAFETY_SIGNALS["signed_binary"]

    # "scheduled" and "routine" are safe; "expected" alone is NOT checked
    # (would false-match "unexpected")
    if any(kw in text_lower for kw in ["scheduled", "routine"]):
        return "scheduled_task", 0.0, SAFETY_SIGNALS["scheduled_task"]

    if any(kw in text_lower for kw in ["no critical", "patched", "up to date"]):
        return "patched", 0.0, SAFETY_SIGNALS["patched"]

    if any(kw in text_lower for kw in ["no match", "no rule match"]):
        return "clean", 0.0, SAFETY_SIGNALS["clean"]

    # "outbound" without "not in baseline" is moderate threat
    if "outbound" in text_lower:
        return "outbound_port", THREAT_SIGNALS["outbound_port"], 0.0

    # --- AMBIGUOUS ---

    if any(kw in text_lower for kw in ["ambiguous", "unclear"]):
        return "ambiguous", 0.05, 0.05

    if any(kw in text_lower for kw in ["not in malware", "seen before", "cvss 5"]):
        return "moderate_signal", 0.10, 0.05

    # Default: slight ambiguity
    return "unknown", 0.05, 0.05


def se_classify_complexity(alert_text: str) -> str:
    """Se-proxy: classify alert complexity from text."""
    text_lower = alert_text.lower()

    HIGH_KW = [
        "sequence detected", "chain", "lateral movement", "privilege escalation",
        "multi", "stage", "obfuscated", "base64", "exec(", "postinstall",
        "typosquat", "payload", "certutil", "regsvr32",
    ]
    LOW_KW = [
        "scheduled", "maintenance", "unattended-upgrades", "certificate rotation",
        "certbot", "pentest", "approved", "engagement", "dr runbook",
        "failover", "red team", "timezone", "utc+",
    ]

    high_hits = sum(1 for kw in HIGH_KW if kw in text_lower)
    low_hits = sum(1 for kw in LOW_KW if kw in text_lower)

    if high_hits >= 2:
        return "high"
    elif low_hits >= 2 or (low_hits >= 1 and high_hits == 0):
        return "low"
    else:
        return "medium"


def sidecar_confidence(model_output: str) -> Tuple[float, float]:
    """Sidecar-proxy: estimate model confidence direction.

    Returns (threat_confidence, safety_confidence) — how confident
    the model sounds about threat vs safety.
    """
    import re
    text_lower = model_output.lower()

    THREAT_PATTERNS = [
        r"(clearly malicious|definitely suspicious|confirmed attack)",
        r"(strong indicator|definitive threat|conclusive evidence of)",
        r"(this is (a )?compromise|this is (a )?attack|escalat)",
    ]
    SAFETY_PATTERNS = [
        r"(clearly benign|definitely safe|confirmed normal)",
        r"(this is (a )?(standard|normal|routine|known|legitimate))",
        r"(no threat|no concern|approved|authorized|expected)",
    ]
    UNCERTAIN_PATTERNS = [
        r"(unclear|ambiguous|uncertain|not sure|hard to tell)",
        r"(could be|might be|possibly|potentially)",
        r"(need more|further investigation|additional)",
    ]

    threat_conf = sum(1 for p in THREAT_PATTERNS if re.search(p, text_lower))
    safety_conf = sum(1 for p in SAFETY_PATTERNS if re.search(p, text_lower))
    uncertain = sum(1 for p in UNCERTAIN_PATTERNS if re.search(p, text_lower))

    if uncertain > 0:
        return 0.0, 0.0

    t = min(0.15, threat_conf * 0.07) if threat_conf > 0 else 0.0
    s = min(0.15, safety_conf * 0.07) if safety_conf > 0 else 0.0
    return t, s


# ---------------------------------------------------------------------------
# Coincidence Detection (bidirectional)
# ---------------------------------------------------------------------------

THREAT_COINCIDENCES = {
    "reverse_shell": {
        "requires": ["unexpected", "outbound_port"],
        "bonus": 0.25,
    },
    "full_compromise": {
        "requires": ["unexpected", "outbound_port", "yara_match"],
        "bonus": 0.35,
    },
    "supply_chain": {
        "requires": ["unexpected", "critical_cve"],
        "bonus": 0.20,
    },
}

SAFETY_COINCIDENCES = {
    "routine_maintenance": {
        "requires": ["baseline_match", "known_good"],
        "bonus": 0.25,
    },
    "clean_system": {
        "requires": ["baseline_match", "known_good", "clean"],
        "bonus": 0.30,
    },
    "approved_operation": {
        "requires": ["scheduled_task", "signed_binary"],
        "bonus": 0.20,
    },
}


def coincidence_check(evidence_tags: List[str]) -> Tuple[float, float]:
    """Check for multi-signal coincidence patterns.

    Returns (threat_coincidence_bonus, safety_coincidence_bonus).
    Supralinear: bonus is ON TOP of individual evidence scores.
    """
    threat_bonus = 0.0
    for pattern in THREAT_COINCIDENCES.values():
        if all(tag in evidence_tags for tag in pattern["requires"]):
            threat_bonus = max(threat_bonus, pattern["bonus"])

    safety_bonus = 0.0
    for pattern in SAFETY_COINCIDENCES.values():
        if all(tag in evidence_tags for tag in pattern["requires"]):
            safety_bonus = max(safety_bonus, pattern["bonus"])

    return threat_bonus, safety_bonus


# ---------------------------------------------------------------------------
# Novelty Sensor (∇Ω) — threshold modulator
# ---------------------------------------------------------------------------

def nabla_omega(memory: SplitMemoryStore, alert_text: str,
                evidence_so_far: List[Tuple[str, str]]) -> float:
    """Novelty detector — threshold multiplier.

    v6.1 fix: unknown/novel is NEUTRAL (1.0), not penalized.
    Only learned patterns LOWER the threshold (sensitization).
    Cold start = baseline behavior, not harder behavior.

    < 1.0 → known pattern, sensitized (lower threshold, commit faster)
    = 1.0 → neutral / unknown / novel
    """
    result = memory.lookup(alert_text, evidence_so_far)

    if result:
        store_name, match = result
        if match.exposures >= 3:
            return max(0.65, 1.0 - match.confidence * 0.25)
        elif match.exposures >= 1:
            return max(0.80, 1.0 - match.confidence * 0.12)

    # v6.1: novel = neutral, not penalized
    return 1.0


# ---------------------------------------------------------------------------
# CommitGate v6
# ---------------------------------------------------------------------------

class CommitAction:
    """Result of a gate decision."""
    def __init__(self, action: str, direction: Optional[str] = None,
                 reason: str = ""):
        self.action = action      # CONTINUE | COMMIT | ABSTAIN
        self.direction = direction  # benign | suspicious | escalate (if COMMIT)
        self.reason = reason

    def __repr__(self):
        if self.direction:
            return f"CommitAction({self.action}:{self.direction})"
        return f"CommitAction({self.action})"


class CommitGate:
    """v6 commit controller — metacognitive commit control for local agents.

    The gate answers: "Should the agent continue investigating, commit to a
    verdict, or abstain because evidence is contradictory?"

    Bidirectional pressure:
        threat_score accumulates from threat evidence
        safety_score accumulates from safety evidence

    Commit triggers when evidence clarity (|threat - safety|) + urgency
    exceeds the threshold. Direction determined by which score dominates.

    Abstain triggers when both scores are high (contradictory evidence).
    """

    def __init__(self, threshold: float = 0.8, urgency_rate: float = 0.08,
                 contradiction_threshold: float = 0.4,
                 min_evidence_for_commit: float = 0.2,
                 exhaustion_after: int = 5,
                 memory: Optional[SplitMemoryStore] = None):
        # Thresholds
        self.base_threshold = threshold
        self.threshold = threshold
        self.urgency_rate = urgency_rate
        self.contradiction_threshold = contradiction_threshold
        self.min_evidence_for_commit = min_evidence_for_commit
        self.exhaustion_after = exhaustion_after  # v6.1: force commit path after N tools

        # Bidirectional state
        self.threat_score = 0.0
        self.safety_score = 0.0
        self.turn = 0
        self.committed = False
        self.last_action = CommitAction("CONTINUE")

        # Evidence tracking
        self.evidence_vector: List[Tuple[str, str]] = []
        self.evidence_tags: List[str] = []
        self.tool_count = 0

        # Memory (the strange loop)
        self.memory = memory or SplitMemoryStore("/tmp/commit_gate_memory.json")
        self.novelty = 1.0
        self.memory_match = None
        self.alert_text = ""

        # History for receipt
        self.history: List[dict] = []

    def set_threshold(self, complexity: str, alert_text: str = ""):
        """Se sets the base threshold. Memory modulates via ∇Ω."""
        self.base_threshold = {"low": 0.6, "medium": 0.8, "high": 1.0}[complexity]
        self.alert_text = alert_text

        # ∇Ω: novelty modulates threshold
        omega = nabla_omega(self.memory, alert_text, [])
        self.novelty = omega
        self.threshold = self.base_threshold * omega

        # Check for memory match
        result = self.memory.lookup(alert_text, [])
        self.memory_match = result

    def add_evidence(self, tool_name: str, tool_result: str,
                     model_output: str = "") -> CommitAction:
        """Process one piece of evidence. Returns the gate decision.

        This is the core loop:
          classify result → update scores → check commit conditions → return action
        """
        if self.committed:
            return CommitAction("COMMITTED", self.last_action.direction,
                                "gate already fired")

        # Classify tool result → bidirectional scores
        category, threat_delta, safety_delta = classify_tool_result(tool_result)
        self.evidence_vector.append((tool_name, category))
        self.evidence_tags.append(category)
        self.tool_count += 1

        # Add evidence to scores
        self.threat_score += threat_delta
        self.safety_score += safety_delta

        # Sidecar confidence from model output
        if model_output:
            t_conf, s_conf = sidecar_confidence(model_output)
            self.threat_score += t_conf
            self.safety_score += s_conf

        # Coincidence detection (supralinear)
        t_coin, s_coin = 0.0, 0.0
        if len(self.evidence_tags) >= 2:
            t_coin, s_coin = coincidence_check(self.evidence_tags)
            self.threat_score += t_coin
            self.safety_score += s_coin

        # Urgency (time pressure)
        urgency = self.turn * self.urgency_rate
        self.turn += 1

        # v6.1: investigation exhaustion — after N tools, add escalating
        # pressure and lower threshold. The agent has tried enough; commit
        # with what you have.
        exhaustion = 0.0
        if self.tool_count >= self.exhaustion_after:
            overshoot = self.tool_count - self.exhaustion_after + 1
            exhaustion = 0.15 * overshoot  # 0.15, 0.30, 0.45...

        # Compute commit metrics
        evidence_clarity = abs(self.threat_score - self.safety_score)
        contradiction = min(self.threat_score, self.safety_score)
        commit_pressure = evidence_clarity + urgency + exhaustion

        # Determine action
        action = self._decide(commit_pressure, contradiction)

        # Record history
        self.history.append({
            "turn": self.turn,
            "tool": tool_name,
            "category": category,
            "threat_score": round(self.threat_score, 3),
            "safety_score": round(self.safety_score, 3),
            "threat_delta": round(threat_delta, 3),
            "safety_delta": round(safety_delta, 3),
            "t_coincidence": round(t_coin, 3),
            "s_coincidence": round(s_coin, 3),
            "urgency": round(urgency, 3),
            "exhaustion": round(exhaustion, 3),
            "evidence_clarity": round(evidence_clarity, 3),
            "contradiction": round(contradiction, 3),
            "commit_pressure": round(commit_pressure, 3),
            "threshold": round(self.threshold, 3),
            "action": action.action,
            "direction": action.direction,
        })

        self.last_action = action
        if action.action in ("COMMIT", "ABSTAIN"):
            self.committed = True

        return action

    def _decide(self, commit_pressure: float, contradiction: float) -> CommitAction:
        """Core decision logic. Three possible actions."""
        # Not enough total evidence yet
        total_evidence = self.threat_score + self.safety_score
        if total_evidence < self.min_evidence_for_commit:
            return CommitAction("CONTINUE", reason="insufficient evidence")

        # Pressure hasn't reached threshold
        if commit_pressure < self.threshold:
            return CommitAction("CONTINUE", reason="below threshold")

        # Pressure exceeded threshold — time to decide

        # ABSTAIN: contradictory evidence (both threat and safety are high)
        if contradiction >= self.contradiction_threshold:
            return CommitAction("ABSTAIN", reason=
                f"contradictory evidence (threat={self.threat_score:.2f}, "
                f"safety={self.safety_score:.2f})")

        # COMMIT: determine direction
        if self.threat_score > self.safety_score:
            # How much more threat than safety determines severity
            margin = self.threat_score - self.safety_score
            if margin > 0.5 or self.threat_score > 0.8:
                direction = "escalate"
            else:
                direction = "suspicious"
        else:
            direction = "benign"

        return CommitAction("COMMIT", direction=direction,
                            reason=f"evidence clear (t={self.threat_score:.2f}, "
                                   f"s={self.safety_score:.2f})")

    def force_commit(self) -> CommitAction:
        """Force a decision (e.g., max turns reached). Still uses evidence."""
        if self.committed:
            return self.last_action

        contradiction = min(self.threat_score, self.safety_score)
        if contradiction >= self.contradiction_threshold:
            action = CommitAction("ABSTAIN", reason="forced: contradictory")
        elif self.threat_score > self.safety_score:
            margin = self.threat_score - self.safety_score
            direction = "escalate" if margin > 0.3 else "suspicious"
            action = CommitAction("COMMIT", direction=direction,
                                  reason="forced: max turns")
        elif self.safety_score > self.threat_score:
            action = CommitAction("COMMIT", direction="benign",
                                  reason="forced: max turns")
        else:
            action = CommitAction("COMMIT", direction="suspicious",
                                  reason="forced: ambiguous at limit")

        self.committed = True
        self.last_action = action
        self.history.append({
            "turn": self.turn,
            "tool": "FORCED",
            "category": "forced_commit",
            "threat_score": round(self.threat_score, 3),
            "safety_score": round(self.safety_score, 3),
            "action": action.action,
            "direction": action.direction,
            "reason": action.reason,
        })
        return action

    def close_episode(self, final_resolution: str, confidence: float):
        """Post-episode: write to memory. The strange loop closes here.

        receipt → memory → future threshold change → different behavior
        """
        if self.evidence_vector:
            self.memory.record_episode(
                evidence_signature=self.evidence_vector,
                resolution=final_resolution,
                confidence=confidence,
                alert_text=self.alert_text,
                threat_score=self.threat_score,
                safety_score=self.safety_score,
                turns=self.turn,
            )

    def to_receipt(self) -> dict:
        """Full receipt — proof of why the gate acted."""
        return {
            "gate_version": "v6_commit_gate",
            "base_threshold": self.base_threshold,
            "effective_threshold": round(self.threshold, 3),
            "novelty_omega": round(self.novelty, 3),
            "threat_score": round(self.threat_score, 3),
            "safety_score": round(self.safety_score, 3),
            "contradiction": round(min(self.threat_score, self.safety_score), 3),
            "committed": self.committed,
            "final_action": self.last_action.action,
            "final_direction": self.last_action.direction,
            "final_reason": self.last_action.reason,
            "turns": self.turn,
            "tool_count": self.tool_count,
            "evidence_vector": self.evidence_vector,
            "memory_match": (
                f"{self.memory_match[0]}:{self.memory_match[1].pattern_hash[:12]}"
                if self.memory_match else None
            ),
            "history": self.history,
            "memory_state": self.memory.to_receipt(),
        }
