"""
Tests for TwoStageGate v0 — two-stage routing: threshold for clear, QUBO for ambiguous.

Covers:
    1. Routing logic — clear evidence → threshold, ambiguous → QUBO
    2. Threshold backend — correct action/direction under clear evidence
    3. QUBO backend — correct dispatch for contradiction/disagreement/drift
    4. Memory disagreement triggers QUBO
    5. Graph disagreement triggers QUBO
    6. Correction signal triggers QUBO
    7. Low evidence → threshold (CONTINUE)
    8. Result structure — all receipt fields present
    9. CommitAction compatibility
   10. Both backends always populate action_scores
"""

import pytest
from morphsat.two_stage_gate import TwoStageGate, TwoStageResult
from morphsat.gate_qubo import GateQUBO, GateSnapshot
from morphsat.commit_gate import CommitAction


@pytest.fixture
def gate():
    return TwoStageGate()


# ---------------------------------------------------------------------------
# Routing logic
# ---------------------------------------------------------------------------

class TestRouting:
    def test_clear_threat_routes_to_threshold(self, gate):
        snap = GateSnapshot(
            threat_score=0.9, safety_score=0.1,
            evidence_clarity=0.8, contradiction=0.1,
            urgency=0.3, tool_count=3,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"
        assert result.routing_reason == "clear_evidence"

    def test_clear_safety_routes_to_threshold(self, gate):
        snap = GateSnapshot(
            threat_score=0.1, safety_score=0.8,
            evidence_clarity=0.7, contradiction=0.1,
            urgency=0.3, tool_count=3,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"
        assert result.routing_reason == "clear_evidence"

    def test_high_contradiction_routes_to_qubo(self, gate):
        snap = GateSnapshot(
            threat_score=0.6, safety_score=0.5,
            evidence_clarity=0.1, contradiction=0.5,
            urgency=0.2, tool_count=3,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        assert result.routing_reason == "high_contradiction"

    def test_ambiguous_evidence_routes_to_qubo(self, gate):
        snap = GateSnapshot(
            threat_score=0.3, safety_score=0.2,
            evidence_clarity=0.1, contradiction=0.2,
            urgency=0.1, tool_count=2,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        assert result.routing_reason == "ambiguous_evidence"

    def test_low_evidence_routes_to_threshold(self, gate):
        snap = GateSnapshot(
            threat_score=0.05, safety_score=0.05,
            evidence_clarity=0.0, contradiction=0.05,
            tool_count=1,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"
        assert result.routing_reason == "low_evidence"

    def test_correction_always_routes_to_qubo(self, gate):
        snap = GateSnapshot(
            threat_score=0.1, safety_score=0.8,
            evidence_clarity=0.7, contradiction=0.1,
            correction_seen=True,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        assert result.routing_reason == "correction_seen"


# ---------------------------------------------------------------------------
# Memory/graph disagreement routing
# ---------------------------------------------------------------------------

class TestDisagreementRouting:
    def test_memory_disagrees_routes_to_qubo(self, gate):
        snap = GateSnapshot(
            threat_score=0.6, safety_score=0.1,
            evidence_clarity=0.5, contradiction=0.1,
            urgency=0.2, tool_count=3,
            memory_outcome="benign", memory_confidence=0.8,
            memory_exposures=5,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        assert "memory_disagrees" in result.routing_reason

    def test_graph_disagrees_routes_to_qubo(self, gate):
        snap = GateSnapshot(
            threat_score=0.1, safety_score=0.6,
            evidence_clarity=0.5, contradiction=0.1,
            urgency=0.2, tool_count=3,
            graph_dominant_outcome="escalate",
            graph_strength="strong",
            graph_reinforcements=5,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        assert "graph_disagrees" in result.routing_reason

    def test_memory_agrees_stays_threshold(self, gate):
        """Memory agreeing with sensor should NOT trigger QUBO."""
        snap = GateSnapshot(
            threat_score=0.8, safety_score=0.1,
            evidence_clarity=0.7, contradiction=0.1,
            urgency=0.3, tool_count=3,
            memory_outcome="escalate", memory_confidence=0.9,
            memory_exposures=5,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"

    def test_weak_graph_doesnt_trigger_qubo(self, gate):
        """Weak graph signal should not override clear evidence."""
        snap = GateSnapshot(
            threat_score=0.8, safety_score=0.1,
            evidence_clarity=0.7, contradiction=0.1,
            urgency=0.3, tool_count=3,
            graph_dominant_outcome="benign",
            graph_strength="weak",
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"

    def test_low_confidence_memory_doesnt_trigger_qubo(self, gate):
        """Low-confidence memory disagreement should not trigger QUBO."""
        snap = GateSnapshot(
            threat_score=0.7, safety_score=0.1,
            evidence_clarity=0.6, contradiction=0.1,
            urgency=0.2, tool_count=3,
            memory_outcome="benign", memory_confidence=0.3,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"


# ---------------------------------------------------------------------------
# Threshold backend correctness
# ---------------------------------------------------------------------------

class TestThresholdBackend:
    def test_clear_threat_escalates(self, gate):
        snap = GateSnapshot(
            threat_score=0.9, safety_score=0.1,
            evidence_clarity=0.8, contradiction=0.1,
            urgency=0.3, tool_count=4,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"
        assert result.action == "COMMIT"
        assert result.direction == "escalate"

    def test_clear_safety_benign(self, gate):
        snap = GateSnapshot(
            threat_score=0.1, safety_score=0.8,
            evidence_clarity=0.7, contradiction=0.1,
            urgency=0.3, tool_count=4,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"
        assert result.action == "COMMIT"
        assert result.direction == "benign"

    def test_moderate_threat_suspicious(self, gate):
        snap = GateSnapshot(
            threat_score=0.45, safety_score=0.1,
            evidence_clarity=0.35, contradiction=0.1,
            urgency=0.5, tool_count=4,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"
        assert result.action == "COMMIT"
        assert result.direction == "suspicious"

    def test_below_threshold_continues(self, gate):
        snap = GateSnapshot(
            threat_score=0.2, safety_score=0.05,
            evidence_clarity=0.15, contradiction=0.05,
            urgency=0.1, tool_count=2,
        )
        result = gate.decide(snap)
        assert result.action == "CONTINUE"

    def test_threshold_abstains_on_contradiction(self, gate):
        snap = GateSnapshot(
            threat_score=0.5, safety_score=0.45,
            evidence_clarity=0.05, contradiction=0.45,
            urgency=0.8, tool_count=6,
        )
        result = gate.decide(snap)
        assert result.action == "ABSTAIN"


# ---------------------------------------------------------------------------
# QUBO backend correctness
# ---------------------------------------------------------------------------

class TestQUBOBackend:
    def test_qubo_handles_contradiction(self, gate):
        snap = GateSnapshot(
            threat_score=0.6, safety_score=0.55,
            evidence_clarity=0.05, contradiction=0.55,
            urgency=0.2, tool_count=3,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        assert result.qubo_result is not None

    def test_qubo_handles_memory_disagreement(self, gate):
        snap = GateSnapshot(
            threat_score=0.5, safety_score=0.1,
            evidence_clarity=0.4, contradiction=0.1,
            urgency=0.2, tool_count=3,
            memory_outcome="benign", memory_confidence=0.9,
            memory_exposures=10,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        assert result.qubo_result is not None

    def test_qubo_result_has_objective(self, gate):
        snap = GateSnapshot(
            threat_score=0.4, safety_score=0.35,
            evidence_clarity=0.05, contradiction=0.35,
            urgency=0.2, tool_count=4,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        assert "objective_value" in result.qubo_result


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_threshold_result_always_present(self, gate):
        snap = GateSnapshot(
            threat_score=0.6, safety_score=0.55,
            evidence_clarity=0.05, contradiction=0.55,
        )
        result = gate.decide(snap)
        assert result.threshold_result is not None
        assert "action" in result.threshold_result
        assert "direction" in result.threshold_result

    def test_qubo_result_only_when_qubo_used(self, gate):
        # Clear evidence → threshold
        snap_clear = GateSnapshot(
            threat_score=0.9, safety_score=0.1,
            evidence_clarity=0.8, contradiction=0.1,
            urgency=0.3, tool_count=3,
        )
        r_clear = gate.decide(snap_clear)
        assert r_clear.qubo_result is None

        # Ambiguous → QUBO
        snap_ambig = GateSnapshot(
            threat_score=0.3, safety_score=0.25,
            evidence_clarity=0.05, contradiction=0.25,
        )
        r_ambig = gate.decide(snap_ambig)
        assert r_ambig.qubo_result is not None

    def test_action_scores_always_present(self, gate):
        for snap in [
            GateSnapshot(threat_score=0.9, safety_score=0.1,
                         evidence_clarity=0.8, urgency=0.3, tool_count=3),
            GateSnapshot(threat_score=0.3, safety_score=0.25,
                         evidence_clarity=0.05, contradiction=0.25),
        ]:
            result = gate.decide(snap)
            assert len(result.action_scores) == 5
            for name in ["commit_benign", "commit_suspicious",
                         "commit_escalate", "continue", "abstain"]:
                assert name in result.action_scores

    def test_routing_scores_present(self, gate):
        snap = GateSnapshot(threat_score=0.5, safety_score=0.1)
        result = gate.decide(snap)
        assert isinstance(result.routing_scores, dict)
        assert "clarity" in result.routing_scores or "total_evidence" in result.routing_scores

    def test_wall_time_positive(self, gate):
        snap = GateSnapshot(threat_score=0.5)
        result = gate.decide(snap)
        assert result.wall_time_ms >= 0

    def test_snapshot_preserved(self, gate):
        snap = GateSnapshot(threat_score=0.42, safety_score=0.13)
        result = gate.decide(snap)
        assert result.snapshot["threat_score"] == 0.42
        assert result.snapshot["safety_score"] == 0.13


# ---------------------------------------------------------------------------
# CommitAction compatibility
# ---------------------------------------------------------------------------

class TestCompatibility:
    def test_decide_as_commit_action(self, gate):
        snap = GateSnapshot(
            threat_score=0.8, safety_score=0.1,
            evidence_clarity=0.7, urgency=0.3, tool_count=4,
        )
        action = gate.decide_as_commit_action(snap)
        assert isinstance(action, CommitAction)
        assert action.action in ("COMMIT", "CONTINUE", "ABSTAIN")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_zero_evidence(self, gate):
        snap = GateSnapshot()
        result = gate.decide(snap)
        assert result.action == "CONTINUE"
        assert result.gate_backend_used == "threshold"

    def test_extreme_threat(self, gate):
        snap = GateSnapshot(
            threat_score=5.0, safety_score=0.0,
            evidence_clarity=5.0, urgency=1.0,
            tool_count=10,
        )
        result = gate.decide(snap)
        assert result.action == "COMMIT"
        assert result.direction == "escalate"

    def test_equal_scores_doesnt_crash(self, gate):
        snap = GateSnapshot(
            threat_score=0.5, safety_score=0.5,
            evidence_clarity=0.0, contradiction=0.5,
        )
        result = gate.decide(snap)
        assert result.action in ("COMMIT", "CONTINUE", "ABSTAIN")

    def test_custom_qubo_weights(self):
        custom_qubo = GateQUBO(w_clarity_commit=-5.0)
        gate = TwoStageGate(gate_qubo=custom_qubo)
        snap = GateSnapshot(
            threat_score=0.4, safety_score=0.35,
            evidence_clarity=0.05, contradiction=0.35,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"

    def test_custom_clarity_threshold(self):
        gate = TwoStageGate(clarity_threshold=0.6)
        # Moderate clarity (0.4) would be clear with default (0.3) but not with 0.6
        snap = GateSnapshot(
            threat_score=0.5, safety_score=0.1,
            evidence_clarity=0.4, contradiction=0.1,
            urgency=0.2, tool_count=3,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        assert result.routing_reason == "ambiguous_evidence"

    def test_disagreement_routing_can_be_disabled(self):
        gate = TwoStageGate(disagreement_triggers_qubo=False)
        snap = GateSnapshot(
            threat_score=0.7, safety_score=0.1,
            evidence_clarity=0.6, contradiction=0.1,
            urgency=0.2, tool_count=3,
            memory_outcome="benign", memory_confidence=0.9,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "threshold"


# ---------------------------------------------------------------------------
# Backend comparison (the key property)
# ---------------------------------------------------------------------------

class TestBackendSeparation:
    """The whole point: threshold handles clear, QUBO handles ambiguous."""

    def test_clear_cases_get_correct_answer_from_threshold(self, gate):
        """Clear evidence should produce correct verdicts via threshold."""
        cases = [
            (0.9, 0.1, "escalate"),
            (0.1, 0.8, "benign"),
        ]
        for threat, safety, expected_dir in cases:
            snap = GateSnapshot(
                threat_score=threat, safety_score=safety,
                evidence_clarity=abs(threat - safety),
                contradiction=min(threat, safety),
                urgency=0.3, tool_count=4,
            )
            result = gate.decide(snap)
            assert result.gate_backend_used == "threshold", \
                f"Clear case (t={threat}) should use threshold"
            assert result.action == "COMMIT"
            assert result.direction == expected_dir

    def test_ambiguous_cases_use_qubo(self, gate):
        """Ambiguous/conflict cases should go to QUBO."""
        cases = [
            # High contradiction
            GateSnapshot(threat_score=0.5, safety_score=0.45,
                         evidence_clarity=0.05, contradiction=0.45),
            # Memory disagreement
            GateSnapshot(threat_score=0.6, safety_score=0.1,
                         evidence_clarity=0.5, contradiction=0.1,
                         memory_outcome="benign", memory_confidence=0.8),
            # Low clarity
            GateSnapshot(threat_score=0.2, safety_score=0.15,
                         evidence_clarity=0.05, contradiction=0.15,
                         tool_count=3),
        ]
        for snap in cases:
            result = gate.decide(snap)
            assert result.gate_backend_used == "qubo", \
                f"Ambiguous case should use QUBO, got {result.gate_backend_used} ({result.routing_reason})"

    def test_threshold_and_qubo_can_disagree(self, gate):
        """When QUBO is used, its answer may differ from what threshold would say."""
        snap = GateSnapshot(
            threat_score=0.5, safety_score=0.1,
            evidence_clarity=0.4, contradiction=0.1,
            urgency=0.2, tool_count=3,
            memory_outcome="benign", memory_confidence=0.9,
            memory_exposures=10,
        )
        result = gate.decide(snap)
        assert result.gate_backend_used == "qubo"
        # Threshold result is recorded for comparison
        assert result.threshold_result is not None
        # They CAN disagree — that's the whole point
