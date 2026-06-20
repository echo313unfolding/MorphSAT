"""
Receipt Graph — Layer 2 Tests

Tests the living associative memory and error-correction loop:
1. Node creation from receipt
2. Manual edge creation
3. Auto-connect finds related receipts
4. Reinforcement increases weight
5. Decay reduces weight over time
6. Cold edges stop appearing in retrieval
7. Cold edges still exist in graph (provenance preserved)
8. Contradiction weakens edges
9. Prediction from graph patterns
10. Score prediction — correct → reinforce
11. Score prediction — wrong → weaken
12. Full error-correction loop (predict → act → score → adapt)
13. HUD exposes summary, not weights
14. Persistence roundtrip
15. Different receipt classes decay at different rates
"""

import os
import tempfile

import pytest

from morphsat.receipt_chain import canonical_hash
from morphsat.receipt_graph import (
    ReceiptGraph,
    ReceiptNode,
    ReceiptEdge,
    COLD_THRESHOLD,
    REINFORCE_BOOST,
    CONTRADICT_PENALTY,
    DECAY_RATES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def graph_path():
    tmp = tempfile.mktemp(suffix=".json")
    yield tmp
    if os.path.exists(tmp):
        os.unlink(tmp)


@pytest.fixture
def graph(graph_path):
    return ReceiptGraph(graph_path)


def make_receipt(tag: str, direction: str = "benign",
                 action: str = "COMMIT", domain_cat: str = "safe") -> dict:
    return {
        "gate_version": "v7_shadow_monitor",
        "tag": tag,
        "final_action": action,
        "final_direction": direction,
        "initial_state": "normal",
        "threat_score": 0.1 if direction == "benign" else 0.7,
        "safety_score": 0.7 if direction == "benign" else 0.1,
        "evidence_vector": [("tool1", domain_cat), ("tool2", domain_cat)],
    }


def add_receipt_node(graph, tag, **kwargs):
    """Helper: create receipt, hash it, add as node."""
    receipt = make_receipt(tag, **kwargs)
    h = canonical_hash(receipt)
    graph.add_node(h, receipt, block_number=0)
    return h, receipt


# ---------------------------------------------------------------------------
# 1. Node creation
# ---------------------------------------------------------------------------

class TestNodeCreation:

    def test_add_node(self, graph):
        h, r = add_receipt_node(graph, "r1")
        assert h in graph.nodes
        assert graph.node_count == 1
        assert graph.nodes[h].outcome == "benign"
        assert graph.nodes[h].action == "COMMIT"

    def test_domain_extraction(self, graph):
        h, _ = add_receipt_node(graph, "r1", domain_cat="threat")
        assert graph.nodes[h].domain == "threat"

    def test_tag_extraction(self, graph):
        h, _ = add_receipt_node(graph, "r1")
        tags = graph.nodes[h].tags
        assert "v7_shadow_monitor" in tags
        assert "COMMIT" in tags
        assert "benign" in tags


# ---------------------------------------------------------------------------
# 2-3. Edge creation and auto-connect
# ---------------------------------------------------------------------------

class TestEdgeCreation:

    def test_manual_connect(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        edge = graph.connect(h1, h2, "same_domain", ["test"])
        assert edge is not None
        assert edge.weight == 0.5
        assert graph.edge_count == 1

    def test_no_duplicate_edges(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        graph.connect(h1, h2, "same_domain")
        graph.connect(h1, h2, "same_domain")  # duplicate
        assert graph.edge_count == 1

    def test_different_edge_types_allowed(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        graph.connect(h1, h2, "same_domain")
        graph.connect(h1, h2, "same_outcome")
        assert graph.edge_count == 2

    def test_connect_unknown_hash_returns_none(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        assert graph.connect(h1, "nonexistent", "test") is None

    def test_auto_connect_same_domain(self, graph):
        h1, _ = add_receipt_node(graph, "r1", domain_cat="threat")
        h2, _ = add_receipt_node(graph, "r2", domain_cat="threat")
        edges = graph.auto_connect(h2)
        types = [e.edge_type for e in edges]
        assert "same_domain" in types

    def test_auto_connect_same_outcome(self, graph):
        h1, _ = add_receipt_node(graph, "r1", direction="escalate")
        h2, _ = add_receipt_node(graph, "r2", direction="escalate")
        edges = graph.auto_connect(h2)
        types = [e.edge_type for e in edges]
        assert "same_outcome" in types

    def test_auto_connect_different_domains_no_domain_edge(self, graph):
        h1, _ = add_receipt_node(graph, "r1", domain_cat="safe")
        h2, _ = add_receipt_node(graph, "r2", domain_cat="threat")
        edges = graph.auto_connect(h2)
        types = [e.edge_type for e in edges]
        assert "same_domain" not in types


# ---------------------------------------------------------------------------
# 4. Reinforcement
# ---------------------------------------------------------------------------

class TestReinforcement:

    def test_reinforce_increases_weight(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        edge = graph.connect(h1, h2, "test")
        initial = edge.weight
        edge.reinforce()
        assert edge.weight > initial
        assert edge.reinforcements == 1

    def test_reinforce_path(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        h3, _ = add_receipt_node(graph, "r3")
        graph.connect(h1, h2, "chain")
        graph.connect(h2, h3, "chain")
        count = graph.reinforce_path([h1, h2, h3])
        assert count == 2  # two edges reinforced

    def test_weight_caps_at_one(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        edge = graph.connect(h1, h2, "test", initial_weight=0.95)
        edge.reinforce(boost=0.2)
        assert edge.weight == 1.0


# ---------------------------------------------------------------------------
# 5-7. Decay and cold edges
# ---------------------------------------------------------------------------

class TestDecay:

    def test_decay_reduces_weight(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        edge = graph.connect(h1, h2, "test")
        initial = edge.weight
        graph.decay_all(current_block=5)
        assert edge.weight < initial

    def test_cold_edge_not_retrieved(self, graph):
        h1, _ = add_receipt_node(graph, "r1", domain_cat="threat")
        h2, _ = add_receipt_node(graph, "r2", domain_cat="threat")
        edge = graph.connect(h1, h2, "same_domain")

        # Force cold
        edge.weight = 0.05
        active = graph.retrieve_active(domain="threat")
        assert len(active) == 0

    def test_cold_edge_still_exists(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        edge = graph.connect(h1, h2, "test")
        edge.weight = 0.01  # cold
        assert edge.is_cold
        assert graph.edge_count == 1  # still in graph
        assert graph.cold_edge_count == 1
        assert graph.active_edge_count == 0

    def test_mark_cold_forces_all_edges(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        h3, _ = add_receipt_node(graph, "r3")
        graph.connect(h1, h2, "test")
        graph.connect(h1, h3, "test")
        marked = graph.mark_cold(h1)
        assert marked == 2
        assert graph.active_edge_count == 0


# ---------------------------------------------------------------------------
# 8. Contradiction
# ---------------------------------------------------------------------------

class TestContradiction:

    def test_contradiction_weakens_edge(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        edge = graph.connect(h1, h2, "test")
        initial = edge.weight
        edge.contradict()
        assert edge.weight < initial
        assert edge.contradictions == 1

    def test_weaken_edges_by_hash(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        h3, _ = add_receipt_node(graph, "r3")
        graph.connect(h1, h2, "a")
        graph.connect(h1, h3, "b")
        weakened = graph.weaken_edges(h1)
        assert weakened == 2

    def test_weight_floors_at_zero(self, graph):
        h1, _ = add_receipt_node(graph, "r1")
        h2, _ = add_receipt_node(graph, "r2")
        edge = graph.connect(h1, h2, "test", initial_weight=0.1)
        edge.contradict(penalty=0.5)
        assert edge.weight == 0.0


# ---------------------------------------------------------------------------
# 9-11. Prediction and error correction
# ---------------------------------------------------------------------------

class TestPrediction:

    def test_predict_from_matching_nodes(self, graph):
        # Build history: multiple benign receipts in same domain
        for i in range(3):
            h, _ = add_receipt_node(graph, f"benign_{i}",
                                    direction="benign", domain_cat="safe")
            graph.auto_connect(h)

        pred = graph.predict(tags=["benign"], domain="safe")
        assert pred["predicted_outcome"] == "benign"
        assert pred["confidence"] > 0
        assert pred["supporting_receipts"] > 0

    def test_predict_unknown_with_no_data(self, graph):
        pred = graph.predict(tags=["never_seen"], domain="alien")
        assert pred["predicted_outcome"] == "unknown"
        assert pred["confidence"] == 0.0

    def test_score_correct_reinforces(self, graph):
        h1, _ = add_receipt_node(graph, "r1", direction="escalate",
                                 domain_cat="threat")
        h2, _ = add_receipt_node(graph, "r2", direction="escalate",
                                 domain_cat="threat")
        graph.auto_connect(h2)

        # Get initial edge weights
        initial_weights = [e.weight for e in graph.edges]

        # Predict, then confirm correct
        graph.predict(tags=["escalate"], domain="threat")
        result = graph.score_prediction("escalate")

        assert result["scored"]
        assert result["correct"]
        assert result["action"] == "reinforced"

        # Edges should be stronger
        for e, init_w in zip(graph.edges, initial_weights):
            if e.reinforcements > 0:
                assert e.weight >= init_w

    def test_score_wrong_weakens(self, graph):
        h1, _ = add_receipt_node(graph, "r1", direction="benign",
                                 domain_cat="safe")
        h2, _ = add_receipt_node(graph, "r2", direction="benign",
                                 domain_cat="safe")
        graph.auto_connect(h2)

        graph.predict(tags=["benign"], domain="safe")
        result = graph.score_prediction("escalate")  # WRONG

        assert result["scored"]
        assert not result["correct"]
        assert result["action"] == "weakened"

    def test_score_without_prediction(self, graph):
        result = graph.score_prediction("benign")
        assert not result["scored"]


# ---------------------------------------------------------------------------
# 12. Full error-correction loop
# ---------------------------------------------------------------------------

class TestErrorCorrectionLoop:

    def test_full_loop(self, graph):
        """The complete cycle: learn → predict → test → correct → adapt."""
        # Phase 1: Build initial memory — 3 escalation receipts
        escalate_hashes = []
        for i in range(3):
            h, _ = add_receipt_node(graph, f"esc_{i}",
                                    direction="escalate", domain_cat="threat")
            graph.auto_connect(h)
            escalate_hashes.append(h)

        # Phase 2: Graph predicts escalation for new threat-domain query
        pred1 = graph.predict(tags=["escalate"], domain="threat")
        assert pred1["predicted_outcome"] == "escalate"

        # Phase 3: Prediction confirmed — reinforce
        score1 = graph.score_prediction("escalate")
        assert score1["correct"]

        # Phase 4: Now add a benign receipt in same domain
        h_benign, _ = add_receipt_node(graph, "surprise_benign",
                                       direction="benign",
                                       domain_cat="threat")
        graph.auto_connect(h_benign)

        # Phase 5: Graph still predicts escalate (history is strong)
        pred2 = graph.predict(tags=["ev:threat"], domain="threat")
        # Graph has 3 escalate + 1 benign, should still lean escalate
        assert pred2["predicted_outcome"] == "escalate"

        # Phase 6: But actual is benign — graph pays
        score2 = graph.score_prediction("benign")
        assert not score2["correct"]
        assert score2["action"] == "weakened"

        # Phase 7: After enough corrections, prediction should shift
        # Add more benign receipts and keep contradicting
        for i in range(4):
            h, _ = add_receipt_node(graph, f"benign_wave_{i}",
                                    direction="benign",
                                    domain_cat="threat")
            graph.auto_connect(h)
            graph.predict(tags=["ev:threat"], domain="threat")
            graph.score_prediction("benign")

        # Phase 8: Graph should have adapted
        final_pred = graph.predict(tags=["ev:threat"], domain="threat")
        # With 5 benign vs 3 escalate (weakened), benign should dominate
        assert final_pred["predicted_outcome"] == "benign"

    def test_structure_emerges_from_reinforcement(self, graph):
        """Stable clusters survive repeated reinforcement."""
        # Build a cluster of related benign receipts
        hashes = []
        for i in range(5):
            h, _ = add_receipt_node(graph, f"stable_{i}",
                                    direction="benign", domain_cat="safe")
            graph.auto_connect(h)
            hashes.append(h)

        # Reinforce the cluster multiple times
        for _ in range(5):
            graph.reinforce_path(hashes)

        # Decay the graph
        graph.decay_all(current_block=10)

        # Strong cluster survives decay
        active = graph.retrieve_active(domain="safe")
        assert len(active) > 0
        # At least some edges should be strong
        max_weight = max(a["weight"] for a in active)
        assert max_weight > 0.5


# ---------------------------------------------------------------------------
# 13. HUD
# ---------------------------------------------------------------------------

class TestHUD:

    def test_hud_empty_graph(self, graph):
        hud = graph.export_memory_hud()
        assert hud["memory_status"] == "no_relevant_memory"
        assert hud["active_patterns"] == 0

    def test_hud_with_active_memory(self, graph):
        for i in range(3):
            h, _ = add_receipt_node(graph, f"r{i}", domain_cat="threat")
            graph.auto_connect(h)

        hud = graph.export_memory_hud(domain="threat")
        assert hud["memory_status"] == "active"
        assert hud["active_patterns"] > 0
        assert hud["dominant_outcome"] == "benign"
        assert hud["memory_strength"] in ("weak", "moderate", "strong")

    def test_hud_no_hidden_state(self, graph):
        """HUD must not expose raw weights, decay rates, or internals."""
        for i in range(3):
            h, _ = add_receipt_node(graph, f"r{i}")
            graph.auto_connect(h)

        hud = graph.export_memory_hud()
        hud_str = str(hud)
        assert "weight" not in hud_str.lower().replace("memory_strength", "")
        assert "decay" not in hud_str
        assert "reinforcement" not in hud_str
        assert "receipt_hash" not in hud_str
        assert "edge" not in hud_str


# ---------------------------------------------------------------------------
# 14. Persistence
# ---------------------------------------------------------------------------

class TestPersistence:

    def test_save_load_roundtrip(self, graph_path):
        g1 = ReceiptGraph(graph_path)
        h1, _ = add_receipt_node(g1, "r1", direction="escalate")
        h2, _ = add_receipt_node(g1, "r2", direction="escalate")
        g1.auto_connect(h2)
        # Use reinforce_path (graph-level API that triggers save)
        count = g1.reinforce_path([h1, h2])
        assert count > 0

        # Reload
        g2 = ReceiptGraph(graph_path)
        assert g2.node_count == 2
        assert g2.edge_count == g1.edge_count
        # At least one edge should have been reinforced
        reinforced = [e for e in g2.edges if e.reinforcements > 0]
        assert len(reinforced) > 0


# ---------------------------------------------------------------------------
# 15. Differential decay rates
# ---------------------------------------------------------------------------

class TestDifferentialDecay:

    def test_formal_decays_slower_than_temporary(self, graph):
        """Formal receipts (benchmarks) should decay slower."""
        # Create a "formal" receipt (contains "bench" in gate_version)
        formal_receipt = {
            "gate_version": "benchmark_test",
            "final_action": "COMMIT",
            "final_direction": "benign",
            "evidence_vector": [("t1", "safe")],
        }
        fh = canonical_hash(formal_receipt)
        graph.add_node(fh, formal_receipt, block_number=0)

        # Create a "temporary" receipt (CONTINUE action)
        temp_receipt = {
            "gate_version": "v7_shadow_monitor",
            "final_action": "CONTINUE",
            "final_direction": "unknown",
            "evidence_vector": [("t1", "ambiguous")],
        }
        th = canonical_hash(temp_receipt)
        graph.add_node(th, temp_receipt, block_number=0)

        # Verify classification
        assert graph.nodes[fh].receipt_class == "formal"
        assert graph.nodes[th].receipt_class == "temporary"

        # Verify rates
        assert DECAY_RATES["formal"] < DECAY_RATES["temporary"]
