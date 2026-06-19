"""
TwoStageGate v0 — routes clear evidence to threshold, ambiguous to QUBO.
========================================================================

Proven by sensitivity sweep (bench_qubo_gate_sensitivity.py):
    - Single-stage QUBO cannot simultaneously handle clear evidence AND
      ambiguous/conflict/drift cases. Weight tuning alone fails 7/7 gates.
    - Threshold gate handles clear evidence well (94.4% baseline).
    - QUBO gate handles concept_drift better (+10pp) but regresses clear cases.

Architecture (Hydra pattern):
    Stage 1 (router): Is this a clear-evidence case?
        - evidence_clarity > clarity_threshold AND contradiction < contra_ceiling
          AND no memory/graph disagreement → THRESHOLD path
        - Otherwise → QUBO path

    Stage 2a (threshold): CommitGate._decide() logic
        - commit_pressure vs threshold
        - direction from score comparison

    Stage 2b (QUBO): GateQUBO.decide()
        - Full matrix with memory/graph signals
        - Better at handling contradiction, drift, disagreement

Receipt includes: gate_backend_used, routing_reason, both backends' scores.

Lineage:
    CommitGate (threshold) → GateQUBO (optimization) → TwoStageGate (router)
    Hydra Router (codec) → TwoStageGate (action) — same pattern, different domain
    Se preflight (complexity) → routing discriminant — same signal concept
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from morphsat.commit_gate import CommitAction
from morphsat.gate_qubo import (
    GateQUBO,
    GateSnapshot,
    GateQUBOResult,
    ACTIONS,
    ACTION_TO_COMMIT,
    N_ACTIONS,
)


@dataclass
class TwoStageResult:
    """Result of two-stage gate decision."""
    action: str                         # COMMIT / CONTINUE / ABSTAIN
    direction: Optional[str]            # benign / suspicious / escalate
    reason: str
    gate_backend_used: str              # "threshold" or "qubo"
    routing_reason: str                 # why this backend was chosen
    routing_scores: Dict[str, float]    # discriminant values
    threshold_result: Optional[Dict]    # what threshold would have said
    qubo_result: Optional[Dict]         # what QUBO would have said (if run)
    action_scores: Dict[str, float]     # from whichever backend was used
    wall_time_ms: float
    snapshot: Dict[str, Any]


class TwoStageGate:
    """Two-stage gate: router → backend.

    Stage 1 routes based on evidence clarity, contradiction, and
    memory/graph agreement. Clear cases go to threshold (fast, proven).
    Ambiguous/conflict/drift cases go to QUBO (handles interactions).

    This is the Hydra pattern applied to gate decisions:
        Hydra: kurtosis + cosine → codec head
        TwoStageGate: clarity + contradiction + disagreement → gate backend
    """

    def __init__(
        self,
        # Router thresholds (the discriminant)
        clarity_threshold: float = 0.3,
        contradiction_ceiling: float = 0.25,
        disagreement_triggers_qubo: bool = True,

        # Threshold backend parameters
        commit_threshold: float = 0.8,
        contradiction_threshold: float = 0.4,
        min_evidence_for_commit: float = 0.2,

        # QUBO backend (passed through)
        gate_qubo: Optional[GateQUBO] = None,
    ):
        # Router
        self.clarity_threshold = clarity_threshold
        self.contradiction_ceiling = contradiction_ceiling
        self.disagreement_triggers_qubo = disagreement_triggers_qubo

        # Threshold backend
        self.commit_threshold = commit_threshold
        self.contradiction_threshold = contradiction_threshold
        self.min_evidence_for_commit = min_evidence_for_commit

        # QUBO backend
        self.gate_qubo = gate_qubo or GateQUBO()

    def _route(self, snap: GateSnapshot) -> Tuple[str, str, Dict[str, float]]:
        """Stage 1: decide which backend handles this case.

        Returns (backend, reason, routing_scores).
        """
        clarity = snap.evidence_clarity
        contra = snap.contradiction
        total_ev = snap.threat_score + snap.safety_score

        # Memory disagreement: memory says X, sensor says Y
        mem_disagrees = False
        if snap.memory_outcome != "unknown" and snap.memory_confidence > 0.5:
            sensor_dir = "benign" if snap.safety_score > snap.threat_score else "escalate"
            if snap.memory_outcome != sensor_dir:
                mem_disagrees = True

        # Graph disagreement: graph says X, sensor says Y
        graph_disagrees = False
        if snap.graph_dominant_outcome != "unknown":
            graph_str = {"none": 0.0, "weak": 0.25, "moderate": 0.5, "strong": 1.0
                         }.get(snap.graph_strength, 0.0)
            if graph_str > 0.25:
                sensor_dir = "benign" if snap.safety_score > snap.threat_score else "escalate"
                if snap.graph_dominant_outcome != sensor_dir:
                    graph_disagrees = True

        # Correction seen → always QUBO (needs careful handling)
        if snap.correction_seen:
            return "qubo", "correction_seen", {
                "clarity": clarity, "contradiction": contra,
                "mem_disagrees": float(mem_disagrees),
                "graph_disagrees": float(graph_disagrees),
                "correction": 1.0,
            }

        # High contradiction → QUBO
        if contra > self.contradiction_ceiling:
            return "qubo", "high_contradiction", {
                "clarity": clarity, "contradiction": contra,
                "mem_disagrees": float(mem_disagrees),
                "graph_disagrees": float(graph_disagrees),
            }

        # Memory or graph disagrees with sensor → QUBO
        if self.disagreement_triggers_qubo and (mem_disagrees or graph_disagrees):
            reasons = []
            if mem_disagrees:
                reasons.append("memory_disagrees")
            if graph_disagrees:
                reasons.append("graph_disagrees")
            return "qubo", "|".join(reasons), {
                "clarity": clarity, "contradiction": contra,
                "mem_disagrees": float(mem_disagrees),
                "graph_disagrees": float(graph_disagrees),
            }

        # Low evidence → threshold (CONTINUE is the right default)
        if total_ev < self.min_evidence_for_commit:
            return "threshold", "low_evidence", {
                "clarity": clarity, "contradiction": contra,
                "total_evidence": total_ev,
            }

        # Clear evidence, low contradiction, no disagreement → threshold
        if clarity >= self.clarity_threshold:
            return "threshold", "clear_evidence", {
                "clarity": clarity, "contradiction": contra,
            }

        # Moderate evidence, no strong signal either way → QUBO
        return "qubo", "ambiguous_evidence", {
            "clarity": clarity, "contradiction": contra,
            "mem_disagrees": float(mem_disagrees),
            "graph_disagrees": float(graph_disagrees),
        }

    def _threshold_decide(self, snap: GateSnapshot) -> Tuple[str, Optional[str], str]:
        """Stage 2a: threshold decision (CommitGate._decide logic).

        Returns (action, direction, reason).
        """
        total_ev = snap.threat_score + snap.safety_score

        if total_ev < self.min_evidence_for_commit:
            return "CONTINUE", None, "insufficient evidence"

        # Compute commit pressure
        commit_pressure = snap.evidence_clarity + snap.urgency + snap.exhaustion

        if commit_pressure < self.commit_threshold:
            return "CONTINUE", None, "below threshold"

        # Pressure exceeded — decide direction
        if snap.contradiction >= self.contradiction_threshold:
            return "ABSTAIN", None, (
                f"contradictory (t={snap.threat_score:.2f}, s={snap.safety_score:.2f})")

        if snap.threat_score > snap.safety_score:
            margin = snap.threat_score - snap.safety_score
            if margin > 0.5 or snap.threat_score > 0.8:
                direction = "escalate"
            else:
                direction = "suspicious"
        else:
            direction = "benign"

        return "COMMIT", direction, (
            f"clear (t={snap.threat_score:.2f}, s={snap.safety_score:.2f})")

    def decide(self, snap: GateSnapshot) -> TwoStageResult:
        """Full two-stage decision.

        Stage 1: route to backend.
        Stage 2: run selected backend.
        Always compute threshold result for comparison.
        """
        t0 = time.time()

        # Stage 1: route
        backend, routing_reason, routing_scores = self._route(snap)

        # Always compute threshold result (cheap)
        th_action, th_direction, th_reason = self._threshold_decide(snap)
        threshold_result = {
            "action": th_action,
            "direction": th_direction,
            "reason": th_reason,
        }

        # Stage 2: run selected backend
        qubo_result_dict = None
        if backend == "threshold":
            action = th_action
            direction = th_direction
            reason = f"threshold: {th_reason}"
            action_scores = self._threshold_action_scores(snap)
        else:
            qubo_result = self.gate_qubo.decide(snap)
            action = qubo_result.action
            direction = qubo_result.direction
            reason = f"qubo: {qubo_result.reason}"
            action_scores = qubo_result.action_scores
            qubo_result_dict = {
                "action": qubo_result.action,
                "direction": qubo_result.direction,
                "reason": qubo_result.reason,
                "selected_action_name": qubo_result.selected_action_name,
                "objective_value": qubo_result.objective_value,
            }

        wall_ms = (time.time() - t0) * 1000

        return TwoStageResult(
            action=action,
            direction=direction,
            reason=reason,
            gate_backend_used=backend,
            routing_reason=routing_reason,
            routing_scores=routing_scores,
            threshold_result=threshold_result,
            qubo_result=qubo_result_dict,
            action_scores=action_scores,
            wall_time_ms=round(wall_ms, 3),
            snapshot=asdict(snap),
        )

    def decide_as_commit_action(self, snap: GateSnapshot) -> CommitAction:
        """Convenience: return CommitAction for existing code."""
        result = self.decide(snap)
        return CommitAction(result.action, result.direction, result.reason)

    def _threshold_action_scores(self, snap: GateSnapshot) -> Dict[str, float]:
        """Synthetic action scores for threshold path (for diagnostics)."""
        scores = {}
        clarity = snap.evidence_clarity
        contra = snap.contradiction
        threat = snap.threat_score
        safety = snap.safety_score

        # Lower = better (matching QUBO convention)
        scores["commit_benign"] = -safety + threat * 0.5 + contra
        scores["commit_suspicious"] = -(threat + safety) * 0.3 + contra * 0.5
        scores["commit_escalate"] = -threat + safety * 0.5 + contra
        scores["continue"] = clarity * 0.5 - (1.0 - snap.tool_count / max(snap.max_tools, 1))
        scores["abstain"] = -contra + clarity

        return {k: round(v, 4) for k, v in scores.items()}
