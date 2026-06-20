"""
MorphSAT v7 Shadow Horizon Monitor — anticipatory metacognitive control.

The v6 negative result showed that novelty-as-scalar-penalty is wrong.
v7 replaces it with novelty-as-reflex-state-transition.

Architecture:
    Layer 1: FSA — legal lifecycle skeleton
    Layer 2: Evidence sensors — bidirectional threat/safety classification
    Layer 3: Shadow Monitor — trajectory/novelty → reflex states
    Layer 4: Split Memory — threat + tolerance patterns
    Layer 5: Receipts — why the monitor changed posture

Shadow states (hidden from model, controls the loop):
    NORMAL         — ordinary evidence collection
    ORIENTING      — novelty/surprise detected; pause and assess
    SAFE_DISTANCE  — restrict irreversible action; gather cautiously
    INVESTIGATING  — bounded evidence collection (has a budget)
    COMMIT_READY   — enough signal to decide locally
    ABSTAIN_READY  — ambiguity persists after bounded investigation
    ESCALATE_READY — danger exceeds local capacity
    SWARM_CALL     — multi-axis pressure; needs external perspectives

Biological mapping:
    surprise → orient          (defensive cascade: PMC4495877)
    safe evidence → normalize  (immune tolerance)
    threat confirmed → escalate (inflammation)
    ambiguity persists → abstain (uncertainty = defer)
    pressure from all sides → swarm (cytokine recruitment)

The key v7 rule:
    NOT: threshold = base * novelty_penalty
    YES: if novel → enter ORIENT state → bounded investigation → decide

Literature:
    - Jones/Laird: Anticipatory thinking via event cognition (CEUR-WS 2019)
    - Defensive cascades: arousal→orient→active defense (PMC4495877)
    - Active inference: surprise as control signal (ScienceDirect)
    - Overthinking exit: stop when reasoning complete (arXiv 2508.17627)

Lineage: v4 PressureGate → v5 PatternMemory → v6 CommitGate (NEGATIVE)
         → v7 ShadowMonitor (novelty = reflex, not penalty)
"""

import enum
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from morphsat.commit_gate import (
    SplitMemoryStore,
    CommitAction,
    classify_tool_result,
    coincidence_check,
    se_classify_complexity,
    sidecar_confidence,
)


# ---------------------------------------------------------------------------
# Shadow States
# ---------------------------------------------------------------------------

class ShadowState(enum.Enum):
    """Hidden posture states — the agent doesn't see these directly.

    The shadow monitor controls the loop AROUND the model.
    These states change what the agent is ALLOWED to do.
    """
    NORMAL = "normal"
    ORIENTING = "orienting"
    SAFE_DISTANCE = "safe_distance"
    INVESTIGATING = "investigating"
    COMMIT_READY = "commit_ready"
    ABSTAIN_READY = "abstain_ready"
    ESCALATE_READY = "escalate_ready"
    SWARM_CALL = "swarm_call"


@dataclass
class PostureTrace:
    """One posture change record for the receipt."""
    turn: int
    from_state: str
    to_state: str
    trigger: str
    metrics: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Shadow Horizon Monitor
# ---------------------------------------------------------------------------

class ShadowMonitor:
    """v7 Shadow Horizon Monitor — anticipatory metacognitive control.

    The monitor watches the agent's trajectory in evidence space and
    controls posture (not threshold). Novelty triggers state transitions,
    not scalar penalties.

    The key insight from v6 failure: don't make novel = harder to commit.
    Make novel = protective orienting response with bounded investigation.

    Cold-start rule:
        novel → ORIENT → limited probe → decide posture
        NOT: novel → raise threshold → investigate forever

    Swarm rule:
        multi-axis pressure → SWARM_CALL → recruit help
        NOT: confusion → keep looping alone
    """

    def __init__(self,
                 # Investigation budgets
                 orient_budget: int = 1,
                 investigate_budget: int = 3,
                 max_tools: int = 8,

                 # Commit thresholds (clarity-based, not pressure-penalty)
                 commit_clarity: float = 0.35,
                 escalate_threat: float = 0.55,
                 safety_clear: float = 0.45,
                 contradiction_gate: float = 0.30,

                 # Surprise detection
                 surprise_spike: float = 0.25,

                 # Orient decay
                 orient_decay_per_safe: float = 0.20,

                 # Swarm trigger
                 swarm_axes_required: int = 3,

                 # Evidence decay (leaky accumulator)
                 evidence_decay: float = 1.0,

                 # v9 correction pathway toggle
                 enable_correction: bool = True,

                 # Dual-boundary (uncertainty-preserving) mode
                 enable_dual_boundary: bool = False,
                 commit_threat_boundary: float = 0.55,
                 commit_safe_boundary: float = 0.40,

                 # Memory
                 memory: Optional[SplitMemoryStore] = None,

                 # Layer 1+2: receipt chain and receipt graph
                 receipt_chain=None,    # ReceiptChain or None
                 receipt_graph=None):   # ReceiptGraph or None

        # --- State ---
        self.state = ShadowState.NORMAL
        self.previous_state = ShadowState.NORMAL

        # --- Budgets ---
        self.orient_budget = orient_budget
        self.investigate_budget = investigate_budget
        self.max_tools = max_tools
        self.orient_tools_used = 0
        self.investigate_tools_used = 0
        self.total_tools = 0

        # --- Evidence (bidirectional) ---
        self.threat_score = 0.0
        self.safety_score = 0.0
        self.evidence_tags: List[str] = []
        self.evidence_vector: List[Tuple[str, str]] = []
        self.turn = 0
        self.evidence_decay = evidence_decay
        self.enable_correction = enable_correction
        self.enable_dual_boundary = enable_dual_boundary
        self.commit_threat_boundary = commit_threat_boundary
        self.commit_safe_boundary = commit_safe_boundary
        self.total_threat_decayed = 0.0
        self.total_safety_decayed = 0.0
        self.time_in_continue_zone = 0
        self.boundary_crossed = None  # "threat", "safe", or None
        self.abstain_due_to_uncertainty = False

        # --- Thresholds ---
        self.commit_clarity = commit_clarity
        self.escalate_threat = escalate_threat
        self.safety_clear = safety_clear
        self.contradiction_gate = contradiction_gate
        self.surprise_spike = surprise_spike
        self.orient_decay_per_safe = orient_decay_per_safe
        self.swarm_axes_required = swarm_axes_required

        # --- Trajectory tracking ---
        self.threat_deltas: List[float] = []
        self.safety_deltas: List[float] = []
        self.repeated_categories: Dict[str, int] = {}
        self.novelty_at_start = 1.0
        self.orient_pressure = 0.0

        # --- Memory ---
        self.memory = memory or SplitMemoryStore("/tmp/shadow_monitor_memory.json")
        self.alert_text = ""
        self.committed = False
        self.last_action = CommitAction("CONTINUE")
        self.terrain = "uncharted"  # cached terrain label from initialize()

        # --- Receipt chain + graph (Layers 1+2) ---
        self._receipt_chain = receipt_chain
        self._receipt_graph = receipt_graph

        # --- Receipt ---
        self.posture_trace: List[PostureTrace] = []
        self.history: List[dict] = []

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self, alert_text: str, complexity: str = ""):
        """Start of episode. Assess novelty → set initial posture.

        Known pattern → NORMAL (sensitized, lower commit threshold)
        Novel pattern → ORIENTING (protective reflex)
        Moderate      → NORMAL (baseline)
        """
        self.alert_text = alert_text

        if not complexity:
            complexity = se_classify_complexity(alert_text)

        # Check memory for known patterns
        novelty_dist = self.memory.novelty_distance(alert_text)
        self.novelty_at_start = novelty_dist

        result = self.memory.lookup(alert_text, [])

        if result:
            store_name, match = result
            if match.exposures >= 2 and match.confidence >= 0.7:
                # Known pattern — NORMAL, with sensitized thresholds
                self.state = ShadowState.NORMAL
                self.commit_clarity *= (1.0 - 0.2 * match.confidence)
                self._trace("initialize", ShadowState.NORMAL,
                            f"known_{store_name} (conf={match.confidence:.2f})")
                # Terrain: strong match — classify by store
                if store_name == "tolerance":
                    self.terrain = "familiar"
                elif store_name == "threat":
                    self.terrain = "flagged"
                else:  # abstain
                    self.terrain = "unstable"
            else:
                self.state = ShadowState.NORMAL
                self._trace("initialize", ShadowState.NORMAL,
                            f"partial_match_{store_name}")
                self.terrain = "recognized"
        elif novelty_dist > 0.8:
            # Highly novel — ORIENT (protective reflex, NOT penalty)
            self.state = ShadowState.ORIENTING
            self.orient_pressure = novelty_dist
            self._trace("initialize", ShadowState.ORIENTING,
                        f"novel (dist={novelty_dist:.2f})")
            self.terrain = "uncharted"
        else:
            self.state = ShadowState.NORMAL
            self._trace("initialize", ShadowState.NORMAL,
                        f"moderate_novelty (dist={novelty_dist:.2f})")
            self.terrain = "uncharted"

        # Graph prediction: prime the graph before the episode
        if self._receipt_graph is not None:
            tags = [self.terrain, self.state.value]
            if alert_text:
                tags.append(alert_text[:50])
            self._receipt_graph.predict(tags=tags, domain=self.terrain)

    # ------------------------------------------------------------------
    # Main evidence processing
    # ------------------------------------------------------------------

    def process_evidence(self, tool_name: str, tool_result: str,
                         model_output: str = "") -> CommitAction:
        """Process one tool result. Returns action for the agent.

        1. Classify evidence (bidirectional)
        2. Update scores
        3. Evaluate state transitions
        4. Return action based on current posture
        """
        if self.committed:
            return CommitAction("COMMITTED", self.last_action.direction,
                                "already committed")

        self.total_tools += 1
        self.turn += 1

        # --- 1. Classify evidence ---
        category, threat_delta, safety_delta = classify_tool_result(tool_result)
        self.evidence_vector.append((tool_name, category))
        self.evidence_tags.append(category)

        # Track repeats (loop detection)
        self.repeated_categories[category] = \
            self.repeated_categories.get(category, 0) + 1

        # Sidecar
        t_conf, s_conf = 0.0, 0.0
        if model_output:
            t_conf, s_conf = sidecar_confidence(model_output)

        # Coincidence (supralinear multi-signal)
        t_coin, s_coin = 0.0, 0.0
        if len(self.evidence_tags) >= 2:
            t_coin, s_coin = coincidence_check(self.evidence_tags)

        # --- 1b. Leaky accumulator: decay prior evidence ---
        # Before adding new evidence, decay accumulated scores so early
        # signals lose weight over time. This prevents false early signals
        # from permanently dominating the accumulator. Biological analogy:
        # cytokine half-life — immune signals degrade naturally.
        if self.evidence_decay < 1.0 and self.turn > 1:
            pre_threat = self.threat_score
            pre_safety = self.safety_score
            self.threat_score *= self.evidence_decay
            self.safety_score *= self.evidence_decay
            self.total_threat_decayed += (pre_threat - self.threat_score)
            self.total_safety_decayed += (pre_safety - self.safety_score)

        # --- 2. Update scores ---
        total_threat = threat_delta + t_conf + t_coin
        total_safety = safety_delta + s_conf + s_coin

        # v9 correction pathway: when evidence explicitly corrects a
        # prior signal, DECAY the opposite score. Without this, false
        # threat signals permanently accumulate with no reversal path.
        # Biological analogy: anti-inflammatory response inhibits the
        # accumulated inflammation, not just adds safety.
        if self.enable_correction and category == "correction":
            # Strong safety-only signal: decay accumulated threat
            decay = min(self.threat_score, 0.30)
            self.threat_score = max(0.0, self.threat_score - decay)
            total_threat = -decay  # record as negative delta for receipt
        elif self.enable_correction and category == "negated_threat":
            # Weaker: evidence that negates threat keywords
            decay = min(self.threat_score, 0.15)
            self.threat_score = max(0.0, self.threat_score - decay)
            total_threat = -decay
        else:
            self.threat_score += total_threat

        self.safety_score += total_safety
        self.threat_deltas.append(total_threat)
        self.safety_deltas.append(total_safety)

        # --- 3. Compute trajectory metrics ---
        evidence_clarity = abs(self.threat_score - self.safety_score)
        evidence_balance = self.threat_score - self.safety_score
        contradiction = min(self.threat_score, self.safety_score)
        is_looping = self._detect_loop()
        no_new_info = self._no_new_evidence()

        # Track dual-boundary zone occupancy
        if self.enable_dual_boundary:
            if evidence_balance < self.commit_threat_boundary and \
               evidence_balance > -self.commit_safe_boundary:
                self.time_in_continue_zone += 1

        # --- 4. State transitions ---
        action = self._transition(
            evidence_clarity=evidence_clarity,
            contradiction=contradiction,
            threat_delta=total_threat,
            safety_delta=total_safety,
            is_looping=is_looping,
            no_new_info=no_new_info,
            evidence_balance=evidence_balance,
        )

        # --- 5. Record history ---
        self.history.append({
            "turn": self.turn,
            "tool": tool_name,
            "category": category,
            "shadow_state": self.state.value,
            "threat_score": round(self.threat_score, 3),
            "safety_score": round(self.safety_score, 3),
            "threat_delta": round(total_threat, 3),
            "safety_delta": round(total_safety, 3),
            "evidence_clarity": round(evidence_clarity, 3),
            "contradiction": round(contradiction, 3),
            "is_looping": is_looping,
            "no_new_info": no_new_info,
            "orient_pressure": round(self.orient_pressure, 3),
            "action": action.action,
            "direction": action.direction,
            "evidence_decay": self.evidence_decay,
            "cumulative_threat_decayed": round(self.total_threat_decayed, 3),
            "cumulative_safety_decayed": round(self.total_safety_decayed, 3),
            "evidence_balance": round(evidence_balance, 3),
            "dual_boundary": self.enable_dual_boundary,
            "dist_to_threat_boundary": round(self.commit_threat_boundary - evidence_balance, 3) if self.enable_dual_boundary else None,
            "dist_to_safe_boundary": round(self.commit_safe_boundary + evidence_balance, 3) if self.enable_dual_boundary else None,
            "time_in_continue_zone": self.time_in_continue_zone,
        })

        self.last_action = action
        if action.action in ("COMMIT", "ABSTAIN", "SWARM_CALL"):
            self.committed = True

        return action

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _transition(self, evidence_clarity: float, contradiction: float,
                    threat_delta: float, safety_delta: float,
                    is_looping: bool, no_new_info: bool,
                    evidence_balance: float = 0.0) -> CommitAction:
        """Shadow state machine transitions.

        This is the core v7 logic: posture changes based on conditions,
        not scalar threshold multiplication.
        """
        # Absolute ceiling — never exceed max tools
        if self.total_tools >= self.max_tools:
            return self._force_commit("max_tools_reached", evidence_balance)

        # Check swarm trigger (any state)
        if self._check_swarm_trigger(contradiction, is_looping):
            self.state = ShadowState.SWARM_CALL
            self._trace("swarm_trigger", ShadowState.SWARM_CALL,
                        f"multi-axis pressure")
            # For now, SWARM_CALL resolves as ABSTAIN (no real swarm yet)
            self.committed = True
            self.last_action = CommitAction(
                "ABSTAIN", reason="swarm_call: multi-axis pressure exceeds local capacity")
            return self.last_action

        if self.state == ShadowState.NORMAL:
            return self._from_normal(evidence_clarity, contradiction,
                                     threat_delta, safety_delta,
                                     is_looping, no_new_info,
                                     evidence_balance)

        elif self.state == ShadowState.ORIENTING:
            return self._from_orienting(evidence_clarity, contradiction,
                                        threat_delta, safety_delta,
                                        evidence_balance)

        elif self.state == ShadowState.SAFE_DISTANCE:
            return self._from_safe_distance(evidence_clarity, contradiction,
                                            threat_delta, safety_delta,
                                            evidence_balance)

        elif self.state == ShadowState.INVESTIGATING:
            return self._from_investigating(evidence_clarity, contradiction,
                                            is_looping, no_new_info,
                                            evidence_balance)

        # Terminal states — shouldn't arrive here
        return self._force_commit("terminal_state")

    def _from_normal(self, clarity, contradiction, t_delta, s_delta,
                     is_looping, no_new_info,
                     evidence_balance=0.0) -> CommitAction:
        """NORMAL: ordinary evidence collection.

        Transitions:
            surprise spike → ORIENTING
            clear evidence → COMMIT
            loop detected  → force commit
        """
        # Surprise: large unexpected threat on early turn
        if t_delta >= self.surprise_spike and self.turn <= 2:
            self.state = ShadowState.ORIENTING
            self.orient_pressure = t_delta
            self._trace("surprise_threat", ShadowState.ORIENTING,
                        f"t_delta={t_delta:.2f}")
            return CommitAction("CONTINUE", reason="orienting: surprise threat")

        # Enough clarity to commit
        if clarity >= self.commit_clarity:
            return self._resolve_direction(clarity, contradiction,
                                           "normal_clarity",
                                           evidence_balance)

        # Loop or stagnation → commit with what we have
        if is_looping or no_new_info:
            return self._force_commit("loop_in_normal", evidence_balance)

        return CommitAction("CONTINUE", reason="normal: gathering evidence")

    def _from_orienting(self, clarity, contradiction,
                        t_delta, s_delta,
                        evidence_balance=0.0) -> CommitAction:
        """ORIENTING: something surprised me, pause and assess.

        The protective reflex. Allow limited probing, then decide posture.
        Safe evidence DECAYS orient pressure (tolerance response).

        Transitions:
            safe evidence → orient pressure decays → NORMAL
            clear threat  → ESCALATE_READY
            budget spent  → SAFE_DISTANCE (if threat-leaning) or INVESTIGATING
        """
        self.orient_tools_used += 1

        # Safe evidence decays orient pressure (tolerance)
        if s_delta > 0:
            self.orient_pressure = max(
                0, self.orient_pressure - self.orient_decay_per_safe)

        # Orient pressure dissolved → back to normal
        if self.orient_pressure <= 0:
            self.state = ShadowState.NORMAL
            self._trace("orient_resolved", ShadowState.NORMAL,
                        "safe evidence dissolved surprise")
            return CommitAction("CONTINUE", reason="orient resolved → normal")

        # Immediate clear threat while orienting — use boundary in dual mode
        threat_threshold = self.commit_threat_boundary if self.enable_dual_boundary \
            else self.escalate_threat
        if evidence_balance >= threat_threshold:
            self.state = ShadowState.ESCALATE_READY
            self.boundary_crossed = "threat"
            self._trace("orient_to_escalate", ShadowState.ESCALATE_READY,
                        f"balance={evidence_balance:.2f} >= boundary={threat_threshold:.2f}")
            return CommitAction("COMMIT", direction="escalate",
                                reason="orienting: clear threat")

        # Orient budget spent → choose next posture
        if self.orient_tools_used >= self.orient_budget:
            if self.threat_score > self.safety_score:
                self.state = ShadowState.SAFE_DISTANCE
                self._trace("orient_to_safe_dist", ShadowState.SAFE_DISTANCE,
                            "threat > safety after orient")
            else:
                self.state = ShadowState.INVESTIGATING
                self._trace("orient_to_investigate", ShadowState.INVESTIGATING,
                            "no clear threat after orient")
            return CommitAction("CONTINUE",
                                reason=f"orient → {self.state.value}")

        return CommitAction("CONTINUE", reason="orienting: assessing")

    def _from_safe_distance(self, clarity, contradiction,
                            t_delta, s_delta,
                            evidence_balance=0.0) -> CommitAction:
        """SAFE_DISTANCE: I see potential threat, gathering cautiously.

        Biased toward escalate/abstain. Strong safety evidence needed to
        normalize. This is the "get distance from danger" posture.

        Transitions:
            threat confirmed → ESCALATE_READY
            strong safety + low threat → NORMAL (normalize)
            contradiction → ABSTAIN_READY
            budget exhausted → force commit (or ABSTAIN in dual-boundary mode)
        """
        self.investigate_tools_used += 1

        # In dual-boundary mode, use evidence_balance against boundaries
        if self.enable_dual_boundary:
            # Threat boundary crossed → escalate
            if evidence_balance >= self.commit_threat_boundary:
                self.state = ShadowState.ESCALATE_READY
                self.boundary_crossed = "threat"
                self._trace("safe_dist_escalate", ShadowState.ESCALATE_READY,
                            f"balance={evidence_balance:.2f} >= "
                            f"threat_boundary={self.commit_threat_boundary:.2f}")
                return CommitAction("COMMIT", direction="escalate",
                                    reason="safe_distance: threat boundary crossed")

            # Safe boundary crossed → normalize and commit benign
            if evidence_balance <= -self.commit_safe_boundary:
                self.state = ShadowState.COMMIT_READY
                self.boundary_crossed = "safe"
                self._trace("safe_dist_commit_safe", ShadowState.COMMIT_READY,
                            f"balance={evidence_balance:.2f} <= "
                            f"-safe_boundary={-self.commit_safe_boundary:.2f}")
                return CommitAction("COMMIT", direction="benign",
                                    reason="safe_distance: safe boundary crossed")
        else:
            # Original logic: clear threat → escalate
            if self.threat_score >= self.escalate_threat:
                self.state = ShadowState.ESCALATE_READY
                self._trace("safe_dist_escalate", ShadowState.ESCALATE_READY,
                            f"threat={self.threat_score:.2f}")
                return CommitAction("COMMIT", direction="escalate",
                                    reason="safe_distance: threat confirmed")

        # Strong safety + low threat → normalize (both modes)
        if self.safety_score >= self.safety_clear and self.threat_score < 0.15:
            self.state = ShadowState.NORMAL
            self._trace("safe_dist_normalize", ShadowState.NORMAL,
                        f"safety={self.safety_score:.2f}")
            if clarity >= self.commit_clarity:
                return self._resolve_direction(clarity, contradiction,
                                               "normalized_then_commit",
                                               evidence_balance)
            return CommitAction("CONTINUE",
                                reason="safe_distance → normal: safety evidence")

        # Contradiction → abstain (both modes)
        if contradiction >= self.contradiction_gate:
            self.state = ShadowState.ABSTAIN_READY
            self._trace("safe_dist_abstain", ShadowState.ABSTAIN_READY,
                        f"contradiction={contradiction:.2f}")
            return CommitAction(
                "ABSTAIN",
                reason=f"safe_distance: contradictory "
                       f"(t={self.threat_score:.2f}, s={self.safety_score:.2f})")

        # Budget exhausted
        if self.investigate_tools_used >= self.investigate_budget:
            return self._force_commit("safe_distance_budget", evidence_balance)

        return CommitAction("CONTINUE",
                            reason="safe_distance: gathering cautiously")

    def _from_investigating(self, clarity, contradiction,
                            is_looping, no_new_info,
                            evidence_balance=0.0) -> CommitAction:
        """INVESTIGATING: bounded evidence collection.

        Normal-posture investigation with a budget. The agent is not
        under threat, just needs more information.

        Transitions:
            clarity reached → COMMIT
            contradiction → ABSTAIN
            loop/stagnation → force commit
            budget exhausted → force commit (or ABSTAIN in dual-boundary mode)
        """
        self.investigate_tools_used += 1

        # Enough clarity
        if clarity >= self.commit_clarity:
            return self._resolve_direction(clarity, contradiction,
                                           "investigate_clarity",
                                           evidence_balance)

        # Contradiction
        if contradiction >= self.contradiction_gate:
            self.state = ShadowState.ABSTAIN_READY
            self._trace("investigate_abstain", ShadowState.ABSTAIN_READY,
                        f"contradiction={contradiction:.2f}")
            return CommitAction("ABSTAIN",
                                reason="investigating: contradictory")

        # Loop or stagnation
        if is_looping or no_new_info:
            return self._force_commit("investigate_no_progress",
                                      evidence_balance)

        # Budget
        if self.investigate_tools_used >= self.investigate_budget:
            return self._force_commit("investigate_budget", evidence_balance)

        return CommitAction("CONTINUE",
                            reason="investigating: bounded collection")

    # ------------------------------------------------------------------
    # Resolution helpers
    # ------------------------------------------------------------------

    def _resolve_direction(self, clarity, contradiction,
                           trigger: str,
                           evidence_balance: float = 0.0) -> CommitAction:
        """Determine commit direction from accumulated evidence.

        In dual-boundary mode, only commits if evidence_balance has crossed
        one of the two boundaries. If still in the continue zone, returns
        CONTINUE — the system preserves uncertainty.
        """
        # Contradiction overrides both boundaries
        if contradiction >= self.contradiction_gate:
            self.state = ShadowState.ABSTAIN_READY
            self._trace(trigger, ShadowState.ABSTAIN_READY,
                        f"contradiction={contradiction:.2f}")
            return CommitAction("ABSTAIN",
                                reason=f"{trigger}: contradictory")

        if self.enable_dual_boundary:
            # Dual-boundary: only commit if a boundary is crossed
            if evidence_balance >= self.commit_threat_boundary:
                # Threat boundary crossed
                self.boundary_crossed = "threat"
                if evidence_balance >= self.escalate_threat or \
                   evidence_balance > 0.4:
                    direction = "escalate"
                    self.state = ShadowState.ESCALATE_READY
                else:
                    direction = "suspicious"
                    self.state = ShadowState.COMMIT_READY
                self._trace(trigger, self.state,
                            f"balance={evidence_balance:.2f} >= "
                            f"threat_boundary={self.commit_threat_boundary:.2f}")
                return CommitAction(
                    "COMMIT", direction=direction,
                    reason=f"{trigger}: threat boundary crossed "
                           f"(bal={evidence_balance:.2f})")

            elif evidence_balance <= -self.commit_safe_boundary:
                # Safe boundary crossed
                self.boundary_crossed = "safe"
                self.state = ShadowState.COMMIT_READY
                self._trace(trigger, self.state,
                            f"balance={evidence_balance:.2f} <= "
                            f"-safe_boundary={-self.commit_safe_boundary:.2f}")
                return CommitAction(
                    "COMMIT", direction="benign",
                    reason=f"{trigger}: safe boundary crossed "
                           f"(bal={evidence_balance:.2f})")
            else:
                # CONTINUE ZONE — uncertainty preserved
                return CommitAction(
                    "CONTINUE",
                    reason=f"{trigger}: in continue zone "
                           f"(bal={evidence_balance:.2f}, "
                           f"zone=[{-self.commit_safe_boundary:.2f}, "
                           f"{self.commit_threat_boundary:.2f}])")

        # Original single-boundary logic
        if self.threat_score > self.safety_score:
            margin = self.threat_score - self.safety_score
            if margin > 0.4 or self.threat_score >= self.escalate_threat:
                direction = "escalate"
                self.state = ShadowState.ESCALATE_READY
            else:
                direction = "suspicious"
                self.state = ShadowState.COMMIT_READY
        else:
            direction = "benign"
            self.state = ShadowState.COMMIT_READY

        self._trace(trigger, self.state,
                    f"t={self.threat_score:.2f}, s={self.safety_score:.2f}")
        return CommitAction(
            "COMMIT", direction=direction,
            reason=f"{trigger} (t={self.threat_score:.2f}, "
                   f"s={self.safety_score:.2f})")

    def _force_commit(self, reason: str,
                      evidence_balance: float = 0.0) -> CommitAction:
        """Forced commit — budget exhausted, loop, or max tools.

        In dual-boundary mode: if evidence_balance is still inside the
        continue zone, ABSTAIN instead of inventing a verdict. The whole
        point of uncertainty-preserving boundaries is that budget exhaustion
        does not manufacture confidence.
        """
        contradiction = min(self.threat_score, self.safety_score)

        if contradiction >= self.contradiction_gate:
            action = CommitAction("ABSTAIN",
                                  reason=f"forced:{reason} contradictory")
            self.state = ShadowState.ABSTAIN_READY

        elif self.enable_dual_boundary:
            # Dual-boundary: only commit if a boundary was crossed
            if evidence_balance >= self.commit_threat_boundary:
                self.boundary_crossed = "threat"
                if evidence_balance > 0.4 or \
                   evidence_balance >= self.escalate_threat:
                    direction = "escalate"
                    self.state = ShadowState.ESCALATE_READY
                else:
                    direction = "suspicious"
                    self.state = ShadowState.COMMIT_READY
                action = CommitAction("COMMIT", direction=direction,
                                      reason=f"forced:{reason} "
                                             f"(threat boundary crossed)")
            elif evidence_balance <= -self.commit_safe_boundary:
                self.boundary_crossed = "safe"
                self.state = ShadowState.COMMIT_READY
                action = CommitAction("COMMIT", direction="benign",
                                      reason=f"forced:{reason} "
                                             f"(safe boundary crossed)")
            else:
                # INSIDE CONTINUE ZONE — do not invent confidence
                self.abstain_due_to_uncertainty = True
                self.state = ShadowState.ABSTAIN_READY
                action = CommitAction(
                    "ABSTAIN",
                    reason=f"forced:{reason} insufficient_evidence "
                           f"(bal={evidence_balance:.2f} in zone "
                           f"[{-self.commit_safe_boundary:.2f}, "
                           f"{self.commit_threat_boundary:.2f}])")

        else:
            # Original single-boundary logic
            if self.threat_score > self.safety_score:
                margin = self.threat_score - self.safety_score
                if margin > 0.4 or self.threat_score >= self.escalate_threat:
                    direction = "escalate"
                    self.state = ShadowState.ESCALATE_READY
                else:
                    direction = "suspicious"
                    self.state = ShadowState.COMMIT_READY
                action = CommitAction("COMMIT", direction=direction,
                                      reason=f"forced:{reason}")
            elif self.safety_score > self.threat_score:
                action = CommitAction("COMMIT", direction="benign",
                                      reason=f"forced:{reason}")
                self.state = ShadowState.COMMIT_READY
            else:
                action = CommitAction("COMMIT", direction="suspicious",
                                      reason=f"forced:{reason} ambiguous")
                self.state = ShadowState.COMMIT_READY

        self._trace(reason, self.state, "forced")
        self.committed = True
        self.last_action = action
        return action

    # ------------------------------------------------------------------
    # Trajectory sensors
    # ------------------------------------------------------------------

    def _detect_loop(self) -> bool:
        """Same evidence category repeated 3+ times."""
        return any(count >= 3 for count in self.repeated_categories.values())

    def _no_new_evidence(self) -> bool:
        """Last 2 turns both had near-zero evidence deltas."""
        if len(self.threat_deltas) < 2:
            return False
        recent_t = self.threat_deltas[-2:]
        recent_s = self.safety_deltas[-2:]
        return (all(abs(d) < 0.06 for d in recent_t) and
                all(abs(d) < 0.06 for d in recent_s))

    def _check_swarm_trigger(self, contradiction: float,
                             is_looping: bool) -> bool:
        """Multi-axis pressure exceeds local capacity.

        Counts how many pressure axes are active. If >= threshold,
        the agent needs external help.

        Axes:
            1. High contradiction (both threat AND safety)
            2. High novelty at start
            3. Tool loop detected
            4. Investigation budget spent without resolution
            5. Both scores above minimum (ambiguous territory)
        """
        axes = 0
        if contradiction >= self.contradiction_gate:
            axes += 1
        if self.novelty_at_start > 0.7:
            axes += 1
        if is_looping:
            axes += 1
        if (self.investigate_tools_used >= self.investigate_budget
                and not self.committed):
            axes += 1
        if self.threat_score > 0.2 and self.safety_score > 0.2:
            axes += 1

        return axes >= self.swarm_axes_required

    # ------------------------------------------------------------------
    # Tracing and receipts
    # ------------------------------------------------------------------

    def _trace(self, trigger: str, to_state: ShadowState, detail: str):
        """Record a posture change for the receipt."""
        self.posture_trace.append(PostureTrace(
            turn=self.turn,
            from_state=self.previous_state.value,
            to_state=to_state.value,
            trigger=trigger,
            metrics={
                "threat": round(self.threat_score, 3),
                "safety": round(self.safety_score, 3),
                "orient_pressure": round(self.orient_pressure, 3),
                "total_tools": self.total_tools,
                "detail": detail,
            },
        ))
        self.previous_state = to_state

    def close_episode(self, final_resolution: str, confidence: float):
        """Post-episode: write to memory. Strange loop closure.

        With receipt chain and receipt graph enabled, this also:
        1. Appends the receipt to the chain (Layer 1 — fossil record)
        2. Projects it into the graph (Layer 2 — living memory)
        3. Scores the graph's prediction against actual outcome
        4. Runs decay on graph edges
        """
        if self.evidence_vector:
            self.memory.record_episode(
                evidence_signature=self.evidence_vector,
                resolution=final_resolution,
                confidence=confidence,
                alert_text=self.alert_text,
                threat_score=self.threat_score,
                safety_score=self.safety_score,
                turns=self.turn,
            )

        # Layer 1: receipt chain (immutable provenance spine)
        if self._receipt_chain is not None:
            receipt = self.to_receipt()
            receipt_hash = self._receipt_chain.append_receipt(receipt)
            block = self._receipt_chain.close_block()
            block_number = block.block_number if block else 0

            # Layer 2: receipt graph (living associative memory)
            if self._receipt_graph is not None:
                # Score previous prediction before adding new node
                actual_outcome = receipt.get("final_direction", "unknown")
                self._receipt_graph.score_prediction(actual_outcome)

                # Add new node and auto-connect
                self._receipt_graph.add_node(
                    receipt_hash, receipt, block_number)
                self._receipt_graph.auto_connect(receipt_hash)

                # Decay edges
                self._receipt_graph.decay_all(block_number)

    # ------------------------------------------------------------------
    # HUD — coarse navigation signal for the model
    # ------------------------------------------------------------------

    def render_hud(self) -> dict:
        """Render a coarse navigation HUD for the model.

        The model's weights are fixed during inference. It cannot grow
        new internal structure to track evidence dynamics. So we give
        it an instrument panel: enough signal to orient, not enough
        to game the governor.

        The HUD exposes:
            grid_position  — coarse location on the evidence grid (A1-C10)
            zone           — safe / continue / threat / committed / abstained
            compass        — which direction evidence is drifting
            clearance      — whether the model is cleared to commit
            allowed        — what actions are permitted
            blocked        — what actions are forbidden

        The HUD does NOT expose:
            raw threat_score / safety_score
            exact boundary distances
            decay rate or cumulative decay accounting
            posture state machine internals
            coincidence bonuses or novelty distances
        """
        # --- Grid position: map evidence_balance to coarse cell ---
        # A1-A3: safe side (balance < -safe_boundary)
        # B4-B7: continue zone (between boundaries)
        # C8-C10: threat side (balance > threat_boundary)
        balance = self.threat_score - self.safety_score

        if self.enable_dual_boundary:
            threat_b = self.commit_threat_boundary
            safe_b = self.commit_safe_boundary
        else:
            threat_b = self.escalate_threat
            safe_b = self.safety_clear

        if balance <= -safe_b:
            # Safe side: A1 (deep safe) to A3 (near safe boundary)
            depth = min(1.0, abs(balance + safe_b) / max(safe_b, 0.01))
            cell_num = max(1, 3 - int(depth * 2))
            grid_pos = f"A{cell_num}"
            zone = "safe"
        elif balance >= threat_b:
            # Threat side: C8 (near threat boundary) to C10 (deep threat)
            depth = min(1.0, (balance - threat_b) / max(threat_b, 0.01))
            cell_num = min(10, 8 + int(depth * 2))
            grid_pos = f"C{cell_num}"
            zone = "threat"
        else:
            # Continue zone: B4-B7
            zone_width = threat_b + safe_b
            if zone_width > 0:
                frac = (balance + safe_b) / zone_width
            else:
                frac = 0.5
            cell_num = 4 + int(frac * 3)
            cell_num = max(4, min(7, cell_num))
            grid_pos = f"B{cell_num}"
            zone = "continue"

        # Override zone for terminal states
        if self.committed:
            if self.last_action.action == "ABSTAIN":
                zone = "abstained"
            elif self.last_action.action == "COMMIT":
                zone = "committed"

        # --- Compass: drift direction from last 2 deltas ---
        compass = "steady"
        if len(self.threat_deltas) >= 2:
            recent_t = sum(self.threat_deltas[-2:])
            recent_s = sum(self.safety_deltas[-2:])
            net = recent_t - recent_s
            if net > 0.10:
                compass = "drifting threat-side"
            elif net < -0.10:
                compass = "drifting safe-side"
            elif abs(recent_t) < 0.05 and abs(recent_s) < 0.05:
                compass = "stalled"

        # --- Clearance ---
        if self.committed:
            clearance = "committed" if self.last_action.action == "COMMIT" \
                else "deferred"
        elif zone in ("safe", "threat"):
            clearance = "cleared"
        else:
            clearance = "not_cleared"

        # --- Allowed / blocked moves ---
        if self.committed:
            allowed = []
            blocked = ["all_actions"]
        elif clearance == "cleared":
            allowed = ["final_verdict"]
            blocked = ["gather_more_evidence"]
        else:
            allowed = [
                "gather_independent_confirmation",
                "check_for_correction",
                "request_additional_scan",
            ]
            blocked = [
                "final_verdict",
                "irreversible_action",
            ]

        hud = {
            "grid_position": grid_pos,
            "zone": zone,
            "compass": compass,
            "clearance": clearance,
            "terrain": self.terrain,
            "allowed": allowed,
            "blocked": blocked,
        }

        # Graph memory HUD: coarse summary from Layer 2
        if self._receipt_graph is not None:
            graph_hud = self._receipt_graph.export_memory_hud(
                tags=[self.terrain, self.state.value],
                domain=self.terrain,
            )
            hud["memory"] = graph_hud

        return hud

    def to_receipt(self) -> dict:
        """Full receipt — proof of shadow monitor behavior."""
        return {
            "gate_version": "v7_shadow_monitor",
            "initial_novelty": round(self.novelty_at_start, 3),
            "initial_state": (self.posture_trace[0].to_state
                              if self.posture_trace else "unknown"),
            "final_state": self.state.value,
            "threat_score": round(self.threat_score, 3),
            "safety_score": round(self.safety_score, 3),
            "contradiction": round(
                min(self.threat_score, self.safety_score), 3),
            "committed": self.committed,
            "final_action": self.last_action.action,
            "final_direction": self.last_action.direction,
            "final_reason": self.last_action.reason,
            "turns": self.turn,
            "total_tools": self.total_tools,
            "orient_tools": self.orient_tools_used,
            "investigate_tools": self.investigate_tools_used,
            "posture_transitions": len(self.posture_trace),
            "evidence_vector": self.evidence_vector,
            "posture_trace": [
                {
                    "turn": t.turn,
                    "from": t.from_state,
                    "to": t.to_state,
                    "trigger": t.trigger,
                    **t.metrics,
                }
                for t in self.posture_trace
            ],
            "history": self.history,
            "memory_state": self.memory.to_receipt(),
        }
