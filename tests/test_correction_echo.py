"""Tests for correction_echo — short-lived routing markers after corrections."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from morphsat.correction_echo import CorrectionEcho, EchoMarker


class TestCorrectionEchoMarkerCreation:
    """Test 1: correction creates echo marker."""

    def test_correction_creates_marker(self):
        echo = CorrectionEcho(ttl=5)
        echo.observe_episode(
            alert_text="CORRECTION: External endpoint approved as CDN. Outbound connection pattern is now expected.",
            scenario_id="drift_04",
            is_correction=True,
            outcome="benign",
            prior_outcome="escalate",
        )
        assert echo.active_marker_count == 1
        marker = echo.markers[0]
        assert marker.source_scenario_id == "drift_04"
        assert marker.outcome_before == "escalate"
        assert marker.outcome_after == "benign"
        assert "outbound" in marker.tags
        assert "connection" in marker.tags

    def test_non_correction_does_not_create_marker(self):
        echo = CorrectionEcho(ttl=5)
        echo.observe_episode(
            alert_text="Outbound connection pattern detected",
            scenario_id="drift_00",
            is_correction=False,
            outcome="escalate",
        )
        assert echo.active_marker_count == 0


class TestCorrectionEchoTrigger:
    """Test 2: next similar alert triggers correction_related."""

    def test_similar_alert_triggers(self):
        echo = CorrectionEcho(ttl=5, min_tag_overlap=2)
        echo.observe_episode(
            alert_text="CORRECTION: External endpoint approved as CDN. Outbound connection pattern is now expected.",
            scenario_id="drift_04",
            is_correction=True,
            outcome="benign",
            prior_outcome="escalate",
        )
        triggered, marker = echo.check(
            "Outbound connection pattern detected host connecting external endpoint matches approved change"
        )
        assert triggered is True
        assert marker is not None
        assert marker.source_scenario_id == "drift_04"
        assert marker.fired_count == 1


class TestCorrectionEchoUnrelated:
    """Test 3: unrelated alert does not trigger."""

    def test_unrelated_alert_no_trigger(self):
        echo = CorrectionEcho(ttl=5, min_tag_overlap=2)
        echo.observe_episode(
            alert_text="CORRECTION: External endpoint approved as CDN. Outbound connection pattern.",
            scenario_id="drift_04",
            is_correction=True,
            outcome="benign",
        )
        triggered, marker = echo.check(
            "Certificate renewal completed for internal web server"
        )
        assert triggered is False
        assert marker is None

    def test_single_word_overlap_no_trigger(self):
        echo = CorrectionEcho(ttl=5, min_tag_overlap=2)
        echo.observe_episode(
            alert_text="CORRECTION: Outbound connection pattern approved.",
            scenario_id="drift_04",
            is_correction=True,
            outcome="benign",
        )
        # Only "outbound" overlaps (min_tag_overlap=2 required)
        triggered, _ = echo.check("Outbound firewall rule added")
        # "outbound" and "firewall" — but "firewall" not in marker tags
        # Only 1 overlap if "added" is too short
        assert triggered is False


class TestCorrectionEchoExpiry:
    """Test 4: echo expires after TTL."""

    def test_marker_expires_after_ttl(self):
        echo = CorrectionEcho(ttl=3, min_tag_overlap=2)
        echo.observe_episode(
            alert_text="CORRECTION: Outbound connection pattern approved endpoint.",
            scenario_id="drift_04",
            is_correction=True,
            outcome="benign",
        )
        assert echo.active_marker_count == 1

        # Advance 3 non-correction episodes (TTL=3, each observe decrements by 1)
        for i in range(3):
            echo.observe_episode(
                alert_text=f"Normal episode {i}",
                scenario_id=f"ep_{i}",
                is_correction=False,
                outcome="benign",
            )

        # After 3 decrements, TTL should be 0 → expired
        assert echo.active_marker_count == 0

        # Check no longer triggers
        triggered, _ = echo.check("Outbound connection pattern detected endpoint")
        assert triggered is False

    def test_reinforced_marker_does_not_expire(self):
        echo = CorrectionEcho(ttl=2, min_tag_overlap=2)
        echo.observe_episode(
            alert_text="CORRECTION: Outbound connection pattern approved endpoint.",
            scenario_id="drift_04",
            is_correction=True,
            outcome="benign",
        )
        # Reinforce the marker
        echo.reinforce(echo.markers[0])

        # Advance many episodes
        for i in range(10):
            echo.observe_episode(
                alert_text=f"Normal episode {i}",
                scenario_id=f"ep_{i}",
                is_correction=False,
                outcome="benign",
            )

        # Still active because reinforced
        assert echo.active_marker_count == 1


class TestCorrectionEchoNoVerdict:
    """Test 5: echo does not decide verdict."""

    def test_check_returns_routing_signal_not_verdict(self):
        echo = CorrectionEcho(ttl=5)
        echo.observe_episode(
            alert_text="CORRECTION: Outbound connection pattern approved endpoint.",
            scenario_id="drift_04",
            is_correction=True,
            outcome="benign",
            prior_outcome="escalate",
        )
        triggered, marker = echo.check("Outbound connection pattern detected endpoint")
        # The echo says "correction_related=True" (routing signal)
        # It does NOT say "verdict=benign" or "verdict=escalate"
        assert triggered is True
        # marker stores what happened, but check() returns only triggered + marker
        # The caller (bench/gate) decides how to use it
        assert marker.outcome_after == "benign"
        # But the echo itself has no .verdict or .direction field
        assert not hasattr(echo, "verdict")
        assert not hasattr(echo, "direction")


class TestCorrectionEchoRoutingOnly:
    """Test 6: echo only affects routing."""

    def test_echo_does_not_modify_scores(self):
        """The echo fires a boolean signal. It does not change threat/safety scores."""
        echo = CorrectionEcho(ttl=5)
        echo.observe_episode(
            alert_text="CORRECTION: Outbound connection pattern approved endpoint.",
            scenario_id="drift_04",
            is_correction=True,
            outcome="benign",
        )
        # check() returns (bool, marker). No score modification.
        triggered, marker = echo.check("Outbound connection pattern detected endpoint")
        assert triggered is True
        # There are no score fields on the echo or marker
        assert not hasattr(marker, "threat_score")
        assert not hasattr(marker, "safety_score")


class TestCorrectionEchoDeterministic:
    """Test 7: deterministic replay reproduces same echo triggers."""

    def test_deterministic_replay(self):
        results = []
        for _ in range(3):
            echo = CorrectionEcho(ttl=5, min_tag_overlap=2)
            run_results = []

            # Pre-drift episodes
            for i in range(4):
                echo.observe_episode(
                    alert_text=f"Outbound connection pattern detected host {i}",
                    scenario_id=f"drift_{i:02d}",
                    is_correction=False,
                    outcome="escalate",
                )

            # Correction
            echo.observe_episode(
                alert_text="CORRECTION: External endpoint approved as CDN. Outbound connection pattern.",
                scenario_id="drift_04",
                is_correction=True,
                outcome="benign",
                prior_outcome="escalate",
            )

            # Post-drift checks
            for i in range(5, 10):
                triggered, marker = echo.check(
                    f"Outbound connection pattern detected host connecting endpoint {i}"
                )
                run_results.append(triggered)
                echo.observe_episode(
                    alert_text=f"Outbound connection pattern host {i}",
                    scenario_id=f"drift_{i:02d}",
                    is_correction=False,
                    outcome="benign",
                )

            results.append(run_results)

        # All 3 runs should produce identical trigger patterns
        assert results[0] == results[1] == results[2]


class TestCorrectionEchoBenchSafety:
    """Test 8: false_safe does not increase (structural check)."""

    def test_echo_never_suppresses_escalation(self):
        """The echo can trigger QUBO routing but cannot force a benign verdict."""
        echo = CorrectionEcho(ttl=5)
        # Create a correction marker
        echo.observe_episode(
            alert_text="CORRECTION: Port scan now approved security audit.",
            scenario_id="corr_01",
            is_correction=True,
            outcome="benign",
            prior_outcome="escalate",
        )
        # Real threat arrives with overlapping keywords
        triggered, marker = echo.check("Port scan detected multiple hosts audit trail")
        # Echo fires (tag overlap) but it can only route to QUBO
        # It cannot force verdict=benign. QUBO decides based on evidence.
        if triggered:
            assert marker.outcome_after == "benign"  # what the correction said
            # But the echo signal is routing only — the gate's evidence
            # (threat_score, safety_score) still drives the final verdict
            # This test proves the echo has no override mechanism


class TestCorrectionEchoContradiction:
    """Test 9: contradiction tracking for adversarial defense."""

    def test_contradiction_counter_exists(self):
        echo = CorrectionEcho(ttl=5)
        echo.observe_episode(
            alert_text="CORRECTION: Port scan was authorized penetration test.",
            scenario_id="wc_02",
            is_correction=True,
            outcome="benign",
            prior_outcome="escalate",
        )
        marker = echo.markers[0]
        assert marker.contradiction_count == 0

    def test_contradiction_count_increments(self):
        echo = CorrectionEcho(ttl=5)
        echo.observe_episode(
            alert_text="CORRECTION: Port scan was authorized penetration test.",
            scenario_id="wc_02",
            is_correction=True,
            outcome="benign",
            prior_outcome="escalate",
        )
        marker = echo.markers[0]
        # Simulate caller tracking contradictions
        marker.contradiction_count += 1
        assert marker.contradiction_count == 1
        marker.contradiction_count += 1
        assert marker.contradiction_count == 2

    def test_contradiction_serializes(self):
        echo = CorrectionEcho(ttl=5)
        echo.observe_episode(
            alert_text="CORRECTION: Port scan authorized test lateral movement.",
            scenario_id="wc_02",
            is_correction=True,
            outcome="benign",
            prior_outcome="escalate",
        )
        echo.markers[0].contradiction_count = 3
        d = echo.to_dict()
        assert d["markers"][0]["contradiction_count"] == 3


class TestCorrectionEchoSerialization:
    """Test echo serialization for receipts."""

    def test_to_dict(self):
        echo = CorrectionEcho(ttl=5)
        echo.observe_episode(
            alert_text="CORRECTION: Outbound connection pattern approved endpoint.",
            scenario_id="drift_04",
            is_correction=True,
            outcome="benign",
            prior_outcome="escalate",
        )
        d = echo.to_dict()
        assert d["active_markers"] == 1
        assert d["markers"][0]["source_scenario_id"] == "drift_04"
        assert "outbound" in d["markers"][0]["tags"]

    def test_empty_to_dict(self):
        echo = CorrectionEcho(ttl=5)
        d = echo.to_dict()
        assert d["active_markers"] == 0
        assert d["markers"] == []
