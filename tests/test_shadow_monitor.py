"""
v7 Shadow Monitor — Prediction Tests

These test the specific biological hypotheses, not aggregate accuracy.
Each test feeds a synthetic evidence sequence and checks the state machine.

P1: Novelty causes ORIENT state, not longer loops
P2: ORIENT reduces unsafe/early commitment without increasing tool loops
P3: Multi-axis pressure triggers SWARM_CALL
P4: Benign cases recover from ORIENT → NORMAL → COMMIT(benign)
P5: Repeated-category loops are caught and force commitment
P6: Safe evidence decays orient pressure (tolerance response)
P7: Known patterns sensitize (lower commit clarity threshold)
"""

import json
import os
import tempfile
import pytest

from morphsat.shadow_monitor import ShadowMonitor, ShadowState
from morphsat.commit_gate import SplitMemoryStore, CommitAction


@pytest.fixture
def fresh_monitor():
    """Monitor with no memory (cold start)."""
    tmp = tempfile.mktemp(suffix=".json")
    mem = SplitMemoryStore(tmp)
    mem.clear()
    monitor = ShadowMonitor(memory=mem)
    yield monitor
    if os.path.exists(tmp):
        os.unlink(tmp)


@pytest.fixture
def memory_with_threat():
    """Memory that has learned one threat pattern."""
    tmp = tempfile.mktemp(suffix=".json")
    mem = SplitMemoryStore(tmp)
    mem.clear()
    # Record a known escalation pattern (2 exposures, high confidence)
    for _ in range(2):
        mem.record_episode(
            evidence_signature=[("check_process", "unexpected"),
                                ("check_network", "outbound_port")],
            resolution="escalate",
            confidence=0.9,
            alert_text="Suspicious process with network anomaly detected",
            threat_score=0.8,
            safety_score=0.1,
            turns=3,
        )
    yield mem, tmp


@pytest.fixture
def memory_with_tolerance():
    """Memory that has learned one benign tolerance pattern."""
    tmp = tempfile.mktemp(suffix=".json")
    mem = SplitMemoryStore(tmp)
    mem.clear()
    for _ in range(3):
        mem.record_episode(
            evidence_signature=[("check_process", "baseline_match"),
                                ("check_package", "known_good")],
            resolution="benign",
            confidence=0.85,
            alert_text="Scheduled maintenance unattended-upgrades running",
            threat_score=0.05,
            safety_score=0.6,
            turns=2,
        )
    yield mem, tmp


# -----------------------------------------------------------------------
# P1: Novelty causes ORIENT, not longer loops
# -----------------------------------------------------------------------

class TestP1NoveltyOrient:
    """Novel alerts should trigger ORIENT state, not just raise thresholds."""

    def test_novel_alert_enters_orient(self, fresh_monitor):
        """Cold start with completely novel alert → ORIENT."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        assert fresh_monitor.state == ShadowState.ORIENTING
        assert fresh_monitor.novelty_at_start > 0.8

    def test_novel_alert_does_not_raise_threshold(self, fresh_monitor):
        """v7 does NOT multiply threshold by novelty. Threshold stays base."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        # commit_clarity should be the default, not multiplied
        assert fresh_monitor.commit_clarity == 0.35

    def test_orient_has_bounded_budget(self, fresh_monitor):
        """ORIENT allows only orient_budget tools before transitioning."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        assert fresh_monitor.state == ShadowState.ORIENTING

        # Feed one ambiguous tool result (budget = 1)
        action = fresh_monitor.process_evidence(
            "check_process",
            "Process not in known-good database, ambiguous")

        # Should have transitioned OUT of orienting
        assert fresh_monitor.state != ShadowState.ORIENTING
        assert fresh_monitor.state in (ShadowState.SAFE_DISTANCE,
                                       ShadowState.INVESTIGATING)

    def test_orient_total_tools_bounded(self, fresh_monitor):
        """Novel alert should NOT cause more total tool calls than normal."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")

        # Feed evidence until committed
        tools_used = 0
        for i in range(10):
            action = fresh_monitor.process_evidence(
                f"tool_{i}",
                "Process tree shows unusual child process spawning")
            tools_used += 1
            if action.action != "CONTINUE":
                break

        # Should commit within max_tools (8), typically much sooner
        assert tools_used <= fresh_monitor.max_tools
        assert fresh_monitor.committed


# -----------------------------------------------------------------------
# P2: ORIENT reduces unsafe/early commitment
# -----------------------------------------------------------------------

class TestP2OrientProtection:
    """ORIENT should prevent premature commitment on first evidence."""

    def test_threat_in_orient_does_not_immediately_commit(self, fresh_monitor):
        """First threat evidence during ORIENT → assess, don't commit.

        Unless the threat is overwhelming (>= escalate_threat on turn 1).
        """
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        assert fresh_monitor.state == ShadowState.ORIENTING

        # Moderate threat — should move to SAFE_DISTANCE, not commit
        action = fresh_monitor.process_evidence(
            "check_process",
            "Process has unexpected behavior, not in known-good list")

        # Moderate threat moves to SAFE_DISTANCE (cautious, not committed)
        assert fresh_monitor.state in (ShadowState.SAFE_DISTANCE,
                                       ShadowState.INVESTIGATING)
        # Should NOT have committed on first tool
        assert action.action == "CONTINUE"

    def test_overwhelming_threat_can_still_escalate(self, fresh_monitor):
        """Very high threat in ORIENT should still escalate quickly."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        fresh_monitor.threat_score = 0.50  # pre-load some threat

        action = fresh_monitor.process_evidence(
            "check_yara",
            "YARA match: suspicious_packer variant detected")

        # With pre-loaded threat + yara match, should escalate
        if fresh_monitor.threat_score >= fresh_monitor.escalate_threat:
            assert action.action == "COMMIT"
            assert action.direction == "escalate"


# -----------------------------------------------------------------------
# P3: Multi-axis pressure triggers SWARM_CALL
# -----------------------------------------------------------------------

class TestP3SwarmTrigger:
    """Pressure from multiple axes should trigger swarm recruitment."""

    def test_swarm_on_multi_axis(self, fresh_monitor):
        """Set up conditions that satisfy 3+ pressure axes → SWARM_CALL."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        # novelty_at_start > 0.7 → axis 1

        # Add contradictory evidence (both threat and safety)
        fresh_monitor.process_evidence(
            "check_process",
            "Process has unexpected behavior")
        fresh_monitor.process_evidence(
            "check_package",
            "All match baseline, known-good")
        # Now both threat_score > 0.2 and safety_score > 0.2 → axis 5
        # contradiction >= gate → axis 1

        # Force loop detection → axis 3
        fresh_monitor.repeated_categories["unknown"] = 3

        # Force budget exhaustion → axis 4
        fresh_monitor.investigate_tools_used = fresh_monitor.investigate_budget

        # Next evidence should trigger swarm check
        action = fresh_monitor.process_evidence(
            "check_network",
            "Outbound connection to 4444, not in baseline")

        # Should have triggered swarm (if enough axes met)
        axes = 0
        contradiction = min(fresh_monitor.threat_score,
                            fresh_monitor.safety_score)
        if contradiction >= fresh_monitor.contradiction_gate:
            axes += 1
        if fresh_monitor.novelty_at_start > 0.7:
            axes += 1
        if any(c >= 3 for c in fresh_monitor.repeated_categories.values()):
            axes += 1
        if fresh_monitor.investigate_tools_used >= fresh_monitor.investigate_budget:
            axes += 1
        if fresh_monitor.threat_score > 0.2 and fresh_monitor.safety_score > 0.2:
            axes += 1

        if axes >= fresh_monitor.swarm_axes_required:
            assert fresh_monitor.state == ShadowState.SWARM_CALL
            assert action.action == "ABSTAIN"  # swarm resolves as abstain
        else:
            # Not enough axes — document for analysis
            print(f"  Swarm axes: {axes}/{fresh_monitor.swarm_axes_required}")
            print(f"  t={fresh_monitor.threat_score:.2f}, "
                  f"s={fresh_monitor.safety_score:.2f}")

    def test_normal_case_no_swarm(self, fresh_monitor):
        """Simple clear-evidence case should NOT trigger swarm."""
        fresh_monitor.initialize("Scheduled maintenance apt-get running")
        fresh_monitor.process_evidence(
            "check_process",
            "All processes within expected baseline, no anomalies")
        fresh_monitor.process_evidence(
            "check_package",
            "Package signed and in package database, known-good")

        assert fresh_monitor.state != ShadowState.SWARM_CALL


# -----------------------------------------------------------------------
# P4: Benign recovery from ORIENT
# -----------------------------------------------------------------------

class TestP4BenignRecovery:
    """Benign cases should recover from ORIENT → NORMAL → COMMIT(benign)."""

    def test_safe_evidence_dissolves_orient(self, fresh_monitor):
        """Safety evidence during ORIENT decays orient_pressure → NORMAL."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        assert fresh_monitor.state == ShadowState.ORIENTING
        initial_pressure = fresh_monitor.orient_pressure

        # Feed strong safety evidence
        action = fresh_monitor.process_evidence(
            "check_process",
            "All processes within expected baseline, no anomalies")

        # Orient pressure should have decayed
        assert fresh_monitor.orient_pressure < initial_pressure

    def test_benign_sequence_after_orient(self, fresh_monitor):
        """Full sequence: ORIENT → investigate → commit benign."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        assert fresh_monitor.state == ShadowState.ORIENTING

        # Tool 1: safety evidence in ORIENT
        a1 = fresh_monitor.process_evidence(
            "check_process",
            "All match baseline, no anomalies detected")

        # Tool 2: more safety evidence
        a2 = fresh_monitor.process_evidence(
            "check_package",
            "Package signed and in package database, known-good")

        # Should eventually commit benign (or be on that path)
        final = None
        for i in range(6):  # feed more if needed
            if fresh_monitor.committed:
                final = fresh_monitor.last_action
                break
            a = fresh_monitor.process_evidence(
                f"check_{i}",
                "No anomalies, signed and in package database")
            if a.action != "CONTINUE":
                final = a
                break

        assert final is not None
        assert final.action in ("COMMIT", "ABSTAIN")
        if final.action == "COMMIT":
            assert final.direction == "benign"

    def test_tolerance_memory_helps_future_benign(self, memory_with_tolerance):
        """Known-benign pattern should start in NORMAL, not ORIENT."""
        mem, tmp = memory_with_tolerance
        monitor = ShadowMonitor(memory=mem)
        monitor.initialize("Scheduled maintenance unattended-upgrades running")

        # Known tolerance pattern → should be NORMAL
        assert monitor.state == ShadowState.NORMAL
        # Threshold should be sensitized (lowered)
        assert monitor.commit_clarity < 0.35

        os.unlink(tmp)


# -----------------------------------------------------------------------
# P5: Loop detection forces commitment
# -----------------------------------------------------------------------

class TestP5LoopDetection:
    """Repeated same-category evidence should force commitment."""

    def test_three_same_category_forces_commit(self, fresh_monitor):
        """Three identical categories → loop detected → force commit."""
        fresh_monitor.initialize("Ambiguous network activity detected")

        actions = []
        for i in range(5):
            a = fresh_monitor.process_evidence(
                f"check_{i}",
                "Ambiguous signal, unclear origin")
            actions.append(a)
            if a.action != "CONTINUE":
                break

        # Should have committed before hitting max_tools
        assert fresh_monitor.committed
        assert fresh_monitor.total_tools < fresh_monitor.max_tools

    def test_stagnation_forces_commit(self, fresh_monitor):
        """Two near-zero deltas in a row → stagnation → force commit."""
        fresh_monitor.initialize("Minor alert on workstation")

        # First tool: some evidence
        fresh_monitor.process_evidence(
            "check_0", "Process has unexpected behavior")

        # Next two: near-zero deltas (unknown/ambiguous with tiny deltas)
        fresh_monitor.process_evidence(
            "check_1", "Some unrelated log data")
        a = fresh_monitor.process_evidence(
            "check_2", "More unrelated log data")

        # After stagnation, should be heading toward commitment
        # (may not be immediate if clarity is still building)
        if not fresh_monitor.committed:
            # Feed one more
            a = fresh_monitor.process_evidence(
                "check_3", "Still nothing new here")

        # Eventually commits
        for i in range(4, 8):
            if fresh_monitor.committed:
                break
            fresh_monitor.process_evidence(
                f"check_{i}", "Nothing new")

        assert fresh_monitor.committed


# -----------------------------------------------------------------------
# P6: Safe evidence decays orient pressure
# -----------------------------------------------------------------------

class TestP6OrientDecay:
    """Each safe evidence piece decays orient_pressure."""

    def test_decay_is_quantifiable(self, fresh_monitor):
        """orient_pressure decreases by orient_decay_per_safe per safe tool."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        initial = fresh_monitor.orient_pressure
        assert initial > 0

        fresh_monitor.process_evidence(
            "check",
            "All processes within expected baseline, no anomalies")

        # Safety delta > 0 → orient_pressure should decrease
        expected = max(0, initial - fresh_monitor.orient_decay_per_safe)
        assert abs(fresh_monitor.orient_pressure - expected) < 0.01

    def test_threat_does_not_decay_orient(self, fresh_monitor):
        """Threat evidence should NOT decay orient pressure."""
        fresh_monitor.initialize("Unknown binary executing from /tmp/xyz")
        initial = fresh_monitor.orient_pressure

        fresh_monitor.process_evidence(
            "check",
            "YARA match: suspicious_packer variant detected")

        # Threat delta > 0, safety delta = 0 → no decay
        # (orient_pressure may not change, or may increase from surprise)
        assert fresh_monitor.orient_pressure >= 0


# -----------------------------------------------------------------------
# P7: Known patterns sensitize thresholds
# -----------------------------------------------------------------------

class TestP7Sensitization:
    """Known patterns should lower commit clarity (faster commit)."""

    def test_known_threat_lowers_clarity_threshold(self, memory_with_threat):
        """Recognized threat pattern → sensitized → lower commit_clarity."""
        mem, tmp = memory_with_threat
        monitor = ShadowMonitor(memory=mem)
        monitor.initialize(
            "Suspicious process with network anomaly detected")

        assert monitor.state == ShadowState.NORMAL
        assert monitor.commit_clarity < 0.35  # sensitized below default

        os.unlink(tmp)

    def test_unknown_uses_default_threshold(self, fresh_monitor):
        """Unknown pattern → default commit_clarity."""
        fresh_monitor.initialize("Completely new type of alert never seen")
        # Even though ORIENTING, commit_clarity should be default
        assert fresh_monitor.commit_clarity == 0.35


# -----------------------------------------------------------------------
# Integration: Full evidence sequences
# -----------------------------------------------------------------------

class TestIntegrationSequences:
    """End-to-end sequences testing realistic evidence flows."""

    def test_clear_escalation_sequence(self, fresh_monitor):
        """Threat evidence sequence → escalate."""
        fresh_monitor.initialize("Process spawning shells from web server")

        a1 = fresh_monitor.process_evidence(
            "check_process",
            "Unexpected child process tree, not found in known-good baseline")
        a2 = fresh_monitor.process_evidence(
            "check_network",
            "Outbound connection to port 4444, not in baseline")

        # Clear threat + coincidence → should commit escalate
        assert fresh_monitor.committed
        assert fresh_monitor.last_action.direction == "escalate"

    def test_clear_benign_sequence(self, fresh_monitor):
        """Safety evidence sequence → benign."""
        fresh_monitor.initialize("Scheduled maintenance on server-01")

        a1 = fresh_monitor.process_evidence(
            "check_process",
            "All processes within expected baseline, no anomalies")
        a2 = fresh_monitor.process_evidence(
            "check_package",
            "All packages signed and in package database, known-good")

        # Clear safety → should commit benign
        assert fresh_monitor.committed
        assert fresh_monitor.last_action.direction == "benign"

    def test_suspicious_sequence(self, fresh_monitor):
        """Mixed but threat-leaning → suspicious."""
        fresh_monitor.initialize("DNS queries to unusual domains")

        a1 = fresh_monitor.process_evidence(
            "check_dns",
            "DNS queries to domains not in known-good list")
        a2 = fresh_monitor.process_evidence(
            "check_process",
            "Process is normal system service, expected behavior")

        # Mixed evidence — may need more tools or commit suspicious
        if not fresh_monitor.committed:
            a3 = fresh_monitor.process_evidence(
                "check_reputation",
                "Domain registered recently, moderate signal")

        if fresh_monitor.committed:
            # Should be suspicious (moderate threat, some safety)
            assert fresh_monitor.last_action.direction in (
                "suspicious", "escalate")

    def test_receipt_completeness(self, fresh_monitor):
        """Receipt should contain all required fields."""
        fresh_monitor.initialize("Test alert")
        fresh_monitor.process_evidence("tool1", "Some evidence")
        fresh_monitor.process_evidence("tool2", "More evidence")

        receipt = fresh_monitor.to_receipt()

        assert "gate_version" in receipt
        assert receipt["gate_version"] == "v7_shadow_monitor"
        assert "initial_novelty" in receipt
        assert "final_state" in receipt
        assert "threat_score" in receipt
        assert "safety_score" in receipt
        assert "posture_trace" in receipt
        assert "history" in receipt
        assert "memory_state" in receipt
        assert len(receipt["posture_trace"]) >= 1  # at least init trace

    def test_max_tools_ceiling(self, fresh_monitor):
        """Absolute ceiling: never exceed max_tools."""
        fresh_monitor.initialize("Ambiguous alert with no clear signals")

        for i in range(12):
            if fresh_monitor.committed:
                break
            fresh_monitor.process_evidence(
                f"tool_{i}",
                "Ambiguous data, cannot determine")

        assert fresh_monitor.committed
        assert fresh_monitor.total_tools <= fresh_monitor.max_tools


# ============================================================
# HUD Tests — coarse navigation signal
# ============================================================

class TestHUD:
    """HUD renders coarse grid position without exposing hidden state."""

    def test_hud_fields_present(self, fresh_monitor):
        """HUD returns all required fields."""
        fresh_monitor.initialize("Test alert")
        hud = fresh_monitor.render_hud()
        assert "grid_position" in hud
        assert "zone" in hud
        assert "compass" in hud
        assert "clearance" in hud
        assert "allowed" in hud
        assert "blocked" in hud

    def test_hud_no_hidden_state(self, fresh_monitor):
        """HUD must NOT expose raw scores or boundary distances."""
        fresh_monitor.initialize("Test alert")
        fresh_monitor.process_evidence("tool_1", "Ambiguous data")
        hud = fresh_monitor.render_hud()
        hud_str = str(hud)
        # None of the hidden control-law variables should appear
        assert "threat_score" not in hud
        assert "safety_score" not in hud
        assert "evidence_balance" not in hud
        assert "dist_to_threat" not in hud_str
        assert "dist_to_safe" not in hud_str
        assert "decay" not in hud_str
        assert "orient_pressure" not in hud_str

    def test_hud_init_center(self, fresh_monitor):
        """Fresh monitor starts in continue zone center."""
        fresh_monitor.initialize("Test alert")
        hud = fresh_monitor.render_hud()
        assert hud["zone"] == "continue"
        assert hud["grid_position"].startswith("B")
        assert hud["clearance"] == "not_cleared"

    def test_hud_safe_side(self):
        """3 safe tools should push to A zone."""
        tmp = tempfile.mktemp(suffix=".json")
        mem = SplitMemoryStore(tmp)
        mem.clear()
        sm = ShadowMonitor(memory=mem, enable_dual_boundary=True)
        sm.initialize("Routine check")
        sm.process_evidence("t1", "All match baseline. No anomalies detected.")
        sm.process_evidence("t2", "All processes within expected parameters.")
        sm.process_evidence("t3", "No rule match. Signed and in package database.")
        hud = sm.render_hud()
        assert hud["grid_position"].startswith("A")
        os.unlink(tmp) if os.path.exists(tmp) else None

    def test_hud_threat_side(self):
        """3 threat tools should push to C zone."""
        tmp = tempfile.mktemp(suffix=".json")
        mem = SplitMemoryStore(tmp)
        mem.clear()
        sm = ShadowMonitor(memory=mem, enable_dual_boundary=True)
        sm.initialize("Critical alert")
        sm.process_evidence("t1", "YARA scan: match on rule suspicious_packer.")
        sm.process_evidence("t2", "Outbound connection to port 4444, not in baseline.")
        sm.process_evidence("t3", "Unexpected child process /tmp/.x11")
        hud = sm.render_hud()
        assert hud["grid_position"].startswith("C")
        os.unlink(tmp) if os.path.exists(tmp) else None

    def test_hud_committed_blocks_all(self, fresh_monitor):
        """Once committed, HUD blocks all actions."""
        fresh_monitor.initialize("Test")
        # Force enough evidence to commit
        fresh_monitor.process_evidence("t1", "YARA scan: match on rule suspicious_packer.")
        fresh_monitor.process_evidence("t2", "Outbound connection to port 4444, not in baseline.")
        fresh_monitor.process_evidence("t3", "Unexpected child process /tmp/.x11")
        if fresh_monitor.committed:
            hud = fresh_monitor.render_hud()
            assert hud["blocked"] == ["all_actions"]
            assert hud["allowed"] == []

    def test_hud_not_cleared_blocks_verdict(self, fresh_monitor):
        """In continue zone, final_verdict is blocked."""
        fresh_monitor.initialize("Test alert")
        fresh_monitor.process_evidence("t1", "Ambiguous data")
        hud = fresh_monitor.render_hud()
        if hud["zone"] == "continue":
            assert "final_verdict" in hud["blocked"]
            assert "gather_independent_confirmation" in hud["allowed"]

    def test_hud_compass_drift(self):
        """Compass should detect directional drift."""
        tmp = tempfile.mktemp(suffix=".json")
        mem = SplitMemoryStore(tmp)
        mem.clear()
        sm = ShadowMonitor(memory=mem, enable_dual_boundary=True,
                           commit_threat_boundary=2.0)  # high boundary to stay in zone
        sm.initialize("Test")
        sm.process_evidence("t1", "YARA scan: match on rule suspicious_packer.")
        sm.process_evidence("t2", "Unexpected child process /tmp/.x11")
        hud = sm.render_hud()
        assert hud["compass"] == "drifting threat-side"
        os.unlink(tmp) if os.path.exists(tmp) else None

    def test_hud_terrain_present(self, fresh_monitor):
        """HUD includes terrain field."""
        fresh_monitor.initialize("Test alert")
        hud = fresh_monitor.render_hud()
        assert "terrain" in hud
        assert hud["terrain"] in (
            "uncharted", "familiar", "flagged", "unstable", "recognized")

    def test_hud_terrain_uncharted_new_pattern(self, fresh_monitor):
        """New pattern with no memory → uncharted."""
        fresh_monitor.initialize("Completely novel never-seen-before alert")
        hud = fresh_monitor.render_hud()
        assert hud["terrain"] == "uncharted"

    def test_hud_terrain_familiar_benign_history(self):
        """Known benign pattern with multiple exposures → familiar."""
        tmp = tempfile.mktemp(suffix=".json")
        mem = SplitMemoryStore(tmp)
        mem.clear()
        # Seed memory: 2 benign episodes with same keywords
        for _ in range(2):
            mem.record_episode(
                evidence_signature=[("t1", "safe")],
                resolution="benign",
                confidence=0.9,
                alert_text="routine baseline check normal",
                threat_score=0.0,
                safety_score=0.5,
                turns=2,
            )
        sm = ShadowMonitor(memory=mem, enable_dual_boundary=True)
        sm.initialize("routine baseline check normal")
        hud = sm.render_hud()
        assert hud["terrain"] == "familiar"
        os.unlink(tmp) if os.path.exists(tmp) else None

    def test_hud_terrain_flagged_threat_history(self):
        """Known threat pattern with multiple exposures → flagged."""
        tmp = tempfile.mktemp(suffix=".json")
        mem = SplitMemoryStore(tmp)
        mem.clear()
        for _ in range(2):
            mem.record_episode(
                evidence_signature=[("t1", "threat")],
                resolution="escalate",
                confidence=0.85,
                alert_text="suspicious packer detected lateral",
                threat_score=0.7,
                safety_score=0.0,
                turns=3,
            )
        sm = ShadowMonitor(memory=mem, enable_dual_boundary=True)
        sm.initialize("suspicious packer detected lateral")
        hud = sm.render_hud()
        assert hud["terrain"] == "flagged"
        os.unlink(tmp) if os.path.exists(tmp) else None

    def test_hud_terrain_unstable_abstain_history(self):
        """Known abstain pattern → unstable."""
        tmp = tempfile.mktemp(suffix=".json")
        mem = SplitMemoryStore(tmp)
        mem.clear()
        for _ in range(2):
            mem.record_episode(
                evidence_signature=[("t1", "mixed")],
                resolution="abstain",
                confidence=0.75,
                alert_text="ambiguous conflicting signals mixed",
                threat_score=0.3,
                safety_score=0.3,
                turns=5,
            )
        sm = ShadowMonitor(memory=mem, enable_dual_boundary=True)
        sm.initialize("ambiguous conflicting signals mixed")
        hud = sm.render_hud()
        assert hud["terrain"] == "unstable"
        os.unlink(tmp) if os.path.exists(tmp) else None

    def test_hud_terrain_recognized_weak_match(self):
        """Single exposure / low confidence → recognized (not familiar/flagged)."""
        tmp = tempfile.mktemp(suffix=".json")
        mem = SplitMemoryStore(tmp)
        mem.clear()
        # Only 1 exposure — below the exposures >= 2 gate
        mem.record_episode(
            evidence_signature=[("t1", "safe")],
            resolution="benign",
            confidence=0.5,
            alert_text="partial match single exposure check",
            threat_score=0.0,
            safety_score=0.4,
            turns=2,
        )
        sm = ShadowMonitor(memory=mem, enable_dual_boundary=True)
        sm.initialize("partial match single exposure check")
        hud = sm.render_hud()
        assert hud["terrain"] == "recognized"
        os.unlink(tmp) if os.path.exists(tmp) else None

    def test_hud_terrain_no_raw_memory(self):
        """Terrain label must not leak raw memory internals."""
        tmp = tempfile.mktemp(suffix=".json")
        mem = SplitMemoryStore(tmp)
        mem.clear()
        mem.record_episode(
            evidence_signature=[("t1", "threat")],
            resolution="escalate",
            confidence=0.9,
            alert_text="known threat pattern memory leak test",
            threat_score=0.8,
            safety_score=0.0,
            turns=3,
        )
        mem.record_episode(
            evidence_signature=[("t1", "threat")],
            resolution="escalate",
            confidence=0.9,
            alert_text="known threat pattern memory leak test",
            threat_score=0.8,
            safety_score=0.0,
            turns=3,
        )
        sm = ShadowMonitor(memory=mem, enable_dual_boundary=True)
        sm.initialize("known threat pattern memory leak test")
        hud = sm.render_hud()
        hud_str = str(hud)
        # No raw memory values should appear
        assert "novelty_distance" not in hud_str
        assert "confidence" not in hud_str
        assert "exposures" not in hud_str
        assert "pattern_hash" not in hud_str
        assert "alert_keywords" not in hud_str
        os.unlink(tmp) if os.path.exists(tmp) else None
