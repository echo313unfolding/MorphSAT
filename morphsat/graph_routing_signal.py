"""
Graph Routing Signal — CDR-derived signals for TwoStageGate routing.
====================================================================

Distilled from SplitMemory CDR replay. The graph can now trigger
TwoStageGate routing (threshold vs QUBO) without SplitMemory.

The "old guy" (SplitMemory) helped because he noticed:
    1. Correction receipts in memory → correction_seen → QUBO route
    2. Prior threat entries matching current keywords → memory_outcome="escalate"
    3. Prior tolerance entries matching current keywords → memory_outcome="benign"
    4. Contradictory history (threat then benign) → drift_like
    5. Repeated entity with changed outcome → stale/poisoned patterns

The graph has all this data in its edges and nodes. This module
extracts routing signals FROM the graph that parallel what SplitMemory
would have found — so TwoStageGate can route without SplitMemory.

These signals influence ROUTING only, not final decision.

Lineage:
    SplitMemory.lookup() → CDR trace → graph_routing_signal → TwoStageGate._route()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from morphsat.receipt_graph import ReceiptGraph, ReceiptNode, ReceiptEdge, COLD_THRESHOLD


@dataclass
class GraphRoutingSignal:
    """Routing signals derived from ReceiptGraph, replacing SplitMemory lookup."""
    # Core routing signals (parallel SplitMemory's role)
    graph_memory_outcome: str = "unknown"   # benign/escalate/suspicious/unknown
    graph_memory_confidence: float = 0.0    # 0-1, how strong the graph signal is
    graph_memory_exposures: int = 0         # how many matching nodes found

    # Derived signals (what the old guy noticed)
    drift_like: bool = False                # outcome changed for same entity
    correction_related: bool = False        # correction node in matching set
    stale_memory_like: bool = False         # old threat edges, newer benign override
    poisoned_memory_like: bool = False      # benign entries followed by threat
    sensor_graph_conflict: bool = False     # current evidence vs graph disagree
    repeated_entity_changed: bool = False   # same tags, different outcome

    # Evidence for receipt
    matching_nodes: int = 0
    matching_active_edges: int = 0
    outcome_distribution: Dict[str, int] = field(default_factory=dict)
    strongest_signal: str = "none"          # which signal triggered routing
    routing_triggered: bool = False


def extract_graph_routing_signal(
    graph: ReceiptGraph,
    alert_tags: List[str],
    domain: str = "security",
    current_threat: float = 0.0,
    current_safety: float = 0.0,
    correction_in_evidence: bool = False,
) -> GraphRoutingSignal:
    """Extract routing signals from ReceiptGraph for a given alert.

    This replaces SplitMemory.lookup() for routing purposes.
    Does NOT make final decisions — only produces signals that
    TwoStageGate uses to choose threshold vs QUBO backend.
    """
    signal = GraphRoutingSignal()
    alert_tag_set = set(alert_tags)

    if not alert_tag_set or graph.node_count == 0:
        return signal

    # Step 1: Find matching nodes (same logic as graph.predict but
    # we keep the node details instead of just the prediction)
    matching: List[Tuple[ReceiptNode, float]] = []
    for node in graph.nodes.values():
        score = 0.0
        if domain and node.domain == domain:
            score += 0.3
        node_tag_set = set(node.tags)
        tag_overlap = len(alert_tag_set & node_tag_set)
        if tag_overlap >= 2:
            score += tag_overlap * 0.2
        elif tag_overlap == 1:
            score += 0.1
        if score > 0.2:
            matching.append((node, score))

    signal.matching_nodes = len(matching)
    if not matching:
        return signal

    # Step 2: Count outcome distribution in matching nodes
    outcome_counts: Dict[str, float] = {}
    for node, score in matching:
        if node.outcome != "unknown":
            outcome_counts[node.outcome] = outcome_counts.get(
                node.outcome, 0.0) + score

    signal.outcome_distribution = {
        k: int(v * 10) for k, v in outcome_counts.items()
    }

    # Step 3: Determine graph_memory_outcome (weighted vote)
    if outcome_counts:
        total_weight = sum(outcome_counts.values())
        best_outcome = max(outcome_counts, key=outcome_counts.get)
        best_weight = outcome_counts[best_outcome]

        signal.graph_memory_outcome = best_outcome
        signal.graph_memory_confidence = min(1.0, best_weight / max(total_weight, 0.01))
        signal.graph_memory_exposures = len(matching)

    # Step 4: Check for drift_like signal
    # Drift = matching nodes have DIFFERENT outcomes (some escalate, some benign)
    outcomes_seen = set(outcome_counts.keys())
    has_threat = bool(outcomes_seen & {"escalate", "suspicious"})
    has_safe = "benign" in outcomes_seen
    if has_threat and has_safe:
        signal.drift_like = True
        signal.repeated_entity_changed = True

    # Step 5: Check for correction_related
    # Any matching node that came from a correction episode
    for node, score in matching:
        node_tags_lower = [t.lower() for t in node.tags]
        if any("correction" in t for t in node_tags_lower):
            signal.correction_related = True
            break
    # Also check if current evidence stream has correction
    if correction_in_evidence:
        signal.correction_related = True

    # Step 6: Check for stale_memory_like
    # Old nodes say "escalate", newer nodes say "benign" for same entity
    if has_threat and has_safe and len(matching) >= 2:
        threat_nodes = [(n, s) for n, s in matching
                        if n.outcome in ("escalate", "suspicious")]
        safe_nodes = [(n, s) for n, s in matching if n.outcome == "benign"]
        if threat_nodes and safe_nodes:
            max_threat_block = max(n.block_number for n, _ in threat_nodes)
            max_safe_block = max(n.block_number for n, _ in safe_nodes)
            if max_safe_block > max_threat_block:
                signal.stale_memory_like = True

    # Step 7: Check for poisoned_memory_like
    # Benign entries early, threat entries later for same entity
    if has_threat and has_safe and len(matching) >= 2:
        threat_nodes = [(n, s) for n, s in matching
                        if n.outcome in ("escalate", "suspicious")]
        safe_nodes = [(n, s) for n, s in matching if n.outcome == "benign"]
        if threat_nodes and safe_nodes:
            min_safe_block = min(n.block_number for n, _ in safe_nodes)
            max_threat_block = max(n.block_number for n, _ in threat_nodes)
            if max_threat_block > min_safe_block:
                signal.poisoned_memory_like = True

    # Step 8: Check sensor_graph_conflict
    # Current evidence leans one way, graph history leans the other
    if signal.graph_memory_confidence > 0.3:
        sensor_dir = "benign" if current_safety > current_threat else "escalate"
        if signal.graph_memory_outcome != sensor_dir:
            signal.sensor_graph_conflict = True

    # Step 9: Count active edges among matching nodes
    matching_hashes = {n.receipt_hash for n, _ in matching}
    for edge in graph.edges:
        if edge.is_cold:
            continue
        if edge.from_hash in matching_hashes or edge.to_hash in matching_hashes:
            signal.matching_active_edges += 1

    # Step 10: Determine strongest signal and whether routing triggered
    signal_strength = {
        "drift_like": 3 if signal.drift_like else 0,
        "correction_related": 3 if signal.correction_related else 0,
        "stale_memory_like": 2 if signal.stale_memory_like else 0,
        "poisoned_memory_like": 2 if signal.poisoned_memory_like else 0,
        "sensor_graph_conflict": 2 if signal.sensor_graph_conflict else 0,
        "repeated_entity_changed": 1 if signal.repeated_entity_changed else 0,
    }

    max_signal = max(signal_strength, key=signal_strength.get)
    if signal_strength[max_signal] > 0:
        signal.strongest_signal = max_signal
        signal.routing_triggered = True

    return signal


def apply_graph_signal_to_snapshot(
    signal: GraphRoutingSignal,
    snap_memory_outcome: str,
    snap_memory_confidence: float,
    snap_memory_exposures: int,
    snap_correction_seen: bool,
) -> Tuple[str, float, int, bool]:
    """Apply graph routing signal to GateSnapshot fields.

    Returns (memory_outcome, memory_confidence, memory_exposures, correction_seen)
    that should be set on the GateSnapshot before passing to TwoStageGate.

    Only overwrites if graph has a real signal AND no SplitMemory signal exists.
    """
    out_outcome = snap_memory_outcome
    out_confidence = snap_memory_confidence
    out_exposures = snap_memory_exposures
    out_correction = snap_correction_seen

    # Only fill in if SplitMemory didn't already provide a signal
    if out_outcome == "unknown" and signal.graph_memory_outcome != "unknown":
        out_outcome = signal.graph_memory_outcome
        out_confidence = signal.graph_memory_confidence
        out_exposures = signal.graph_memory_exposures

    # Correction signal: graph can trigger this independently
    if signal.correction_related and not out_correction:
        out_correction = True

    return out_outcome, out_confidence, out_exposures, out_correction
