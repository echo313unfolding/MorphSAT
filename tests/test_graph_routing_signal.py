"""Tests for graph_routing_signal — CDR-derived routing signals."""

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from morphsat.receipt_graph import ReceiptGraph
from morphsat.graph_routing_signal import (
    GraphRoutingSignal,
    extract_graph_routing_signal,
    apply_graph_signal_to_snapshot,
)


def _tmp_graph():
    """Create a temporary ReceiptGraph."""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.unlink(path)
    return ReceiptGraph(path)


def _add_receipt(graph, receipt_hash, block, outcome, direction, tags):
    """Add a receipt node with given properties."""
    receipt = {
        "final_direction": direction,
        "final_action": outcome,
        "evidence_vector": [],
        "gate_version": "test",
        "initial_state": "test",
    }
    # Override tags after node creation
    node = graph.add_node(receipt_hash, receipt, block)
    node.tags = tags
    node.outcome = direction
    node.domain = "security"
    graph._save()
    return node


class TestExtractGraphRoutingSignal:
    """Test core signal extraction."""

    def test_empty_graph_returns_no_signal(self):
        graph = _tmp_graph()
        signal = extract_graph_routing_signal(graph, ["outbound", "connection"])
        assert signal.routing_triggered is False
        assert signal.graph_memory_outcome == "unknown"
        assert signal.matching_nodes == 0

    def test_single_escalate_node_matches(self):
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "escalate",
                     ["outbound", "connection", "threat"])
        graph.auto_connect("h1")

        signal = extract_graph_routing_signal(
            graph, ["outbound", "connection"], domain="security")
        assert signal.matching_nodes >= 1
        assert signal.graph_memory_outcome == "escalate"
        assert signal.graph_memory_confidence > 0

    def test_single_benign_node_matches(self):
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "benign",
                     ["outbound", "connection", "approved"])
        graph.auto_connect("h1")

        signal = extract_graph_routing_signal(
            graph, ["outbound", "connection"], domain="security")
        assert signal.graph_memory_outcome == "benign"

    def test_drift_like_detected(self):
        """Drift: same tags, different outcomes at different times."""
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "escalate",
                     ["outbound", "connection", "pattern"])
        _add_receipt(graph, "h2", 5, "COMMIT", "benign",
                     ["outbound", "connection", "pattern"])
        graph.auto_connect("h1")
        graph.auto_connect("h2")

        signal = extract_graph_routing_signal(
            graph, ["outbound", "connection", "pattern"], domain="security")
        assert signal.drift_like is True
        assert signal.repeated_entity_changed is True
        assert signal.routing_triggered is True

    def test_stale_memory_detected(self):
        """Stale: old threat, newer benign override."""
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "escalate",
                     ["apache", "struts", "vulnerability"])
        _add_receipt(graph, "h2", 5, "COMMIT", "benign",
                     ["apache", "struts", "vulnerability", "patched"])
        graph.auto_connect("h1")
        graph.auto_connect("h2")

        signal = extract_graph_routing_signal(
            graph, ["apache", "struts", "vulnerability"], domain="security")
        assert signal.stale_memory_like is True

    def test_poisoned_memory_detected(self):
        """Poisoned: benign early, threat later for same entity."""
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "benign",
                     ["analytics", "domain", "query"])
        _add_receipt(graph, "h2", 5, "COMMIT", "escalate",
                     ["analytics", "domain", "query", "exfil"])
        graph.auto_connect("h1")
        graph.auto_connect("h2")

        signal = extract_graph_routing_signal(
            graph, ["analytics", "domain", "query"], domain="security")
        assert signal.poisoned_memory_like is True

    def test_correction_related_from_tags(self):
        """Correction: node with correction tag in matching set."""
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "escalate",
                     ["kernel", "module", "loaded"])
        _add_receipt(graph, "h2", 3, "COMMIT", "benign",
                     ["kernel", "module", "loaded", "correction"])
        graph.auto_connect("h1")
        graph.auto_connect("h2")

        signal = extract_graph_routing_signal(
            graph, ["kernel", "module", "loaded"], domain="security")
        assert signal.correction_related is True

    def test_correction_from_evidence_flag(self):
        """Correction: passed via correction_in_evidence parameter."""
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "escalate",
                     ["some", "alert", "pattern"])
        graph.auto_connect("h1")

        signal = extract_graph_routing_signal(
            graph, ["some", "alert", "pattern"],
            domain="security", correction_in_evidence=True)
        assert signal.correction_related is True

    def test_sensor_graph_conflict(self):
        """Conflict: graph says escalate, current evidence leans benign."""
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "escalate",
                     ["port", "scan", "network"])
        _add_receipt(graph, "h2", 1, "COMMIT", "escalate",
                     ["port", "scan", "brute"])
        graph.auto_connect("h1")
        graph.auto_connect("h2")

        signal = extract_graph_routing_signal(
            graph, ["port", "scan", "network"], domain="security",
            current_threat=0.1, current_safety=0.5)
        assert signal.sensor_graph_conflict is True

    def test_no_signal_on_unrelated_tags(self):
        """No routing signal when tags don't overlap (domain match alone is weak)."""
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "escalate",
                     ["network", "lateral", "movement"])

        signal = extract_graph_routing_signal(
            graph, ["certificate", "renewal", "completed"], domain="security")
        # Domain match alone may find the node but no drift/correction/conflict signals
        assert signal.routing_triggered is False
        assert signal.drift_like is False
        assert signal.correction_related is False

    def test_deterministic(self):
        """Same input produces same output."""
        graph = _tmp_graph()
        _add_receipt(graph, "h1", 0, "COMMIT", "escalate",
                     ["outbound", "connection", "threat"])
        _add_receipt(graph, "h2", 3, "COMMIT", "benign",
                     ["outbound", "connection", "approved"])
        graph.auto_connect("h1")
        graph.auto_connect("h2")

        tags = ["outbound", "connection"]
        s1 = extract_graph_routing_signal(graph, tags, domain="security")
        s2 = extract_graph_routing_signal(graph, tags, domain="security")
        assert s1.drift_like == s2.drift_like
        assert s1.graph_memory_outcome == s2.graph_memory_outcome
        assert s1.matching_nodes == s2.matching_nodes


class TestApplyGraphSignalToSnapshot:
    """Test signal application to GateSnapshot fields."""

    def test_fills_unknown_memory(self):
        signal = GraphRoutingSignal(
            graph_memory_outcome="escalate",
            graph_memory_confidence=0.8,
            graph_memory_exposures=3,
        )
        out = apply_graph_signal_to_snapshot(
            signal, "unknown", 0.0, 0, False)
        assert out[0] == "escalate"
        assert out[1] == 0.8
        assert out[2] == 3

    def test_does_not_overwrite_existing_memory(self):
        signal = GraphRoutingSignal(
            graph_memory_outcome="escalate",
            graph_memory_confidence=0.8,
            graph_memory_exposures=3,
        )
        out = apply_graph_signal_to_snapshot(
            signal, "benign", 0.9, 5, False)
        assert out[0] == "benign"  # unchanged
        assert out[1] == 0.9

    def test_correction_propagates(self):
        signal = GraphRoutingSignal(correction_related=True)
        out = apply_graph_signal_to_snapshot(
            signal, "unknown", 0.0, 0, False)
        assert out[3] is True  # correction_seen

    def test_no_double_correction(self):
        signal = GraphRoutingSignal(correction_related=False)
        out = apply_graph_signal_to_snapshot(
            signal, "unknown", 0.0, 0, True)
        assert out[3] is True  # already set, stays True
