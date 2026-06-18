"""Embedding-based evidence classifier for MorphSAT.

Replaces the keyword classifier in commit_gate.py with a sentence-embedding
nearest-centroid classifier. Same interface: (category, threat_delta, safety_delta).

The point is NOT that this classifier is perfect. The point is:
    "The architecture works with a swappable sensor.
     Gate 4 (false_safe_on_dangerous) fails with keyword sensor.
     Does it pass with an embedding sensor?"

If yes: the architecture/sensor separation is proven experimentally.
If no: the architecture has a sensor-independent weakness.

Uses all-MiniLM-L6-v2 (22M params, CPU-fast, cached on this box).
"""

import numpy as np
from typing import Tuple, List, Dict, Optional


# Lazy-loaded globals
_model = None
_centroids: Optional[Dict[str, np.ndarray]] = None


# ============================================================
# Reference exemplars — these define the classifier's knowledge
# ============================================================

# Security triage domain
SECURITY_SAFE_EXEMPLARS = [
    "ps output: All processes within expected parameters. Known-good processes running.",
    "YARA scan: No rule match. Signed and in package database.",
    "Netstat: All connections to known IPs. No outbound to suspicious ports.",
    "Package audit: All packages are up to date. No known vulnerabilities.",
    "File integrity: All hashes match baseline. No unauthorized modifications.",
    "System logs: All services healthy. No anomalies in last 24 hours.",
]

SECURITY_THREAT_EXEMPLARS = [
    "ps output: Unexpected child process /tmp/.x11 spawned by httpd. Not in baseline.",
    "YARA scan: match on rule suspicious_packer. High entropy section detected.",
    "Netstat: Outbound connection to port 4444, opened 10 min ago. Not in baseline.",
    "CVE-2026-5678 (CVSS 9.8). Remote code execution. Exploit available.",
    "File integrity: obfuscated binary found. base64.b64decode in process memory.",
    "Lateral movement detected. Unusual for this service. Not in known-good DB.",
]

SECURITY_SUSPICIOUS_EXEMPLARS = [
    "ps output: Process not in malware DB but not seen before either.",
    "Package audit: CVE-2024-1234 (CVSS 5.5). Local only. Patch not applied.",
    "System logs: Ambiguous pattern in auth logs. Could be misconfiguration.",
]

# Code review domain
CODE_REVIEW_SAFE_EXEMPLARS = [
    "Static analysis: All checks pass. No anomalies detected. Code matches baseline patterns.",
    "Test suite: 247/247 passed. Coverage 94%. No regressions. All within expected parameters.",
    "Dependency scan: All packages are up to date. No critical CVEs. All signed and in package database.",
    "Diff: +12 -3 lines in 2 files. Changes match the linked issue. No anomalies.",
    "Reviewer: LGTM. Code follows conventions. No concerns. Matches known-good patterns.",
]

CODE_REVIEW_THREAT_EXEMPLARS = [
    "Static analysis: Found unexpected eval() call. Obfuscated string concatenation. Not in baseline.",
    "Test suite: 200/247 passed. 47 failures. Unexpected regressions in auth module.",
    "Dependency scan: CVE-2026-5678 (CVSS 9.8). Remote code execution. Exploit available. Not found in known-good packages.",
    "Diff: +340 -2 lines. Binary blob added. Unusual for this repo. Encoded content detected.",
    "Reviewer: This changes permission checks in auth. Unexpected modification to security boundary.",
]

CODE_REVIEW_SUSPICIOUS_EXEMPLARS = [
    "Static analysis: No match in style database. Some patterns not in known-good DB either.",
    "Test suite: 245/247 passed. 2 flaky tests (seen before). Coverage 89%.",
    "Reviewer: Looks okay but I'm not sure about the error handling. Ambiguous intent in the retry logic.",
]


def _load_model():
    """Lazy-load sentence-transformers model."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def _build_centroids(domain: str = "code_review") -> Dict[str, np.ndarray]:
    """Build category centroids from reference exemplars."""
    global _centroids
    if _centroids is not None:
        return _centroids

    model = _load_model()

    if domain == "code_review":
        safe_texts = CODE_REVIEW_SAFE_EXEMPLARS
        threat_texts = CODE_REVIEW_THREAT_EXEMPLARS
        suspicious_texts = CODE_REVIEW_SUSPICIOUS_EXEMPLARS
    else:
        safe_texts = SECURITY_SAFE_EXEMPLARS
        threat_texts = SECURITY_THREAT_EXEMPLARS
        suspicious_texts = SECURITY_SUSPICIOUS_EXEMPLARS

    safe_emb = model.encode(safe_texts)
    threat_emb = model.encode(threat_texts)
    suspicious_emb = model.encode(suspicious_texts)

    _centroids = {
        "safe": np.mean(safe_emb, axis=0),
        "threat": np.mean(threat_emb, axis=0),
        "suspicious": np.mean(suspicious_emb, axis=0),
    }
    return _centroids


def _cos_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))


def reset():
    """Reset cached centroids (call when switching domains)."""
    global _centroids
    _centroids = None


def classify_tool_result_embedding(
    tool_result: str,
    domain: str = "code_review",
) -> Tuple[str, float, float]:
    """Embedding-based evidence classifier.

    Returns (category, threat_delta, safety_delta) — same interface as
    commit_gate.classify_tool_result.

    Strategy:
    1. Correction/noise signals are structural — handle with keywords (same as original)
    2. Everything else: embed, compare to centroids, return calibrated deltas
    3. Delta magnitude scales with confidence (gap between top-1 and top-2 similarity)
    """
    text_lower = tool_result.lower()

    # --- Structural signals (keyword-based, domain-independent) ---

    # Corrections are explicit signals, not semantic
    if any(kw in text_lower for kw in [
        "correction:", "false positive", "false alarm", "was closed as"
    ]):
        return "correction", 0.0, 0.35

    # Embed and compare to centroids
    model = _load_model()
    centroids = _build_centroids(domain)

    embedding = model.encode([tool_result])[0]

    sim_safe = _cos_sim(embedding, centroids["safe"])
    sim_threat = _cos_sim(embedding, centroids["threat"])
    sim_suspicious = _cos_sim(embedding, centroids["suspicious"])

    # Find best match
    sims = {"safe": sim_safe, "threat": sim_threat, "suspicious": sim_suspicious}
    best = max(sims, key=sims.get)
    best_sim = sims[best]

    # Confidence = gap between best and second-best
    sorted_sims = sorted(sims.values(), reverse=True)
    confidence_gap = sorted_sims[0] - sorted_sims[1]

    # Scale deltas by confidence gap
    # Gap > 0.15: strong signal (delta 0.25-0.35)
    # Gap 0.05-0.15: moderate signal (delta 0.12-0.20)
    # Gap < 0.05: weak/ambiguous (delta 0.05-0.10)
    if confidence_gap > 0.15:
        magnitude = min(0.35, 0.20 + confidence_gap)
    elif confidence_gap > 0.05:
        magnitude = 0.10 + confidence_gap
    else:
        magnitude = max(0.05, confidence_gap * 2)

    if best == "safe":
        return f"emb_safe_{confidence_gap:.2f}", 0.0, round(magnitude, 3)
    elif best == "threat":
        return f"emb_threat_{confidence_gap:.2f}", round(magnitude, 3), 0.0
    else:
        # Suspicious: small contribution to both sides
        return f"emb_suspicious_{confidence_gap:.2f}", round(magnitude * 0.3, 3), round(magnitude * 0.3, 3)


def make_classifier(domain: str = "code_review"):
    """Return a classifier function bound to a specific domain.

    Usage:
        classify_fn = make_classifier("code_review")
        cat, td, sd = classify_fn(tool_result)
    """
    def classifier(tool_result: str) -> Tuple[str, float, float]:
        return classify_tool_result_embedding(tool_result, domain=domain)
    return classifier
