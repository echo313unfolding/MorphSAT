"""
MorphSAT QUBO Memory Selector — Constrained Attention
======================================================

Given candidate receipt nodes from ReceiptGraph, choose up to K
memories for HUD using constrained binary optimization.

QUBO is the selector/allocator/router.
Not the memory itself. Not the governor. Not the receipt chain.

    Receipt graph produces candidates.
    QUBO chooses the best active subset.
    MorphSAT governs whether action is allowed.
    Receipt chain proves what was chosen.

Formulation:
    minimize x^T Q x

    x_i = 1 if candidate memory i is selected for HUD
    x_i = 0 otherwise

    Linear terms (diagonal):
        - relevance reward
        - edge strength reward
        - recency reward
        + staleness penalty
        + token cost penalty
        + unsafe memory penalty

    Quadratic terms (off-diagonal):
        + redundancy penalty (i,j share outcome + domain)
        + contradiction penalty (i says safe, j says threat)
        - coverage reward (i,j cover different evidence types)

    Constraints (penalty method):
        sum(x_i) <= K        (max selected)

Solvers:
    brute_force_qubo()       — exact, n <= 20
    greedy_baseline()        — sort by linear score, pick top K
    simulated_annealing()    — stochastic, larger sets
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple

from morphsat.receipt_graph import ReceiptGraph, ReceiptNode, ReceiptEdge, COLD_THRESHOLD


# ---------------------------------------------------------------------------
# Candidate — one memory node eligible for selection
# ---------------------------------------------------------------------------

@dataclass
class MemoryCandidate:
    """A candidate memory for QUBO selection."""
    index: int                  # position in candidate list
    receipt_hash: str
    domain: str
    outcome: str                # benign/suspicious/escalate/unknown
    action: str                 # COMMIT/ABSTAIN/CONTINUE
    receipt_class: str          # formal/decision/evidence/temporary
    tags: List[str]
    edge_weight_sum: float      # sum of active edge weights touching this node
    edge_count: int             # number of active edges
    reinforcements: int         # total reinforcements on connected edges
    contradictions: int         # total contradictions on connected edges
    block_number: int           # when this receipt was created
    token_cost: int = 1         # estimated token cost (default 1 unit)


@dataclass
class QUBOResult:
    """Result of QUBO memory selection."""
    selected_indices: List[int]
    selected_hashes: List[str]
    objective_value: float
    solver: str
    n_candidates: int
    max_k: int
    terms: Dict[str, float]     # breakdown of objective terms
    rejected_indices: List[int]
    rejected_hashes: List[str]
    wall_time_ms: float


# ---------------------------------------------------------------------------
# QUBO Matrix Builder
# ---------------------------------------------------------------------------

class MemoryQUBO:
    """Build and solve QUBO for memory selection.

    Usage:
        qubo = MemoryQUBO(max_k=5)
        candidates = qubo.extract_candidates(graph, tags, domain, current_block)
        result = qubo.solve(candidates, solver="brute_force")
    """

    def __init__(
        self,
        max_k: int = 5,
        # Linear weights (negative = reward, positive = penalty)
        w_relevance: float = -2.0,
        w_strength: float = -1.5,
        w_recency: float = -1.0,
        w_staleness: float = 1.0,
        w_token_cost: float = 0.5,
        w_unsafe: float = 2.0,
        # Quadratic weights
        w_redundancy: float = 1.5,
        w_contradiction: float = 1.0,
        w_coverage: float = -0.8,
        # Constraint penalty
        w_constraint: float = 10.0,
    ):
        self.max_k = max_k
        self.w_relevance = w_relevance
        self.w_strength = w_strength
        self.w_recency = w_recency
        self.w_staleness = w_staleness
        self.w_token_cost = w_token_cost
        self.w_unsafe = w_unsafe
        self.w_redundancy = w_redundancy
        self.w_contradiction = w_contradiction
        self.w_coverage = w_coverage
        self.w_constraint = w_constraint

    # --- Candidate extraction -----------------------------------------------

    def extract_candidates(
        self,
        graph: ReceiptGraph,
        tags: Optional[List[str]] = None,
        domain: Optional[str] = None,
        current_block: int = 0,
    ) -> List[MemoryCandidate]:
        """Extract candidate memories from the graph."""
        candidates = []

        for idx, (h, node) in enumerate(graph.nodes.items()):
            # Filter by domain/tags if specified
            if domain and node.domain != domain:
                tag_overlap = len(set(tags or []) & set(node.tags)) if tags else 0
                if tag_overlap == 0:
                    continue

            # Compute edge statistics
            edge_weight_sum = 0.0
            edge_count = 0
            reinforcements = 0
            contradictions = 0
            for edge in graph.edges:
                if edge.is_cold:
                    continue
                if edge.from_hash == h or edge.to_hash == h:
                    edge_weight_sum += edge.weight
                    edge_count += 1
                    reinforcements += edge.reinforcements
                    contradictions += edge.contradictions

            candidates.append(MemoryCandidate(
                index=len(candidates),
                receipt_hash=h,
                domain=node.domain,
                outcome=node.outcome,
                action=node.action,
                receipt_class=node.receipt_class,
                tags=list(node.tags),
                edge_weight_sum=edge_weight_sum,
                edge_count=edge_count,
                reinforcements=reinforcements,
                contradictions=contradictions,
                block_number=node.block_number,
            ))

        return candidates

    # --- QUBO matrix construction -------------------------------------------

    def build_matrix(
        self,
        candidates: List[MemoryCandidate],
        query_tags: Optional[List[str]] = None,
        query_domain: Optional[str] = None,
        current_block: int = 0,
    ) -> List[List[float]]:
        """Build the QUBO matrix Q where objective = x^T Q x.

        Returns n×n matrix where n = len(candidates).
        Diagonal Q[i][i] = linear terms for candidate i.
        Off-diagonal Q[i][j] = pairwise terms for (i, j).
        """
        n = len(candidates)
        if n == 0:
            return []

        Q = [[0.0] * n for _ in range(n)]

        # --- Linear terms (diagonal) ---
        for c in candidates:
            i = c.index
            score = 0.0

            # Relevance: tag/domain overlap with query
            relevance = 0.0
            if query_domain and c.domain == query_domain:
                relevance += 0.5
            if query_tags:
                tag_overlap = len(set(query_tags) & set(c.tags))
                relevance += tag_overlap * 0.25
            relevance = min(1.0, relevance)
            score += self.w_relevance * relevance

            # Edge strength (normalized)
            max_possible = max(c.edge_count, 1)
            strength = min(1.0, c.edge_weight_sum / max(max_possible, 1))
            score += self.w_strength * strength

            # Recency (exponential decay with block distance)
            block_age = max(0, current_block - c.block_number)
            recency = math.exp(-0.1 * block_age)
            score += self.w_recency * recency

            # Staleness penalty (complement of recency)
            staleness = 1.0 - recency
            score += self.w_staleness * staleness

            # Token cost
            score += self.w_token_cost * c.token_cost

            # Unsafe: high contradiction count relative to reinforcements
            if c.reinforcements + c.contradictions > 0:
                unsafe_ratio = c.contradictions / (c.reinforcements + c.contradictions)
            else:
                unsafe_ratio = 0.0
            score += self.w_unsafe * unsafe_ratio

            Q[i][i] = score

        # --- Quadratic terms (off-diagonal, symmetric) ---
        for i in range(n):
            ci = candidates[i]
            for j in range(i + 1, n):
                cj = candidates[j]
                pairwise = 0.0

                # Redundancy: same domain AND same outcome
                if ci.domain == cj.domain and ci.outcome == cj.outcome:
                    pairwise += self.w_redundancy

                # Contradiction: one says safe-ish, other says threat-ish
                safe_outcomes = {"benign"}
                threat_outcomes = {"escalate"}
                if ((ci.outcome in safe_outcomes and cj.outcome in threat_outcomes) or
                    (ci.outcome in threat_outcomes and cj.outcome in safe_outcomes)):
                    pairwise += self.w_contradiction

                # Coverage: different tags = more evidence coverage
                ci_tags = set(ci.tags)
                cj_tags = set(cj.tags)
                if ci_tags and cj_tags:
                    unique_combined = len(ci_tags | cj_tags)
                    shared = len(ci_tags & cj_tags)
                    coverage = (unique_combined - shared) / max(unique_combined, 1)
                    pairwise += self.w_coverage * coverage

                Q[i][j] = pairwise
                Q[j][i] = pairwise

        # --- Constraint: sum(x_i) <= max_k ---
        # Penalty: w_constraint * (sum(x_i) - K)^2 when sum > K
        # Expanded: w_constraint * (sum_i x_i^2 + 2 * sum_{i<j} x_i*x_j - 2K*sum_i x_i + K^2)
        # Since x_i is binary, x_i^2 = x_i
        # Add to diagonal: w_constraint * (1 - 2K)  ... wait, this penalizes ALL solutions
        # Better: use slack variables or just enforce in solver
        # For simplicity: enforce K constraint in solver, not in matrix

        return Q

    # --- Solvers ------------------------------------------------------------

    def _evaluate(self, Q: List[List[float]], x: List[int]) -> float:
        """Evaluate x^T Q x."""
        n = len(x)
        total = 0.0
        for i in range(n):
            if x[i] == 0:
                continue
            for j in range(n):
                if x[j] == 0:
                    continue
                total += Q[i][j]
        return total

    def brute_force(
        self,
        Q: List[List[float]],
        max_k: int,
    ) -> Tuple[List[int], float]:
        """Exact solver: enumerate all feasible subsets.

        Only for n <= 20 (2^20 = ~1M evaluations).
        """
        n = len(Q)
        if n == 0:
            return [], 0.0
        if n > 20:
            raise ValueError(f"brute_force limited to n<=20, got n={n}")

        best_x = [0] * n
        best_obj = float("inf")

        for mask in range(1 << n):
            x = [(mask >> i) & 1 for i in range(n)]
            if sum(x) > max_k:
                continue
            obj = self._evaluate(Q, x)
            if obj < best_obj:
                best_obj = obj
                best_x = list(x)

        return best_x, best_obj

    def greedy_baseline(
        self,
        Q: List[List[float]],
        max_k: int,
    ) -> Tuple[List[int], float]:
        """Greedy solver: sort by diagonal (linear score), pick top K."""
        n = len(Q)
        if n == 0:
            return [], 0.0

        # Sort by diagonal value (lower = better, since we minimize)
        indices = sorted(range(n), key=lambda i: Q[i][i])

        x = [0] * n
        for i in indices[:max_k]:
            x[i] = 1

        obj = self._evaluate(Q, x)
        return x, obj

    def simulated_annealing(
        self,
        Q: List[List[float]],
        max_k: int,
        n_steps: int = 1000,
        t_start: float = 2.0,
        t_end: float = 0.01,
        seed: int = 42,
    ) -> Tuple[List[int], float]:
        """Simulated annealing solver."""
        n = len(Q)
        if n == 0:
            return [], 0.0

        rng = random.Random(seed)

        # Start from greedy solution
        x, obj = self.greedy_baseline(Q, max_k)
        best_x = list(x)
        best_obj = obj

        for step in range(n_steps):
            t = t_start * (t_end / t_start) ** (step / max(n_steps - 1, 1))

            # Flip a random bit
            i = rng.randint(0, n - 1)
            x_new = list(x)
            x_new[i] = 1 - x_new[i]

            # Check constraint
            if sum(x_new) > max_k:
                continue

            obj_new = self._evaluate(Q, x_new)
            delta = obj_new - obj

            if delta < 0 or rng.random() < math.exp(-delta / max(t, 1e-10)):
                x = x_new
                obj = obj_new
                if obj < best_obj:
                    best_obj = obj
                    best_x = list(x)

        return best_x, best_obj

    # --- High-level solve ---------------------------------------------------

    def solve(
        self,
        candidates: List[MemoryCandidate],
        query_tags: Optional[List[str]] = None,
        query_domain: Optional[str] = None,
        current_block: int = 0,
        solver: str = "auto",
    ) -> QUBOResult:
        """Build QUBO matrix and solve.

        solver: "brute_force", "greedy", "sa", or "auto"
            auto = brute_force if n <= 20, else sa
        """
        t_start = time.time()

        n = len(candidates)
        if n == 0:
            return QUBOResult(
                selected_indices=[], selected_hashes=[],
                objective_value=0.0, solver="empty",
                n_candidates=0, max_k=self.max_k,
                terms={}, rejected_indices=[], rejected_hashes=[],
                wall_time_ms=0.0,
            )

        Q = self.build_matrix(candidates, query_tags, query_domain, current_block)

        if solver == "auto":
            solver = "brute_force" if n <= 20 else "sa"

        if solver == "brute_force":
            x, obj = self.brute_force(Q, self.max_k)
        elif solver == "greedy":
            x, obj = self.greedy_baseline(Q, self.max_k)
        elif solver == "sa":
            x, obj = self.simulated_annealing(Q, self.max_k)
        else:
            raise ValueError(f"Unknown solver: {solver}")

        selected = [i for i in range(n) if x[i] == 1]
        rejected = [i for i in range(n) if x[i] == 0]

        # Compute term breakdown for receipt
        terms = self._compute_term_breakdown(Q, candidates, selected, query_tags, query_domain, current_block)

        wall_ms = (time.time() - t_start) * 1000

        return QUBOResult(
            selected_indices=selected,
            selected_hashes=[candidates[i].receipt_hash for i in selected],
            objective_value=obj,
            solver=solver,
            n_candidates=n,
            max_k=self.max_k,
            terms=terms,
            rejected_indices=rejected,
            rejected_hashes=[candidates[i].receipt_hash for i in rejected],
            wall_time_ms=round(wall_ms, 3),
        )

    def _compute_term_breakdown(
        self,
        Q: List[List[float]],
        candidates: List[MemoryCandidate],
        selected: List[int],
        query_tags, query_domain, current_block,
    ) -> Dict[str, float]:
        """Break down objective value into named terms for receipt."""
        if not selected:
            return {}

        terms = {
            "linear_total": sum(Q[i][i] for i in selected),
            "quadratic_total": sum(
                Q[i][j] for i in selected for j in selected if i != j
            ),
            "n_selected": len(selected),
            "n_candidates": len(candidates),
        }

        # Summarize selected memory properties
        sel_candidates = [candidates[i] for i in selected]
        terms["selected_domains"] = list(set(c.domain for c in sel_candidates))
        terms["selected_outcomes"] = list(set(c.outcome for c in sel_candidates))
        terms["avg_edge_weight"] = (
            sum(c.edge_weight_sum for c in sel_candidates) / len(sel_candidates)
            if sel_candidates else 0.0
        )

        return terms

    # --- Integration: select memories for HUD -------------------------------

    def select_for_hud(
        self,
        graph: ReceiptGraph,
        tags: Optional[List[str]] = None,
        domain: Optional[str] = None,
        current_block: int = 0,
        solver: str = "auto",
    ) -> Tuple[QUBOResult, Dict[str, Any]]:
        """Select memories and produce HUD summary.

        Returns (result, hud_dict) where hud_dict is the memory
        signal for the model.
        """
        candidates = self.extract_candidates(graph, tags, domain, current_block)

        if not candidates:
            hud = {
                "memory_status": "no_relevant_memory",
                "active_patterns": 0,
                "dominant_outcome": "unknown",
                "memory_strength": "none",
                "selector": "qubo",
            }
            return QUBOResult(
                selected_indices=[], selected_hashes=[],
                objective_value=0.0, solver="empty",
                n_candidates=0, max_k=self.max_k,
                terms={}, rejected_indices=[], rejected_hashes=[],
                wall_time_ms=0.0,
            ), hud

        result = self.solve(candidates, tags, domain, current_block, solver)

        # Build HUD from selected memories
        if not result.selected_indices:
            hud = {
                "memory_status": "no_selection",
                "active_patterns": 0,
                "dominant_outcome": "unknown",
                "memory_strength": "none",
                "selector": "qubo",
            }
        else:
            sel = [candidates[i] for i in result.selected_indices]

            # Weighted vote on outcome
            outcome_votes: Dict[str, float] = {}
            for c in sel:
                if c.outcome != "unknown":
                    w = c.edge_weight_sum / max(c.edge_count, 1)
                    outcome_votes[c.outcome] = outcome_votes.get(c.outcome, 0.0) + w

            dominant = max(outcome_votes, key=outcome_votes.get) if outcome_votes else "unknown"

            max_w = max(c.edge_weight_sum / max(c.edge_count, 1) for c in sel) if sel else 0.0
            if max_w >= 0.8:
                strength = "strong"
            elif max_w >= 0.5:
                strength = "moderate"
            elif max_w >= COLD_THRESHOLD:
                strength = "weak"
            else:
                strength = "none"

            hud = {
                "memory_status": "active",
                "active_patterns": len(sel),
                "dominant_outcome": dominant,
                "memory_strength": strength,
                "selector": "qubo",
                "qubo_objective": round(result.objective_value, 4),
            }

        return result, hud
