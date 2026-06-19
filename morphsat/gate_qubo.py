"""
MorphSAT QUBO Gate — monitor commit decisions as binary optimization.
=====================================================================

Replaces scalar threshold logic in CommitGate._decide() with a QUBO
formulation. The gate chooses among 5 actions:

    COMMIT_BENIGN, COMMIT_SUSPICIOUS, COMMIT_ESCALATE, CONTINUE, ABSTAIN

Each action is a binary variable. Exactly one is selected (one-hot
constraint via penalty). The QUBO matrix encodes:

    Linear terms (diagonal):
        Evidence clarity, threat/safety scores, urgency, investigation
        budget, memory signals, graph signals.

    Quadratic terms (off-diagonal):
        Sensor-memory disagreement, graph-threshold contradiction,
        stale memory penalty on commit, coverage-gap penalty on commit.

This does NOT replace the evidence sensors, shadow states, or receipt
chain. It replaces only the _decide() step — the moment where
accumulated evidence becomes an action.

Integration:
    ShadowMonitor can swap its _decide() call for GateQUBO.decide().
    CommitGate can use GateQUBO as an alternative decision backend.
    Benchmarks compare threshold vs QUBO on identical evidence streams.

Lineage:
    CommitGate._decide (threshold) → GateQUBO.decide (optimization)
    MemoryQUBO (selects memories) → GateQUBO (selects action)
    batch_scheduler_qubo (codec assignment) → GateQUBO (action assignment)
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from morphsat.commit_gate import CommitAction


# ---------------------------------------------------------------------------
# Action encoding
# ---------------------------------------------------------------------------

ACTIONS = [
    "commit_benign",
    "commit_suspicious",
    "commit_escalate",
    "continue",
    "abstain",
]

ACTION_TO_COMMIT = {
    "commit_benign": ("COMMIT", "benign"),
    "commit_suspicious": ("COMMIT", "suspicious"),
    "commit_escalate": ("COMMIT", "escalate"),
    "continue": ("CONTINUE", None),
    "abstain": ("ABSTAIN", None),
}

N_ACTIONS = len(ACTIONS)


# ---------------------------------------------------------------------------
# Evidence snapshot — everything the gate needs to decide
# ---------------------------------------------------------------------------

@dataclass
class GateSnapshot:
    """Point-in-time evidence state for the QUBO solver."""
    threat_score: float = 0.0
    safety_score: float = 0.0
    evidence_clarity: float = 0.0       # |threat - safety|
    contradiction: float = 0.0          # min(threat, safety)
    urgency: float = 0.0                # turn * urgency_rate
    exhaustion: float = 0.0             # overshoot past budget
    tool_count: int = 0
    max_tools: int = 8

    # Memory signals
    memory_outcome: str = "unknown"     # benign/escalate/unknown from SplitMemory
    memory_confidence: float = 0.0
    memory_exposures: int = 0
    novelty: float = 1.0               # 0=known, 1=novel

    # Graph signals (from ReceiptGraph/MemoryQUBO)
    graph_dominant_outcome: str = "unknown"
    graph_strength: str = "none"        # none/weak/moderate/strong
    graph_reinforcements: int = 0
    graph_contradictions: int = 0
    graph_cold_edges: int = 0
    graph_prediction_outcome: str = "unknown"

    # Shadow state context
    shadow_state: str = "normal"

    # Correction signal (v9)
    correction_seen: bool = False


@dataclass
class GateQUBOResult:
    """Result of QUBO gate decision."""
    action: str                         # CommitAction.action
    direction: Optional[str]            # CommitAction.direction
    reason: str
    selected_action_name: str           # e.g. "commit_escalate"
    objective_value: float
    solver: str
    action_scores: Dict[str, float]     # diagonal score per action
    wall_time_ms: float
    snapshot: Dict[str, Any]            # the evidence state used


# ---------------------------------------------------------------------------
# QUBO Gate
# ---------------------------------------------------------------------------

class GateQUBO:
    """QUBO-based monitor gate decision.

    Instead of: commit_pressure >= threshold → direction from score comparison
    This does:  minimize x^T Q x over 5 action variables, one-hot constrained.

    The weights encode domain knowledge about when each action is appropriate.
    The quadratic terms encode interactions (memory disagrees with sensor, etc).
    """

    def __init__(
        self,
        # --- Linear weights (negative = reward action, positive = penalize) ---

        # COMMIT rewards (when evidence supports committing)
        w_clarity_commit: float = -3.0,         # reward commit when evidence is clear
        w_threat_escalate: float = -2.5,        # reward escalate on strong threat
        w_safety_benign: float = -2.5,          # reward benign on strong safety
        w_moderate_suspicious: float = -1.5,    # reward suspicious on moderate signal

        # COMMIT penalties (when evidence opposes committing)
        w_contradiction_commit: float = 3.0,    # penalize commit under contradiction
        w_low_evidence_commit: float = 2.0,     # penalize commit on thin evidence
        w_novel_commit: float = 1.5,            # penalize commit on novel patterns

        # CONTINUE rewards/penalties
        w_budget_continue: float = -1.5,        # reward continue when budget remains
        w_urgency_continue: float = 2.0,        # penalize continue under urgency
        w_exhaustion_continue: float = 3.0,     # penalize continue past exhaustion

        # ABSTAIN rewards/penalties
        w_contradiction_abstain: float = -2.5,  # reward abstain under contradiction
        w_clarity_abstain: float = 2.0,         # penalize abstain when evidence is clear
        w_correction_abstain: float = -1.5,     # reward abstain after correction seen

        # --- Quadratic weights (cross-action penalties) ---
        w_memory_disagree: float = 2.0,         # penalize commit if memory disagrees
        w_graph_disagree: float = 2.0,          # penalize commit if graph disagrees
        w_stale_commit: float = 1.5,            # penalize commit on stale/cold graph
        w_graph_reinforce: float = -1.5,        # reward commit when graph reinforces

        # --- One-hot constraint penalty ---
        w_onehot: float = 20.0,

        # --- SA parameters ---
        sa_steps: int = 500,
        sa_seed: int = 42,
    ):
        self.w_clarity_commit = w_clarity_commit
        self.w_threat_escalate = w_threat_escalate
        self.w_safety_benign = w_safety_benign
        self.w_moderate_suspicious = w_moderate_suspicious
        self.w_contradiction_commit = w_contradiction_commit
        self.w_low_evidence_commit = w_low_evidence_commit
        self.w_novel_commit = w_novel_commit
        self.w_budget_continue = w_budget_continue
        self.w_urgency_continue = w_urgency_continue
        self.w_exhaustion_continue = w_exhaustion_continue
        self.w_contradiction_abstain = w_contradiction_abstain
        self.w_clarity_abstain = w_clarity_abstain
        self.w_correction_abstain = w_correction_abstain
        self.w_memory_disagree = w_memory_disagree
        self.w_graph_disagree = w_graph_disagree
        self.w_stale_commit = w_stale_commit
        self.w_graph_reinforce = w_graph_reinforce
        self.w_onehot = w_onehot
        self.sa_steps = sa_steps
        self.sa_seed = sa_seed

    # --- QUBO matrix construction -------------------------------------------

    def build_matrix(self, snap: GateSnapshot) -> List[List[float]]:
        """Build 5x5 QUBO matrix Q for the 5 action variables.

        Indices: 0=commit_benign, 1=commit_suspicious, 2=commit_escalate,
                 3=continue, 4=abstain
        """
        Q = [[0.0] * N_ACTIONS for _ in range(N_ACTIONS)]

        # Shorthands
        clarity = snap.evidence_clarity
        contra = snap.contradiction
        threat = snap.threat_score
        safety = snap.safety_score
        total_ev = threat + safety
        urgency = snap.urgency
        exhaust = snap.exhaustion
        budget_frac = max(0.0, 1.0 - snap.tool_count / max(snap.max_tools, 1))
        novelty = snap.novelty

        # Graph signal strength as float
        graph_str = {"none": 0.0, "weak": 0.25, "moderate": 0.5, "strong": 1.0
                     }.get(snap.graph_strength, 0.0)

        # =====================================================================
        # DIAGONAL: linear terms per action
        # =====================================================================

        # --- commit_benign (index 0) ---
        score = 0.0
        score += self.w_clarity_commit * min(1.0, clarity)
        score += self.w_safety_benign * min(1.0, safety)
        # Penalize benign when threat is high
        score += abs(self.w_threat_escalate) * 0.5 * min(1.0, threat)
        score += self.w_contradiction_commit * min(1.0, contra)
        if total_ev < 0.2:
            score += self.w_low_evidence_commit
        score += self.w_novel_commit * novelty
        Q[0][0] = score

        # --- commit_suspicious (index 1) ---
        score = 0.0
        score += self.w_clarity_commit * min(1.0, clarity) * 0.7  # less reward than clear commit
        score += self.w_moderate_suspicious * min(1.0, (threat + safety) / 2)
        score += self.w_contradiction_commit * min(1.0, contra) * 0.5
        if total_ev < 0.2:
            score += self.w_low_evidence_commit
        score += self.w_novel_commit * novelty * 0.5
        Q[1][1] = score

        # --- commit_escalate (index 2) ---
        score = 0.0
        score += self.w_clarity_commit * min(1.0, clarity)
        score += self.w_threat_escalate * min(1.0, threat)
        # Penalize escalate when safety is high
        score += abs(self.w_safety_benign) * 0.5 * min(1.0, safety)
        score += self.w_contradiction_commit * min(1.0, contra)
        if total_ev < 0.2:
            score += self.w_low_evidence_commit
        score += self.w_novel_commit * novelty
        Q[2][2] = score

        # --- continue (index 3) ---
        score = 0.0
        score += self.w_budget_continue * budget_frac
        score += self.w_urgency_continue * min(1.0, urgency)
        score += self.w_exhaustion_continue * min(1.0, exhaust)
        # Penalize continuing when evidence is very clear
        if clarity > 0.5:
            score += abs(self.w_clarity_commit) * 0.3 * clarity
        Q[3][3] = score

        # --- abstain (index 4) ---
        score = 0.0
        score += self.w_contradiction_abstain * min(1.0, contra)
        score += self.w_clarity_abstain * min(1.0, clarity)
        if snap.correction_seen:
            score += self.w_correction_abstain
        # Abstain more attractive when novelty is high and evidence thin
        if novelty > 0.8 and total_ev < 0.3:
            score += -0.5
        Q[4][4] = score

        # =====================================================================
        # OFF-DIAGONAL: quadratic interaction terms
        # =====================================================================

        # Memory disagrees with action
        # If memory says benign but we're trying to escalate (or vice versa)
        mem = snap.memory_outcome
        mem_conf = snap.memory_confidence

        if mem == "benign" and mem_conf > 0.5:
            # Memory says safe → penalize escalate
            Q[2][2] += self.w_memory_disagree * mem_conf
            # Memory says safe → slightly reward benign
            Q[0][0] += -0.5 * mem_conf
        elif mem == "escalate" and mem_conf > 0.5:
            # Memory says threat → penalize benign
            Q[0][0] += self.w_memory_disagree * mem_conf
            # Memory says threat → slightly reward escalate
            Q[2][2] += -0.5 * mem_conf

        # Graph disagrees with action
        gout = snap.graph_dominant_outcome
        gpred = snap.graph_prediction_outcome
        g_reinf = snap.graph_reinforcements
        g_contra = snap.graph_contradictions

        if gout == "benign" and graph_str > 0.25:
            Q[2][2] += self.w_graph_disagree * graph_str
        elif gout == "escalate" and graph_str > 0.25:
            Q[0][0] += self.w_graph_disagree * graph_str

        # Graph reinforcement rewards commit in the reinforced direction
        if g_reinf > 0 and g_contra == 0:
            reinf_signal = min(1.0, g_reinf / 5.0)
            if gout == "benign":
                Q[0][0] += self.w_graph_reinforce * reinf_signal
            elif gout == "escalate":
                Q[2][2] += self.w_graph_reinforce * reinf_signal

        # Graph contradiction → push toward abstain
        if g_contra > 0:
            contra_signal = min(1.0, g_contra / 3.0)
            Q[4][4] += -1.0 * contra_signal  # reward abstain
            # Penalize all commits
            for ci in [0, 1, 2]:
                Q[ci][ci] += 0.5 * contra_signal

        # Stale/cold graph → penalize committing on graph signal
        if snap.graph_cold_edges > 0 and graph_str > 0:
            cold_ratio = snap.graph_cold_edges / max(g_reinf + g_contra + 1, 1)
            for ci in [0, 1, 2]:
                Q[ci][ci] += self.w_stale_commit * cold_ratio * graph_str

        # Sensor-graph disagreement → mutual penalty on commit, reward abstain
        # This is a TRUE quadratic: the pair (commit_X, continue) gets penalized
        # when sensor and graph disagree
        sensor_dir = "benign" if safety > threat else ("escalate" if threat > 0.5 else "suspicious")
        if gout != "unknown" and sensor_dir != gout and graph_str > 0.25:
            disagree_strength = graph_str * min(1.0, abs(threat - safety))
            # Cross-term: penalize the sensor-favored commit
            if sensor_dir == "benign":
                Q[0][3] += disagree_strength  # benign × continue interaction
                Q[3][0] += disagree_strength
            elif sensor_dir == "escalate":
                Q[2][3] += disagree_strength
                Q[3][2] += disagree_strength
            # Also reward abstain slightly
            Q[4][4] += -0.3 * disagree_strength

        # =====================================================================
        # ONE-HOT CONSTRAINT: exactly one action selected
        # =====================================================================
        # Penalty: w * (sum(x_i) - 1)^2
        # = w * (sum x_i^2 + 2*sum_{i<j} x_i*x_j - 2*sum x_i + 1)
        # Since x_i binary: x_i^2 = x_i
        # Diagonal: w * (1 - 2) = -w  ... add to each diagonal
        # Off-diagonal: w * 2 ... add to each (i,j) pair
        # Constant: w * 1 ... ignored (doesn't affect argmin)

        for i in range(N_ACTIONS):
            Q[i][i] += self.w_onehot * (-1.0)
        for i in range(N_ACTIONS):
            for j in range(i + 1, N_ACTIONS):
                Q[i][j] += self.w_onehot * 2.0
                Q[j][i] += self.w_onehot * 2.0

        return Q

    # --- Solvers ------------------------------------------------------------

    def _evaluate(self, Q: List[List[float]], x: List[int]) -> float:
        """Evaluate x^T Q x."""
        total = 0.0
        for i in range(N_ACTIONS):
            if x[i] == 0:
                continue
            for j in range(N_ACTIONS):
                if x[j] == 0:
                    continue
                total += Q[i][j]
        return total

    def brute_force(self, Q: List[List[float]]) -> Tuple[List[int], float]:
        """Exact: enumerate all 5 one-hot vectors."""
        best_x = [0] * N_ACTIONS
        best_obj = float("inf")

        for k in range(N_ACTIONS):
            x = [0] * N_ACTIONS
            x[k] = 1
            obj = self._evaluate(Q, x)
            if obj < best_obj:
                best_obj = obj
                best_x = list(x)

        return best_x, best_obj

    def simulated_annealing(
        self,
        Q: List[List[float]],
        n_steps: int = 0,
        seed: int = 0,
    ) -> Tuple[List[int], float]:
        """SA solver — explores beyond one-hot (penalized) then settles."""
        n_steps = n_steps or self.sa_steps
        seed = seed or self.sa_seed
        rng = random.Random(seed)

        # Start from brute-force best one-hot
        x, obj = self.brute_force(Q)
        best_x = list(x)
        best_obj = obj

        t_start, t_end = 5.0, 0.01

        for step in range(n_steps):
            t = t_start * (t_end / t_start) ** (step / max(n_steps - 1, 1))

            # Flip a random bit
            i = rng.randint(0, N_ACTIONS - 1)
            x_new = list(x)
            x_new[i] = 1 - x_new[i]

            # Must have at least one selected
            if sum(x_new) == 0:
                continue

            obj_new = self._evaluate(Q, x_new)
            delta = obj_new - obj

            if delta < 0 or rng.random() < math.exp(-delta / max(t, 1e-10)):
                x = x_new
                obj = obj_new
                if obj < best_obj:
                    best_obj = obj
                    best_x = list(x)

        # Final: project to best one-hot if SA wandered
        if sum(best_x) != 1:
            # Pick the selected action with lowest individual score
            selected = [i for i in range(N_ACTIONS) if best_x[i] == 1]
            scores = [(Q[i][i], i) for i in selected]
            scores.sort()
            best_x = [0] * N_ACTIONS
            best_x[scores[0][1]] = 1
            best_obj = self._evaluate(Q, best_x)

        return best_x, best_obj

    # --- High-level decide --------------------------------------------------

    def decide(
        self,
        snap: GateSnapshot,
        solver: str = "brute_force",
    ) -> GateQUBOResult:
        """Build QUBO from evidence snapshot, solve, return action.

        For N=5, brute_force is always fast (5 evaluations). SA is
        available for testing whether exploration finds better solutions
        when the quadratic landscape is complex.
        """
        t0 = time.time()

        Q = self.build_matrix(snap)

        if solver == "brute_force":
            x, obj = self.brute_force(Q)
        elif solver == "sa":
            x, obj = self.simulated_annealing(Q)
        else:
            raise ValueError(f"Unknown solver: {solver}")

        # Decode action
        selected_idx = x.index(1) if 1 in x else 3  # default continue
        action_name = ACTIONS[selected_idx]
        commit_action, direction = ACTION_TO_COMMIT[action_name]

        # Build reason from dominant terms
        reason = self._build_reason(snap, action_name, Q, selected_idx)

        # Action scores for diagnostics
        action_scores = {ACTIONS[i]: round(Q[i][i], 4) for i in range(N_ACTIONS)}

        wall_ms = (time.time() - t0) * 1000

        return GateQUBOResult(
            action=commit_action,
            direction=direction,
            reason=reason,
            selected_action_name=action_name,
            objective_value=round(obj, 4),
            solver=solver,
            action_scores=action_scores,
            wall_time_ms=round(wall_ms, 3),
            snapshot=asdict(snap),
        )

    def decide_as_commit_action(
        self,
        snap: GateSnapshot,
        solver: str = "brute_force",
    ) -> CommitAction:
        """Convenience: return a CommitAction compatible with existing code."""
        result = self.decide(snap, solver)
        return CommitAction(result.action, result.direction, result.reason)

    # --- Snapshot builder (from CommitGate/ShadowMonitor state) ---------------

    @staticmethod
    def snapshot_from_commit_gate(
        gate,
        graph=None,
        graph_hud: Optional[Dict] = None,
    ) -> GateSnapshot:
        """Build a GateSnapshot from a CommitGate's current state."""
        snap = GateSnapshot(
            threat_score=gate.threat_score,
            safety_score=gate.safety_score,
            evidence_clarity=abs(gate.threat_score - gate.safety_score),
            contradiction=min(gate.threat_score, gate.safety_score),
            urgency=gate.turn * gate.urgency_rate,
            exhaustion=max(0, 0.15 * (gate.tool_count - gate.exhaustion_after + 1))
                       if gate.tool_count >= gate.exhaustion_after else 0.0,
            tool_count=gate.tool_count,
            max_tools=gate.exhaustion_after + 3,
            novelty=gate.novelty,
        )

        # Memory signals
        if gate.memory_match:
            store_name, match = gate.memory_match
            if store_name == "tolerance":
                snap.memory_outcome = "benign"
            elif store_name == "threat":
                snap.memory_outcome = "escalate"
            else:
                snap.memory_outcome = "abstain"
            snap.memory_confidence = match.confidence
            snap.memory_exposures = match.exposures

        # Graph signals
        if graph_hud:
            snap.graph_dominant_outcome = graph_hud.get("dominant_outcome", "unknown")
            snap.graph_strength = graph_hud.get("memory_strength", "none")
        if graph:
            snap.graph_reinforcements = sum(
                e.reinforcements for e in graph.edges if not e.is_cold
            )
            snap.graph_contradictions = sum(
                e.contradictions for e in graph.edges if not e.is_cold
            )
            snap.graph_cold_edges = sum(1 for e in graph.edges if e.is_cold)

        return snap

    @staticmethod
    def snapshot_from_shadow_monitor(
        monitor,
        graph_hud: Optional[Dict] = None,
    ) -> GateSnapshot:
        """Build a GateSnapshot from a ShadowMonitor's current state."""
        snap = GateSnapshot(
            threat_score=monitor.threat_score,
            safety_score=monitor.safety_score,
            evidence_clarity=abs(monitor.threat_score - monitor.safety_score),
            contradiction=min(monitor.threat_score, monitor.safety_score),
            urgency=monitor.turn * 0.08,
            tool_count=monitor.total_tools,
            max_tools=monitor.max_tools,
            novelty=monitor.novelty_at_start,
            shadow_state=monitor.state.value,
            correction_seen="correction" in monitor.evidence_tags,
        )

        # Memory
        result = monitor.memory.lookup(monitor.alert_text, monitor.evidence_vector)
        if result:
            store_name, match = result
            if store_name == "tolerance":
                snap.memory_outcome = "benign"
            elif store_name == "threat":
                snap.memory_outcome = "escalate"
            else:
                snap.memory_outcome = "abstain"
            snap.memory_confidence = match.confidence
            snap.memory_exposures = match.exposures

        # Graph
        graph = monitor._receipt_graph
        if graph:
            snap.graph_reinforcements = sum(
                e.reinforcements for e in graph.edges if not e.is_cold
            )
            snap.graph_contradictions = sum(
                e.contradictions for e in graph.edges if not e.is_cold
            )
            snap.graph_cold_edges = sum(1 for e in graph.edges if e.is_cold)

        if graph_hud:
            snap.graph_dominant_outcome = graph_hud.get("dominant_outcome", "unknown")
            snap.graph_strength = graph_hud.get("memory_strength", "none")

        return snap

    # --- Reason builder -----------------------------------------------------

    def _build_reason(
        self,
        snap: GateSnapshot,
        action_name: str,
        Q: List[List[float]],
        idx: int,
    ) -> str:
        """Human-readable reason from QUBO terms."""
        parts = [f"qubo_selected={action_name}"]
        parts.append(f"obj={Q[idx][idx]:.2f}")
        parts.append(f"t={snap.threat_score:.2f}")
        parts.append(f"s={snap.safety_score:.2f}")

        if snap.graph_strength != "none":
            parts.append(f"graph={snap.graph_dominant_outcome}({snap.graph_strength})")
        if snap.memory_outcome != "unknown":
            parts.append(f"mem={snap.memory_outcome}({snap.memory_confidence:.2f})")
        if snap.correction_seen:
            parts.append("correction_seen")

        return " | ".join(parts)
