"""
MorphSAT Pressure Gate — Sensor-driven commitment mechanism.

v4: Sensors (Se, sidecar, evidence, urgency) accumulate pressure toward
    a threshold. Gate opens when threshold crossed. Action potential model.

v5: + Pattern memory (superglyph store) — cross-episode learning
    + Novelty detection (nabla_omega / ∇Ω) — threshold modulation
    + Coincidence detection — supralinear multi-signal patterns
    + Post-episode write — immune system learns from every episode

Lineage: AGI equation Ξ(t) → GuardianCell Θ(cᵢ) → MorphSAT FSA → PressureGate
"""

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class PressureGate:
    """Accumulates pressure from sensors. Opens when threshold is crossed."""

    def __init__(self, threshold: float = 0.8, urgency_rate: float = 0.08,
                 min_pressure_for_verdict: float = 0.2):
        self.threshold = threshold
        self.urgency_rate = urgency_rate
        self.min_pressure_for_verdict = min_pressure_for_verdict
        self.pressure = 0.0
        self.committed = False
        self.turn = 0
        self.tool_count = 0
        self.history = []

    def set_threshold(self, complexity: str):
        """Se sets the threshold at intake."""
        self.threshold = {"low": 0.6, "medium": 0.8, "high": 1.0}[complexity]

    def add_pressure(self, evidence_p: float = 0.0, sidecar_p: float = 0.0,
                     source: str = "turn") -> str:
        """Add pressure from sensors. Returns gate state: HOLD, OPEN, COMMITTED."""
        if self.committed:
            return "COMMITTED"

        urgency = self.turn * self.urgency_rate
        delta = evidence_p + sidecar_p + urgency
        self.pressure += delta
        self.turn += 1

        self.history.append({
            "turn": self.turn,
            "source": source,
            "evidence_p": round(evidence_p, 3),
            "sidecar_p": round(sidecar_p, 3),
            "urgency": round(urgency, 3),
            "delta": round(delta, 3),
            "pressure": round(self.pressure, 3),
            "threshold": self.threshold,
        })

        if self.pressure >= self.threshold:
            self.committed = True
            return "OPEN"

        return "HOLD"

    def try_verdict(self) -> str:
        """Model wants to verdict voluntarily. Allow or block?"""
        if self.committed:
            return "ALLOW"
        if self.pressure < self.min_pressure_for_verdict:
            return "BLOCK"  # not enough evidence yet
        return "ALLOW"  # model chose to commit early, fine

    def should_block_tool(self) -> bool:
        """Should we block further tool calls? Only after gate opens."""
        return self.committed

    def to_receipt(self) -> dict:
        return {
            "gate_type": "pressure",
            "threshold": self.threshold,
            "final_pressure": round(self.pressure, 3),
            "committed": self.committed,
            "turns": self.turn,
            "tool_count": self.tool_count,
            "history": self.history,
        }


# ---------------------------------------------------------------------------
# Sensor functions
# ---------------------------------------------------------------------------

def se_classify_complexity(alert_text: str) -> str:
    """Se-proxy: classify alert complexity from text signals."""
    text_lower = alert_text.lower()

    HIGH_KW = [
        "sequence detected", "chain", "lateral movement", "privilege escalation",
        "multi", "stage", "obfuscated", "base64", "exec(", "postinstall",
        "typosquat", "payload", "certutil", "regsvr32", "squiblydoo",
    ]
    MEDIUM_KW = [
        "dns txt", "random subdomain", "registered", "not in", "no yara",
        "non-interactive", "no.*scheduled", "no.*badge",
        "resignation", "pip", "downloaded",
    ]
    LOW_KW = [
        "scheduled", "maintenance", "unattended-upgrades", "certificate rotation",
        "certbot", "pentest", "approved", "engagement", "dr runbook",
        "failover", "red team", "timezone", "utc+",
    ]

    high_hits = sum(1 for kw in HIGH_KW if kw in text_lower)
    medium_hits = sum(1 for kw in MEDIUM_KW if kw in text_lower)
    low_hits = sum(1 for kw in LOW_KW if kw in text_lower)

    if high_hits >= 2 or (high_hits >= 1 and medium_hits >= 1):
        return "high"
    elif low_hits >= 2 or (low_hits >= 1 and medium_hits == 0 and high_hits == 0):
        return "low"
    elif medium_hits >= 1:
        return "medium"
    else:
        return "medium"


def evidence_pressure(tool_result: str, category_hint: Optional[str] = None) -> float:
    """Score how informative a tool result is → pressure increment.

    Clear confirming/definitive: 0.30 - 0.35
    Moderate signal: 0.20 - 0.25
    Ambiguous: 0.10
    Redundant/empty: 0.05
    Contradictory: -0.05
    """
    text_lower = tool_result.lower()

    # Definitive signals
    if any(kw in text_lower for kw in [
        "yara", "match", "exploit available", "cvss 9",
        "not found in known-good", "unexpected",
        "matches known-good", "all match baseline", "all processes within expected",
        "no anomalies", "signed and in package",
    ]):
        return 0.30

    # Moderate signals
    if any(kw in text_lower for kw in [
        "not in malware db", "not in known-good",
        "ambiguous", "no known-bad", "seen before",
        "not signed", "cvss 5",
    ]):
        return 0.15

    # Explicit ambiguity
    if any(kw in text_lower for kw in [
        "no match", "no rule match", "normal but",
    ]):
        return 0.10

    # Default: some information gained
    return 0.12


def sidecar_confidence(model_output: str) -> float:
    """Sidecar-proxy: estimate model confidence from response language.

    Returns pressure increment (0.0 - 0.15).
    High confidence language → more pressure (ready to decide).
    Low confidence → less pressure.
    """
    text_lower = model_output.lower()

    HIGH_PATTERNS = [
        r"clearly (benign|malicious|suspicious)",
        r"(definitely|certainly|obviously|confirmed)",
        r"(no doubt|confident|high confidence)",
        r"(approved|authorized|scheduled|expected|routine)",
        r"this is (a )?(standard|normal|routine|known|legitimate)",
        r"(strong indicator|definitive|conclusive)",
    ]
    LOW_PATTERNS = [
        r"(unclear|ambiguous|uncertain|not sure|hard to tell)",
        r"(could be|might be|possibly|potentially)",
        r"(need more|further investigation|additional)",
        r"(inconclusive|insufficient|cannot determine)",
    ]

    high_score = sum(1 for p in HIGH_PATTERNS if re.search(p, text_lower))
    low_score = sum(1 for p in LOW_PATTERNS if re.search(p, text_lower))

    if high_score > 0 and low_score == 0:
        return min(0.15, 0.05 + high_score * 0.05)
    elif low_score > 0 and high_score == 0:
        return 0.0  # uncertain → no confidence pressure
    else:
        return 0.03  # neutral


def categorize_evidence(tool_result: str) -> str:
    """Classify a tool result into a category tag for pattern matching.

    Order matters — more specific patterns first to avoid false matches
    (e.g., "all match baseline" contains "match" but is NOT a YARA match).
    """
    text_lower = tool_result.lower()

    # Benign patterns first (specific multi-word phrases)
    if any(kw in text_lower for kw in ["all match baseline", "no anomalies", "within expected"]):
        return "baseline_match"
    if any(kw in text_lower for kw in ["known-good", "signed and in package", "package database"]):
        return "known_good"
    if any(kw in text_lower for kw in ["no critical", "patched", "no match"]):
        return "clean"

    # Attack patterns (specific indicators)
    if any(kw in text_lower for kw in ["yara", "suspicious_packer"]):
        return "yara_match"
    if any(kw in text_lower for kw in ["unexpected", "unusual", "not found in known-good"]):
        return "unexpected"
    if any(kw in text_lower for kw in ["4444", "outbound", "not in baseline"]):
        return "outbound_port"
    if any(kw in text_lower for kw in ["cvss 9", "exploit available", "remote code"]):
        return "critical_cve"

    # Ambiguous
    if any(kw in text_lower for kw in ["ambiguous", "not in known-good", "not in malware"]):
        return "ambiguous"
    if any(kw in text_lower for kw in ["seen before", "not signed", "cvss 5"]):
        return "moderate_signal"

    return "unknown"


# ---------------------------------------------------------------------------
# v5: Pattern Store (Superglyph Memory)
# ---------------------------------------------------------------------------

@dataclass
class PatternEntry:
    """One entry in the antibody library."""
    pattern_hash: str
    resolution: str             # benign | suspicious | escalate
    confidence: float
    exposures: int = 1
    first_seen: str = ""
    last_seen: str = ""
    evidence_signature: List = field(default_factory=list)
    alert_keywords: List[str] = field(default_factory=list)
    threshold_at_resolution: float = 0.0
    pressure_at_resolution: float = 0.0
    turns_to_resolve: int = 0


class PatternStore:
    """Persistent cross-episode pattern memory (superglyph evolved)."""

    def __init__(self, store_path: str = "pattern_store.json"):
        self.store_path = Path(store_path)
        self.patterns: Dict[str, PatternEntry] = {}
        self._load()

    def _load(self):
        if self.store_path.exists():
            try:
                data = json.loads(self.store_path.read_text())
                for h, entry in data.items():
                    if "evidence_signature" in entry:
                        entry["evidence_signature"] = [
                            tuple(x) if isinstance(x, list) else x
                            for x in entry["evidence_signature"]
                        ]
                    self.patterns[h] = PatternEntry(**entry)
            except (json.JSONDecodeError, TypeError):
                self.patterns = {}

    def _save(self):
        data = {}
        for h, entry in self.patterns.items():
            d = asdict(entry)
            d["evidence_signature"] = [
                list(x) if isinstance(x, tuple) else x
                for x in d["evidence_signature"]
            ]
            data[h] = d
        self.store_path.write_text(json.dumps(data, indent=2))

    @staticmethod
    def hash_evidence(evidence_signature: List[Tuple[str, str]]) -> str:
        canonical = sorted(evidence_signature)
        blob = json.dumps(canonical, sort_keys=True).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    def lookup(self, alert_text: str,
               evidence_so_far: List[Tuple[str, str]]) -> Optional[PatternEntry]:
        if evidence_so_far:
            h = self.hash_evidence(evidence_so_far)
            if h in self.patterns:
                return self.patterns[h]

        alert_lower = alert_text.lower()
        best_match = None
        best_overlap = 0
        for entry in self.patterns.values():
            if not entry.alert_keywords:
                continue
            overlap = sum(1 for kw in entry.alert_keywords if kw in alert_lower)
            ratio = overlap / max(len(entry.alert_keywords), 1)
            if ratio > 0.5 and overlap > best_overlap:
                best_overlap = overlap
                best_match = entry
        return best_match

    def nearest_distance(self, alert_text: str) -> float:
        if not self.patterns:
            return 1.0
        alert_lower = alert_text.lower()
        best_overlap = 0.0
        for entry in self.patterns.values():
            if not entry.alert_keywords:
                continue
            overlap = sum(1 for kw in entry.alert_keywords if kw in alert_lower)
            ratio = overlap / max(len(entry.alert_keywords), 1)
            best_overlap = max(best_overlap, ratio)
        return 1.0 - best_overlap

    def check_learned_patterns(self, evidence_tags: List[str]) -> float:
        for entry in self.patterns.values():
            if entry.confidence < 0.7 or entry.exposures < 2:
                continue
            stored_tags = [cat for _, cat in entry.evidence_signature]
            if not stored_tags:
                continue
            match_ratio = sum(1 for t in stored_tags if t in evidence_tags) / len(stored_tags)
            if match_ratio >= 0.7:
                return 0.15 * entry.confidence
        return 0.0

    def record_episode(self, evidence_signature: List[Tuple[str, str]],
                       resolution: str, confidence: float,
                       alert_text: str, threshold: float,
                       pressure: float, turns: int):
        h = self.hash_evidence(evidence_signature)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        keywords = [w.lower() for w in alert_text.split()
                    if len(w) > 3 and w.isalpha()]

        if h in self.patterns:
            entry = self.patterns[h]
            entry.exposures += 1
            entry.last_seen = now
            entry.confidence = (
                entry.confidence * (entry.exposures - 1) + confidence
            ) / entry.exposures
            existing_kw = set(entry.alert_keywords)
            entry.alert_keywords = list(existing_kw | set(keywords))
        else:
            self.patterns[h] = PatternEntry(
                pattern_hash=h,
                resolution=resolution,
                confidence=confidence,
                exposures=1,
                first_seen=now,
                last_seen=now,
                evidence_signature=evidence_signature,
                alert_keywords=keywords,
                threshold_at_resolution=threshold,
                pressure_at_resolution=pressure,
                turns_to_resolve=turns,
            )
        self._save()

    def clear(self):
        self.patterns = {}
        if self.store_path.exists():
            self.store_path.unlink()

    def to_receipt(self) -> dict:
        return {
            "pattern_count": len(self.patterns),
            "total_exposures": sum(e.exposures for e in self.patterns.values()),
            "resolutions": {
                r: sum(1 for e in self.patterns.values() if e.resolution == r)
                for r in ["benign", "suspicious", "escalate"]
            },
        }


# ---------------------------------------------------------------------------
# v5: Novelty Sensor (∇Ω)
# ---------------------------------------------------------------------------

def nabla_omega(pattern_store: PatternStore,
                alert_text: str,
                evidence_so_far: List[Tuple[str, str]]) -> float:
    """Novelty detector — threshold multiplier.

    < 1.0 → known pattern, sensitized (lower threshold)
    = 1.0 → neutral
    > 1.0 → novel pattern (raise threshold, investigate harder)
    """
    match = pattern_store.lookup(alert_text, evidence_so_far)

    if match and match.exposures >= 3:
        return max(0.6, 1.0 - match.confidence * 0.25)
    elif match and match.exposures >= 1:
        return max(0.8, 1.0 - match.confidence * 0.12)
    else:
        nearest_dist = pattern_store.nearest_distance(alert_text)
        if nearest_dist > 0.8:
            return 1.25
        elif nearest_dist > 0.5:
            return 1.12
        else:
            return 1.0


# ---------------------------------------------------------------------------
# v5: Coincidence Detection (Supralinear Pressure)
# ---------------------------------------------------------------------------

ATTACK_PATTERNS = {
    "reverse_shell": {
        "requires": ["unexpected", "outbound_port"],
        "bonus": 0.20,
    },
    "full_compromise": {
        "requires": ["unexpected", "outbound_port", "yara_match"],
        "bonus": 0.30,
    },
    "supply_chain": {
        "requires": ["unexpected", "critical_cve"],
        "bonus": 0.20,
    },
}

BENIGN_PATTERNS = {
    "routine_maintenance": {
        "requires": ["baseline_match", "known_good"],
        "bonus": 0.20,
    },
    "clean_system": {
        "requires": ["baseline_match", "known_good", "clean"],
        "bonus": 0.25,
    },
}


def coincidence_pressure(evidence_tags: List[str],
                         pattern_store: Optional[PatternStore] = None) -> float:
    bonus = 0.0
    for pattern in {**ATTACK_PATTERNS, **BENIGN_PATTERNS}.values():
        if all(tag in evidence_tags for tag in pattern["requires"]):
            bonus = max(bonus, pattern["bonus"])
    if pattern_store:
        learned = pattern_store.check_learned_patterns(evidence_tags)
        bonus = max(bonus, learned)
    return bonus


# ---------------------------------------------------------------------------
# v5: PressureGate with Pattern Memory
# ---------------------------------------------------------------------------

class PressureGateV5:
    """Pressure gate with cross-episode pattern memory."""

    def __init__(self, threshold: float = 0.8, urgency_rate: float = 0.08,
                 min_pressure_for_verdict: float = 0.2,
                 pattern_store: Optional[PatternStore] = None):
        self.base_threshold = threshold
        self.threshold = threshold
        self.urgency_rate = urgency_rate
        self.min_pressure_for_verdict = min_pressure_for_verdict
        self.pressure = 0.0
        self.committed = False
        self.turn = 0
        self.tool_count = 0
        self.history = []

        self.pattern_store = pattern_store or PatternStore("/tmp/morphsat_patterns.json")
        self.evidence_vector: List[Tuple[str, str]] = []
        self.evidence_tags: List[str] = []
        self.novelty = 1.0
        self.pattern_match = None
        self.alert_text = ""

    def set_threshold(self, complexity: str, alert_text: str = ""):
        self.base_threshold = {"low": 0.6, "medium": 0.8, "high": 1.0}[complexity]
        self.alert_text = alert_text

        omega = nabla_omega(self.pattern_store, alert_text, [])
        self.novelty = omega
        self.threshold = self.base_threshold * omega
        self.pattern_match = self.pattern_store.lookup(alert_text, [])

    def add_pressure(self, evidence_p: float = 0.0, sidecar_p: float = 0.0,
                     source: str = "turn",
                     tool_name: str = "", result_category: str = "") -> str:
        if self.committed:
            return "COMMITTED"

        if tool_name and result_category:
            self.evidence_vector.append((tool_name, result_category))
            self.evidence_tags.append(result_category)
            self.tool_count += 1

        coin_p = coincidence_pressure(
            self.evidence_tags, self.pattern_store
        ) if len(self.evidence_tags) >= 2 else 0.0

        urgency = self.turn * self.urgency_rate
        delta = evidence_p + sidecar_p + urgency + coin_p
        self.pressure += delta
        self.turn += 1

        self.history.append({
            "turn": self.turn,
            "source": source,
            "evidence_p": round(evidence_p, 3),
            "sidecar_p": round(sidecar_p, 3),
            "coincidence_p": round(coin_p, 3),
            "urgency": round(urgency, 3),
            "delta": round(delta, 3),
            "pressure": round(self.pressure, 3),
            "threshold": round(self.threshold, 3),
            "novelty": round(self.novelty, 3),
        })

        if self.pressure >= self.threshold:
            self.committed = True
            return "OPEN"

        return "HOLD"

    def try_verdict(self) -> str:
        if self.committed:
            return "ALLOW"
        if self.pressure < self.min_pressure_for_verdict:
            return "BLOCK"
        return "ALLOW"

    def should_block_tool(self) -> bool:
        return self.committed

    def close_episode(self, resolution: str, confidence: float):
        if self.evidence_vector:
            self.pattern_store.record_episode(
                evidence_signature=self.evidence_vector,
                resolution=resolution,
                confidence=confidence,
                alert_text=self.alert_text,
                threshold=self.threshold,
                pressure=self.pressure,
                turns=self.turn,
            )

    def to_receipt(self) -> dict:
        return {
            "gate_type": "pressure_v5",
            "base_threshold": self.base_threshold,
            "effective_threshold": round(self.threshold, 3),
            "novelty_omega": round(self.novelty, 3),
            "final_pressure": round(self.pressure, 3),
            "committed": self.committed,
            "turns": self.turn,
            "tool_count": self.tool_count,
            "pattern_match": (self.pattern_match.pattern_hash[:12]
                              if self.pattern_match else None),
            "evidence_vector": self.evidence_vector,
            "history": self.history,
            "pattern_store": self.pattern_store.to_receipt(),
        }
