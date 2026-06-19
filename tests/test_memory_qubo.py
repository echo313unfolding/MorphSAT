"""
Tests for MemoryQUBO — QUBO memory selector for MorphSAT.

Covers:
    1. Candidate extraction from ReceiptGraph
    2. QUBO matrix construction (linear + quadratic terms)
    3. Brute-force solver correctness
    4. Greedy baseline solver
    5. SA solver convergence
    6. Relevance scoring (domain + tag matching)
    7. Redundancy penalty (same domain + outcome penalized)
    8. Contradiction penalty (benign vs escalate penalized)
    9. Coverage reward (diverse tags rewarded)
    10. Staleness penalty (old blocks penalized)
    11. Unsafe memory penalty (high contradiction ratio)
    12. Max-K constraint enforcement
    13. HUD integration (select_for_hud)
    14. Empty graph edge case
    15. Single candidate edge case
"""

import pytest
import time

from morphsat.memory_qubo import MemoryQUBO, MemoryCandidate, QUBOResult
from morphsat.receipt_graph import ReceiptGraph, ReceiptNode, ReceiptEdge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_candidate(
    index: int,
    receipt_hash: str = "",
    domain: str = "network",
    outcome: str = "benign",
    action: str = "COMMIT",
    tags: list = None,
    edge_weight_sum: float = 1.0,
    edge_count: int = 2,
    reinforcements: int = 3,
    contradictions: int = 0,
    block_number: int = 0,
    token_cost: int = 1,
) -> MemoryCandidate:
    """Create a candidate. NOTE: index must match position in the list
    passed to build_matrix (Q[c.index][c.index] is used)."""
    return MemoryCandidate(
        index=index,
        receipt_hash=receipt_hash or f"hash_{index}",
        domain=domain,
        outcome=outcome,
        action=action,
        receipt_class="decision",
        tags=tags or ["port", "process"],
        edge_weight_sum=edge_weight_sum,
        edge_count=edge_count,
        reinforcements=reinforcements,
        contradictions=contradictions,
        block_number=block_number,
        token_cost=token_cost,
    )


def make_graph_with_nodes(n: int = 5) -> ReceiptGraph:
    """Build a ReceiptGraph with n nodes and some edges."""
    import os
    path = f"/tmp/test_mqubo_{os.getpid()}_{time.time_ns()}.json"
    g = ReceiptGraph(path)

    domains = ["network", "endpoint", "cloud", "network", "endpoint"]
    outcomes = ["benign", "escalate", "benign", "suspicious", "escalate"]
    tags_list = [
        ["port", "scan"],
        ["process", "rootkit"],
        ["iam", "api"],
        ["port", "brute"],
        ["file", "malware"],
    ]

    for i in range(n):
        h = f"node_{i}"
        g.nodes[h] = ReceiptNode(
            receipt_hash=h,
            domain=domains[i % len(domains)],
            outcome=outcomes[i % len(outcomes)],
            action="COMMIT",
            receipt_class="decision",
            tags=tags_list[i % len(tags_list)],
            block_number=i * 10,
            timestamp="2026-06-19T00:00:00",
        )

    # Add some edges
    if n >= 2:
        g.edges.append(ReceiptEdge(
            from_hash="node_0", to_hash="node_1",
            edge_type="outcome_match", weight=0.8,
            reinforcements=3, contradictions=0,
        ))
    if n >= 3:
        g.edges.append(ReceiptEdge(
            from_hash="node_1", to_hash="node_2",
            edge_type="domain_match", weight=0.5,
            reinforcements=1, contradictions=2,
        ))
    if n >= 4:
        g.edges.append(ReceiptEdge(
            from_hash="node_2", to_hash="node_3",
            edge_type="tag_overlap", weight=0.3,
            reinforcements=0, contradictions=0,
        ))

    return g


@pytest.fixture
def qubo():
    return MemoryQUBO(max_k=3)


@pytest.fixture
def graph():
    return make_graph_with_nodes(5)


# ---------------------------------------------------------------------------
# 1. Candidate extraction
# ---------------------------------------------------------------------------

class TestCandidateExtraction:
    def test_extracts_all_nodes(self, qubo, graph):
        candidates = qubo.extract_candidates(graph)
        assert len(candidates) == 5

    def test_candidate_has_edge_stats(self, qubo, graph):
        candidates = qubo.extract_candidates(graph)
        # node_0 has one edge (to node_1)
        c0 = [c for c in candidates if c.receipt_hash == "node_0"][0]
        assert c0.edge_count >= 1
        assert c0.edge_weight_sum > 0

    def test_domain_filter(self, qubo, graph):
        candidates = qubo.extract_candidates(graph, domain="cloud")
        # Only node_2 is domain "cloud"
        assert len(candidates) >= 1
        assert all(c.domain == "cloud" or len(set(c.tags) & set([])) > 0
                   for c in candidates)

    def test_tag_filter(self, qubo, graph):
        candidates = qubo.extract_candidates(
            graph, domain="nonexistent", tags=["port"])
        # Should include nodes with "port" tag even if domain doesn't match
        assert len(candidates) >= 1


# ---------------------------------------------------------------------------
# 2. Matrix construction
# ---------------------------------------------------------------------------

class TestMatrixConstruction:
    def test_matrix_is_nxn(self, qubo):
        candidates = [make_candidate(i) for i in range(4)]
        Q = qubo.build_matrix(candidates)
        assert len(Q) == 4
        for row in Q:
            assert len(row) == 4

    def test_empty_candidates(self, qubo):
        Q = qubo.build_matrix([])
        assert Q == []

    def test_diagonal_has_linear_terms(self, qubo):
        candidates = [make_candidate(0, outcome="escalate", edge_weight_sum=2.0)]
        Q = qubo.build_matrix(candidates, current_block=0)
        assert Q[0][0] != 0.0, "Diagonal should have non-zero linear terms"

    def test_offdiagonal_symmetric(self, qubo):
        candidates = [
            make_candidate(0, domain="network", outcome="benign"),
            make_candidate(1, domain="network", outcome="escalate"),
        ]
        Q = qubo.build_matrix(candidates)
        assert abs(Q[0][1] - Q[1][0]) < 1e-10


# ---------------------------------------------------------------------------
# 3-5. Solvers
# ---------------------------------------------------------------------------

class TestSolvers:
    def test_brute_force_respects_max_k(self, qubo):
        candidates = [make_candidate(i) for i in range(5)]
        Q = qubo.build_matrix(candidates)
        x, obj = qubo.brute_force(Q, max_k=3)
        assert sum(x) <= 3

    def test_brute_force_optimal(self, qubo):
        """Brute force should find the global minimum."""
        candidates = [
            make_candidate(0, edge_weight_sum=5.0),  # strong
            make_candidate(1, edge_weight_sum=0.1),  # weak
            make_candidate(2, edge_weight_sum=3.0),  # medium
        ]
        Q = qubo.build_matrix(candidates, query_domain="network",
                              current_block=0)
        x_bf, obj_bf = qubo.brute_force(Q, max_k=2)

        # Verify: no other feasible solution has lower objective
        from itertools import combinations
        n = len(candidates)
        for r in range(1, min(3, n) + 1):
            for combo in combinations(range(n), r):
                x_test = [0] * n
                for i in combo:
                    x_test[i] = 1
                obj_test = qubo._evaluate(Q, x_test)
                assert obj_bf <= obj_test + 1e-10

    def test_greedy_respects_max_k(self, qubo):
        candidates = [make_candidate(i) for i in range(6)]
        Q = qubo.build_matrix(candidates)
        x, obj = qubo.greedy_baseline(Q, max_k=2)
        assert sum(x) <= 2

    def test_sa_respects_max_k(self, qubo):
        candidates = [make_candidate(i) for i in range(8)]
        Q = qubo.build_matrix(candidates)
        x, obj = qubo.simulated_annealing(Q, max_k=3)
        assert sum(x) <= 3

    def test_sa_matches_brute_force_on_small(self, qubo):
        """SA should find the same optimum as brute force on small problems."""
        candidates = [
            make_candidate(0, edge_weight_sum=3.0, domain="network"),
            make_candidate(1, edge_weight_sum=0.5, domain="cloud"),
            make_candidate(2, edge_weight_sum=2.0, domain="network"),
        ]
        Q = qubo.build_matrix(candidates, query_domain="network",
                              current_block=0)
        _, obj_bf = qubo.brute_force(Q, max_k=2)
        _, obj_sa = qubo.simulated_annealing(Q, max_k=2, n_steps=2000)
        assert abs(obj_bf - obj_sa) < 1e-6

    def test_brute_force_rejects_large_n(self, qubo):
        candidates = [make_candidate(i) for i in range(25)]
        Q = qubo.build_matrix(candidates)
        with pytest.raises(ValueError, match="n<=20"):
            qubo.brute_force(Q, max_k=3)


# ---------------------------------------------------------------------------
# 6. Relevance scoring
# ---------------------------------------------------------------------------

class TestRelevance:
    def test_domain_match_improves_score(self):
        qubo = MemoryQUBO(max_k=1)
        c_match = make_candidate(0, domain="network")
        c_nomatch = make_candidate(0, domain="cloud")  # index=0 for single-element list

        Q_match = qubo.build_matrix([c_match], query_domain="network")
        Q_nomatch = qubo.build_matrix([c_nomatch], query_domain="network")

        # Domain match should give lower (better) diagonal score
        assert Q_match[0][0] < Q_nomatch[0][0]

    def test_tag_overlap_improves_score(self):
        qubo = MemoryQUBO(max_k=1)
        c_tags = make_candidate(0, tags=["port", "scan", "brute"])
        c_notags = make_candidate(0, tags=["unrelated"])  # index=0 for single-element list

        Q_tags = qubo.build_matrix([c_tags],
                                   query_tags=["port", "scan"])
        Q_notags = qubo.build_matrix([c_notags],
                                     query_tags=["port", "scan"])

        assert Q_tags[0][0] < Q_notags[0][0]


# ---------------------------------------------------------------------------
# 7. Redundancy penalty
# ---------------------------------------------------------------------------

class TestRedundancy:
    def test_same_domain_outcome_penalized(self):
        qubo = MemoryQUBO(max_k=2)
        candidates = [
            make_candidate(0, domain="network", outcome="benign"),
            make_candidate(1, domain="network", outcome="benign"),
        ]
        Q = qubo.build_matrix(candidates)
        # Off-diagonal should include redundancy penalty (positive)
        assert Q[0][1] > 0, "Same domain+outcome should add redundancy penalty"

    def test_different_domain_no_redundancy(self):
        qubo = MemoryQUBO(max_k=2)
        candidates = [
            make_candidate(0, domain="network", outcome="benign"),
            make_candidate(1, domain="cloud", outcome="escalate"),
        ]
        Q = qubo.build_matrix(candidates)
        # No redundancy term (may still have coverage reward, which is negative)
        # Just check it's not as penalized as redundant pair
        Q2 = qubo.build_matrix([
            make_candidate(0, domain="network", outcome="benign"),
            make_candidate(1, domain="network", outcome="benign"),
        ])
        assert Q[0][1] < Q2[0][1]


# ---------------------------------------------------------------------------
# 8. Contradiction penalty
# ---------------------------------------------------------------------------

class TestContradiction:
    def test_benign_vs_escalate_penalized(self):
        qubo = MemoryQUBO(max_k=2)
        candidates = [
            make_candidate(0, outcome="benign"),
            make_candidate(1, outcome="escalate"),
        ]
        Q = qubo.build_matrix(candidates)
        # Contradiction penalty should be positive in off-diagonal
        assert Q[0][1] > 0

    def test_same_outcome_no_contradiction(self):
        qubo = MemoryQUBO(max_k=2)
        # Different domain to isolate contradiction from redundancy
        candidates = [
            make_candidate(0, domain="network", outcome="escalate"),
            make_candidate(1, domain="cloud", outcome="escalate"),
        ]
        Q = qubo.build_matrix(candidates)
        # No contradiction between same outcomes (may have negative coverage)
        candidates2 = [
            make_candidate(0, domain="network", outcome="benign"),
            make_candidate(1, domain="cloud", outcome="escalate"),
        ]
        Q2 = qubo.build_matrix(candidates2)
        # Contradicting pair should have higher off-diagonal than same-outcome
        assert Q2[0][1] > Q[0][1]


# ---------------------------------------------------------------------------
# 9. Coverage reward
# ---------------------------------------------------------------------------

class TestCoverage:
    def test_diverse_tags_rewarded(self):
        qubo = MemoryQUBO(max_k=2)
        # Different tags = coverage
        candidates_diverse = [
            make_candidate(0, domain="network", outcome="suspicious",
                          tags=["port", "scan"]),
            make_candidate(1, domain="cloud", outcome="suspicious",
                          tags=["iam", "api"]),
        ]
        # Same tags = no coverage
        candidates_same = [
            make_candidate(0, domain="network", outcome="suspicious",
                          tags=["port", "scan"]),
            make_candidate(1, domain="cloud", outcome="suspicious",
                          tags=["port", "scan"]),
        ]
        Q_div = qubo.build_matrix(candidates_diverse)
        Q_same = qubo.build_matrix(candidates_same)
        # Diverse tags should have lower (more negative) off-diagonal from coverage reward
        assert Q_div[0][1] < Q_same[0][1]


# ---------------------------------------------------------------------------
# 10. Staleness penalty
# ---------------------------------------------------------------------------

class TestStaleness:
    def test_old_block_penalized(self):
        qubo = MemoryQUBO(max_k=1)
        c_recent = make_candidate(0, block_number=95)
        c_old = make_candidate(0, block_number=5)  # index=0 for single-element list

        Q_recent = qubo.build_matrix([c_recent], current_block=100)
        Q_old = qubo.build_matrix([c_old], current_block=100)

        # Old block should have higher (worse) diagonal from staleness
        assert Q_old[0][0] > Q_recent[0][0]


# ---------------------------------------------------------------------------
# 11. Unsafe memory penalty
# ---------------------------------------------------------------------------

class TestUnsafe:
    def test_high_contradiction_ratio_penalized(self):
        qubo = MemoryQUBO(max_k=1)
        c_safe = make_candidate(0, reinforcements=10, contradictions=0)
        c_unsafe = make_candidate(0, reinforcements=1, contradictions=9)  # index=0

        Q_safe = qubo.build_matrix([c_safe])
        Q_unsafe = qubo.build_matrix([c_unsafe])

        # High contradiction ratio should give worse score
        assert Q_unsafe[0][0] > Q_safe[0][0]


# ---------------------------------------------------------------------------
# 12. Max-K constraint
# ---------------------------------------------------------------------------

class TestConstraint:
    def test_solve_auto_selects_brute_force_small(self):
        qubo = MemoryQUBO(max_k=2)
        candidates = [make_candidate(i) for i in range(5)]
        result = qubo.solve(candidates, solver="auto")
        assert result.solver == "brute_force"
        assert len(result.selected_indices) <= 2

    def test_solve_auto_selects_sa_large(self):
        qubo = MemoryQUBO(max_k=3)
        candidates = [make_candidate(i) for i in range(25)]
        result = qubo.solve(candidates, solver="auto")
        assert result.solver == "sa"
        assert len(result.selected_indices) <= 3


# ---------------------------------------------------------------------------
# 13. HUD integration
# ---------------------------------------------------------------------------

class TestHUD:
    def test_select_for_hud_returns_tuple(self, qubo, graph):
        result, hud = qubo.select_for_hud(graph, current_block=50)
        assert isinstance(result, QUBOResult)
        assert isinstance(hud, dict)
        assert "memory_status" in hud
        assert "selector" in hud
        assert hud["selector"] == "qubo"

    def test_hud_active_when_selected(self, qubo, graph):
        result, hud = qubo.select_for_hud(graph, current_block=50)
        if result.selected_indices:
            assert hud["memory_status"] == "active"
            assert hud["active_patterns"] > 0
            assert hud["dominant_outcome"] in ("benign", "escalate",
                                                "suspicious", "unknown")
            assert hud["memory_strength"] in ("none", "weak",
                                               "moderate", "strong")

    def test_hud_strength_from_edge_weights(self):
        """Strong edge weights should produce strong memory_strength."""
        import os
        path = f"/tmp/test_hud_strength_{os.getpid()}.json"
        g = ReceiptGraph(path)

        g.nodes["strong"] = ReceiptNode(
            receipt_hash="strong", domain="network",
            outcome="escalate", action="COMMIT",
            receipt_class="decision", tags=["port"],
            block_number=0,
            timestamp="2026-06-19T00:00:00",
        )
        g.edges.append(ReceiptEdge(
            from_hash="strong", to_hash="strong",
            edge_type="self", weight=0.9,
            reinforcements=10, contradictions=0,
        ))

        qubo = MemoryQUBO(max_k=1)
        result, hud = qubo.select_for_hud(g, current_block=0)
        if result.selected_indices:
            assert hud["memory_strength"] == "strong"


# ---------------------------------------------------------------------------
# 14. Empty graph
# ---------------------------------------------------------------------------

class TestEmptyGraph:
    def test_empty_graph_returns_no_memory(self, qubo):
        import os
        path = f"/tmp/test_empty_graph_{os.getpid()}.json"
        g = ReceiptGraph(path)
        result, hud = qubo.select_for_hud(g)
        assert hud["memory_status"] == "no_relevant_memory"
        assert result.selected_indices == []
        assert result.n_candidates == 0


# ---------------------------------------------------------------------------
# 15. Single candidate
# ---------------------------------------------------------------------------

class TestSingleCandidate:
    def test_single_candidate_always_selected(self, qubo):
        candidates = [make_candidate(0, edge_weight_sum=2.0)]
        result = qubo.solve(candidates, solver="brute_force")
        assert len(result.selected_indices) == 1
        assert result.selected_indices[0] == 0


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_result_has_terms(self, qubo):
        candidates = [make_candidate(i) for i in range(3)]
        result = qubo.solve(candidates)
        assert "linear_total" in result.terms
        assert "n_selected" in result.terms

    def test_result_has_wall_time(self, qubo):
        candidates = [make_candidate(i) for i in range(3)]
        result = qubo.solve(candidates)
        assert result.wall_time_ms >= 0

    def test_result_tracks_rejected(self, qubo):
        candidates = [make_candidate(i) for i in range(5)]
        result = qubo.solve(candidates)
        assert len(result.selected_indices) + len(result.rejected_indices) == 5

    def test_solve_empty(self, qubo):
        result = qubo.solve([])
        assert result.solver == "empty"
        assert result.selected_indices == []
        assert result.objective_value == 0.0
