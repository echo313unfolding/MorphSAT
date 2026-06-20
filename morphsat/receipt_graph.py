"""
MorphSAT Receipt Graph — Layer 2: Living Associative Memory
=============================================================

Weighted graph over receipt hashes. Strengthens useful paths,
decays stale paths. Dead chains remain in the immutable chain
(Layer 1) but stop steering behavior here.

Architecture:
    chain records everything (unconscious — complete, unfiltered)
        |
    graph selects what's active (conscious — filtered, weighted)
        |
    graph makes predictions (terrain: "this is flagged ground")
        |
    prediction gets tested (episode plays out)
        |
    result gets receipted (back into chain)
        |
    receipt updates the graph (reinforce if right, weaken if wrong)
        |
    graph's predictions change
        |
    loop

The loop closes at score_prediction(). That's where the graph
bets on an outcome, and close_episode_feedback() is where it
pays when it's wrong. Structure emerges when clusters of edges
survive repeated reinforcement — those clusters become stable
patterns that reliably predict outcomes.

Decay model:
    - Base decay per block: all edges lose weight over time
    - Fast decay: temporary tool output, draft hypotheses
    - Slow decay: formal results, benchmarks, compliance
    - Contradiction penalty: edge weakened when prediction fails
    - Reinforcement boost: edge strengthened when prediction succeeds
    - Cold threshold: below min_weight, edge stops appearing in retrieval
      but is never deleted (provenance preserved)

Edge types (how receipts connect):
    same_domain       — same alert domain / investigation type
    same_outcome      — same final_action (COMMIT/ABSTAIN)
    same_direction    — same final_direction (benign/escalate/suspicious)
    same_boundary     — same boundary crossed (threat/safe/none)
    same_tool_pattern — same evidence_vector structure
    correction_of     — later receipt corrected earlier receipt
    contradiction     — later receipt contradicts earlier receipt
    temporal_sequence — receipts from same episode block
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Decay rates by receipt class
# ---------------------------------------------------------------------------

DECAY_RATES = {
    "formal":    0.02,   # benchmarks, compliance, human approval
    "decision":  0.05,   # commit/abstain/escalate decisions
    "evidence":  0.10,   # tool outputs, observations
    "temporary": 0.20,   # draft hypotheses, ambiguous signals
}

DEFAULT_DECAY = 0.05
COLD_THRESHOLD = 0.15    # below this, edge is cold (not retrieved)
REINFORCE_BOOST = 0.15   # weight gain on successful prediction
CONTRADICT_PENALTY = 0.25 # weight loss on failed prediction


# ---------------------------------------------------------------------------
# Node and Edge
# ---------------------------------------------------------------------------

@dataclass
class ReceiptNode:
    """A receipt projected into the living graph."""
    receipt_hash: str
    block_number: int
    domain: str           # derived from receipt (e.g. "security", "code_review")
    outcome: str          # final_direction: benign/suspicious/escalate/abstain
    action: str           # final_action: COMMIT/ABSTAIN/CONTINUE
    timestamp: str
    receipt_class: str    # formal/decision/evidence/temporary
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ReceiptNode:
        return cls(**d)


@dataclass
class ReceiptEdge:
    """A weighted connection between two receipts."""
    from_hash: str
    to_hash: str
    edge_type: str
    weight: float = 0.5
    reinforcements: int = 0
    contradictions: int = 0
    last_reinforced: str = ""
    created_at_block: int = 0
    evidence: List[str] = field(default_factory=list)

    @property
    def is_cold(self) -> bool:
        return self.weight < COLD_THRESHOLD

    def reinforce(self, boost: float = REINFORCE_BOOST) -> None:
        self.weight = min(1.0, self.weight + boost)
        self.reinforcements += 1
        self.last_reinforced = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def contradict(self, penalty: float = CONTRADICT_PENALTY) -> None:
        self.weight = max(0.0, self.weight - penalty)
        self.contradictions += 1

    def decay(self, rate: float) -> None:
        self.weight = max(0.0, self.weight - rate)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ReceiptEdge:
        # Handle is_cold being in saved data (it's a property, not a field)
        d = {k: v for k, v in d.items() if k != "is_cold"}
        return cls(**d)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class ReceiptGraph:
    """Living associative memory over receipt hashes.

    The graph is the conscious layer. It selects, weights, and predicts.
    The chain (Layer 1) is the unconscious layer — it remembers everything.

    The error-correction loop:
        1. add_node() — receipt enters the graph
        2. auto_connect() — edges form to related receipts
        3. predict() — graph bets on what a new pattern will produce
        4. score_prediction() — after episode, check if prediction was right
        5. reinforce/contradict — update edge weights based on outcome
        6. decay_all() — time passes, unused edges fade
        7. retrieve_active() — only strong edges steer behavior
        8. export_memory_hud() — model sees coarse summary, not weights

    Structure emerges when a cluster of edges survives repeated
    reinforcement cycles. That cluster becomes stable memory —
    the point where unconscious (chain) and conscious (graph) correlate.
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.nodes: Dict[str, ReceiptNode] = {}
        self.edges: List[ReceiptEdge] = []
        self._current_block: int = 0
        self._last_prediction: Optional[Dict[str, Any]] = None
        self._load()

    # --- Node operations ---------------------------------------------------

    def add_node(
        self,
        receipt_hash: str,
        receipt: Dict[str, Any],
        block_number: int,
    ) -> ReceiptNode:
        """Project a receipt into the graph as a node."""
        node = ReceiptNode(
            receipt_hash=receipt_hash,
            block_number=block_number,
            domain=self._extract_domain(receipt),
            outcome=receipt.get("final_direction", "unknown"),
            action=receipt.get("final_action", "CONTINUE"),
            timestamp=receipt.get("timestamp",
                                  time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                time.gmtime())),
            receipt_class=self._classify_receipt(receipt),
            tags=self._extract_tags(receipt),
        )
        self.nodes[receipt_hash] = node
        self._save()
        return node

    # --- Edge operations ---------------------------------------------------

    def connect(
        self,
        from_hash: str,
        to_hash: str,
        edge_type: str,
        evidence: Optional[List[str]] = None,
        initial_weight: float = 0.5,
    ) -> Optional[ReceiptEdge]:
        """Create a weighted edge between two receipt nodes."""
        if from_hash not in self.nodes or to_hash not in self.nodes:
            return None
        # Don't create duplicate edges
        for e in self.edges:
            if (e.from_hash == from_hash and e.to_hash == to_hash
                    and e.edge_type == edge_type):
                return e

        edge = ReceiptEdge(
            from_hash=from_hash,
            to_hash=to_hash,
            edge_type=edge_type,
            weight=initial_weight,
            created_at_block=self._current_block,
            evidence=evidence or [],
        )
        self.edges.append(edge)
        self._save()
        return edge

    def auto_connect(self, receipt_hash: str) -> List[ReceiptEdge]:
        """Automatically connect a new node to related existing nodes.

        This is where associations form. Receipts connect when they
        share meaningful structure.
        """
        if receipt_hash not in self.nodes:
            return []

        new_node = self.nodes[receipt_hash]
        created = []

        for other_hash, other_node in self.nodes.items():
            if other_hash == receipt_hash:
                continue

            # Same domain
            if (new_node.domain == other_node.domain
                    and new_node.domain != "unknown"):
                edge = self.connect(
                    other_hash, receipt_hash, "same_domain",
                    [f"shared_domain:{new_node.domain}"])
                if edge:
                    created.append(edge)

            # Same outcome
            if (new_node.outcome == other_node.outcome
                    and new_node.outcome != "unknown"):
                edge = self.connect(
                    other_hash, receipt_hash, "same_outcome",
                    [f"shared_outcome:{new_node.outcome}"])
                if edge:
                    created.append(edge)

            # Same action
            if new_node.action == other_node.action:
                edge = self.connect(
                    other_hash, receipt_hash, "same_action",
                    [f"shared_action:{new_node.action}"])
                if edge:
                    created.append(edge)

            # Shared tags (at least 2 in common)
            common_tags = set(new_node.tags) & set(other_node.tags)
            if len(common_tags) >= 2:
                edge = self.connect(
                    other_hash, receipt_hash, "shared_tags",
                    [f"tag:{t}" for t in sorted(common_tags)])
                if edge:
                    created.append(edge)

        return created

    def reinforce_path(self, receipt_hashes: List[str]) -> int:
        """Strengthen all edges along a path of receipt hashes."""
        reinforced = 0
        for i in range(len(receipt_hashes) - 1):
            a, b = receipt_hashes[i], receipt_hashes[i + 1]
            for edge in self.edges:
                if ((edge.from_hash == a and edge.to_hash == b)
                        or (edge.from_hash == b and edge.to_hash == a)):
                    edge.reinforce()
                    reinforced += 1
        if reinforced:
            self._save()
        return reinforced

    def weaken_edges(self, receipt_hash: str, penalty: float = CONTRADICT_PENALTY) -> int:
        """Weaken all edges touching a receipt (prediction was wrong)."""
        weakened = 0
        for edge in self.edges:
            if edge.from_hash == receipt_hash or edge.to_hash == receipt_hash:
                edge.contradict(penalty)
                weakened += 1
        if weakened:
            self._save()
        return weakened

    # --- Decay -------------------------------------------------------------

    def decay_all(self, current_block: int) -> int:
        """Apply time-based decay to all edges.

        Different receipt classes decay at different rates.
        A benchmark receipt decays slowly. A tool output decays fast.
        """
        self._current_block = current_block
        decayed = 0
        for edge in self.edges:
            if edge.is_cold:
                continue  # already cold, don't decay further to zero
            # Use the slower of the two connected nodes' decay rates
            from_node = self.nodes.get(edge.from_hash)
            to_node = self.nodes.get(edge.to_hash)
            from_rate = DECAY_RATES.get(
                from_node.receipt_class if from_node else "evidence",
                DEFAULT_DECAY)
            to_rate = DECAY_RATES.get(
                to_node.receipt_class if to_node else "evidence",
                DEFAULT_DECAY)
            rate = min(from_rate, to_rate)

            blocks_since = max(0, current_block - edge.created_at_block)
            if blocks_since > 0:
                edge.decay(rate)
                decayed += 1
        if decayed:
            self._save()
        return decayed

    # --- Prediction and error correction -----------------------------------

    def predict(self, tags: List[str], domain: str = "") -> Dict[str, Any]:
        """Graph bets on what a new pattern will produce.

        Looks at active edges connected to nodes matching the query.
        Returns a prediction based on weighted vote of connected outcomes.

        This is the "conscious" prediction — what the graph thinks will happen
        based on what it has learned from prior receipts.
        """
        # Find matching nodes
        candidates = []
        for node in self.nodes.values():
            score = 0.0
            if domain and node.domain == domain:
                score += 0.5
            tag_overlap = len(set(tags) & set(node.tags))
            score += tag_overlap * 0.25
            if score > 0:
                candidates.append((node, score))

        if not candidates:
            prediction = {
                "predicted_outcome": "unknown",
                "confidence": 0.0,
                "supporting_receipts": 0,
                "basis_hashes": [],
            }
            self._last_prediction = prediction
            return prediction

        # Weighted vote from active edges
        outcome_weights: Dict[str, float] = {}
        basis_hashes: Set[str] = set()

        for node, match_score in candidates:
            # Get active edges for this node
            for edge in self.edges:
                if edge.is_cold:
                    continue
                if edge.from_hash == node.receipt_hash:
                    other = self.nodes.get(edge.to_hash)
                elif edge.to_hash == node.receipt_hash:
                    other = self.nodes.get(edge.from_hash)
                else:
                    continue

                if other and other.outcome != "unknown":
                    vote = edge.weight * match_score
                    outcome_weights[other.outcome] = (
                        outcome_weights.get(other.outcome, 0.0) + vote)
                    basis_hashes.add(other.receipt_hash)

            # The candidate node itself votes too
            if node.outcome != "unknown":
                outcome_weights[node.outcome] = (
                    outcome_weights.get(node.outcome, 0.0) + match_score)
                basis_hashes.add(node.receipt_hash)

        if not outcome_weights:
            prediction = {
                "predicted_outcome": "unknown",
                "confidence": 0.0,
                "supporting_receipts": 0,
                "basis_hashes": [],
            }
        else:
            total = sum(outcome_weights.values())
            best = max(outcome_weights, key=outcome_weights.get)
            confidence = outcome_weights[best] / total if total > 0 else 0.0

            prediction = {
                "predicted_outcome": best,
                "confidence": round(confidence, 3),
                "supporting_receipts": len(basis_hashes),
                "basis_hashes": sorted(basis_hashes),
            }

        self._last_prediction = prediction
        return prediction

    def score_prediction(self, actual_outcome: str) -> Dict[str, Any]:
        """The loop closes here. Compare prediction to actual outcome.

        If the graph predicted correctly: reinforce the edges that
        contributed to the prediction.
        If the graph predicted wrongly: weaken those edges.

        This is error correction. The graph bets, then pays.
        Structure emerges when correct bets accumulate and
        wrong bets decay — the surviving clusters are memory.
        """
        if not self._last_prediction:
            return {"scored": False, "reason": "no_prediction"}

        pred = self._last_prediction
        predicted = pred["predicted_outcome"]
        basis = pred["basis_hashes"]
        correct = (predicted == actual_outcome)

        if correct and basis:
            # Reinforce the path that led to the correct prediction
            for h in basis:
                for edge in self.edges:
                    if edge.from_hash == h or edge.to_hash == h:
                        if not edge.is_cold:
                            edge.reinforce()
        elif not correct and basis:
            # Weaken edges that contributed to wrong prediction
            for h in basis:
                for edge in self.edges:
                    if edge.from_hash == h or edge.to_hash == h:
                        if not edge.is_cold:
                            edge.contradict()

        result = {
            "scored": True,
            "predicted": predicted,
            "actual": actual_outcome,
            "correct": correct,
            "basis_size": len(basis),
            "action": "reinforced" if correct else "weakened",
        }

        self._last_prediction = None
        self._save()
        return result

    # --- Retrieval ---------------------------------------------------------

    def retrieve_active(
        self,
        tags: Optional[List[str]] = None,
        domain: Optional[str] = None,
        min_weight: float = COLD_THRESHOLD,
    ) -> List[Dict[str, Any]]:
        """Get active chains — edges above cold threshold.

        Dead chains are not retrieved but still exist in the graph
        (and are always verifiable in the immutable chain).
        """
        results = []
        for edge in self.edges:
            if edge.weight < min_weight:
                continue

            from_node = self.nodes.get(edge.from_hash)
            to_node = self.nodes.get(edge.to_hash)
            if not from_node or not to_node:
                continue

            # Filter by tags/domain if specified
            if domain and from_node.domain != domain and to_node.domain != domain:
                continue
            if tags:
                from_tags = set(from_node.tags)
                to_tags = set(to_node.tags)
                if not (set(tags) & (from_tags | to_tags)):
                    continue

            results.append({
                "from": from_node.receipt_hash[:16],
                "to": to_node.receipt_hash[:16],
                "edge_type": edge.edge_type,
                "weight": round(edge.weight, 3),
                "reinforcements": edge.reinforcements,
                "from_outcome": from_node.outcome,
                "to_outcome": to_node.outcome,
            })

        results.sort(key=lambda x: x["weight"], reverse=True)
        return results

    def mark_cold(self, receipt_hash: str) -> int:
        """Force all edges touching a receipt to cold."""
        marked = 0
        for edge in self.edges:
            if edge.from_hash == receipt_hash or edge.to_hash == receipt_hash:
                if not edge.is_cold:
                    edge.weight = 0.0
                    marked += 1
        if marked:
            self._save()
        return marked

    # --- HUD ---------------------------------------------------------------

    def export_memory_hud(
        self,
        tags: Optional[List[str]] = None,
        domain: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Coarse memory signal for the model.

        Same rule as MorphSAT HUD: compass, not the map.
        The model sees a summary. It does NOT see edge weights,
        reinforcement counts, decay rates, or prediction internals.
        """
        active = self.retrieve_active(tags=tags, domain=domain)

        if not active:
            return {
                "memory_status": "no_relevant_memory",
                "active_patterns": 0,
                "dominant_outcome": "unknown",
                "memory_strength": "none",
            }

        # Dominant outcome from active edges
        outcome_votes: Dict[str, float] = {}
        for a in active:
            for outcome_key in ("from_outcome", "to_outcome"):
                o = a[outcome_key]
                if o != "unknown":
                    outcome_votes[o] = outcome_votes.get(o, 0.0) + a["weight"]

        dominant = max(outcome_votes, key=outcome_votes.get) if outcome_votes else "unknown"

        # Strength: coarse bucket from max weight
        max_w = max(a["weight"] for a in active) if active else 0.0
        if max_w >= 0.8:
            strength = "strong"
        elif max_w >= 0.5:
            strength = "moderate"
        elif max_w >= COLD_THRESHOLD:
            strength = "weak"
        else:
            strength = "none"

        return {
            "memory_status": "active",
            "active_patterns": len(active),
            "dominant_outcome": dominant,
            "memory_strength": strength,
        }

    # --- Stats and export --------------------------------------------------

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    @property
    def active_edge_count(self) -> int:
        return sum(1 for e in self.edges if not e.is_cold)

    @property
    def cold_edge_count(self) -> int:
        return sum(1 for e in self.edges if e.is_cold)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_version": "v1",
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "active_edges": self.active_edge_count,
            "cold_edges": self.cold_edge_count,
            "nodes": {h: n.to_dict() for h, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
        }

    # --- Internal helpers --------------------------------------------------

    def _extract_domain(self, receipt: Dict[str, Any]) -> str:
        """Derive domain from receipt content."""
        # Use evidence vector categories if available
        ev = receipt.get("evidence_vector", [])
        if ev:
            categories = [cat for _, cat in ev if isinstance(cat, str)]
            if categories:
                # Most frequent category
                from collections import Counter
                return Counter(categories).most_common(1)[0][0]

        # Fallback: use final_direction as a rough domain
        direction = receipt.get("final_direction", "")
        if direction:
            return direction
        return "unknown"

    def _classify_receipt(self, receipt: Dict[str, Any]) -> str:
        """Classify receipt for decay rate selection."""
        version = receipt.get("gate_version", "")
        action = receipt.get("final_action", "")

        # Formal first — benchmarks and compliance outrank action type
        if "benchmark" in version or "bench" in version:
            return "formal"
        if action in ("COMMIT", "ABSTAIN"):
            return "decision"
        if action == "CONTINUE":
            return "temporary"
        return "evidence"

    def _extract_tags(self, receipt: Dict[str, Any]) -> List[str]:
        """Extract searchable tags from receipt."""
        tags = []
        if receipt.get("gate_version"):
            tags.append(receipt["gate_version"])
        if receipt.get("final_action"):
            tags.append(receipt["final_action"])
        if receipt.get("final_direction"):
            tags.append(receipt["final_direction"])
        if receipt.get("initial_state"):
            tags.append(f"init:{receipt['initial_state']}")

        # Tags from evidence categories
        ev = receipt.get("evidence_vector", [])
        seen = set()
        for _, cat in ev:
            if isinstance(cat, str) and cat not in seen:
                tags.append(f"ev:{cat}")
                seen.add(cat)

        return tags

    # --- Persistence -------------------------------------------------------

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.nodes = {
                h: ReceiptNode.from_dict(n)
                for h, n in data.get("nodes", {}).items()
            }
            self.edges = [
                ReceiptEdge.from_dict(e) for e in data.get("edges", [])
            ]
        except (json.JSONDecodeError, KeyError, TypeError):
            self.nodes = {}
            self.edges = []

    def clear(self) -> None:
        """Reset graph. For testing only."""
        self.nodes.clear()
        self.edges.clear()
        self._last_prediction = None
        if self.path.exists():
            self.path.unlink()
