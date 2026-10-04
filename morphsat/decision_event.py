"""
DecisionEvent — canonical, observational record of one decision episode.
=========================================================================

P1 instrumentation (Phase 2.5). This module is OBSERVATIONAL ONLY:
nothing in the decision path (ShadowMonitor, TwoStageGate, GateQUBO,
CorrectionEcho, memory/graph stores) imports or reads it. Events are built
after an episode has fully resolved and its stores have been written.

Semantics (faithful to public GitHub state 14689b7, not repaired):

    monitor_*   — what ShadowMonitor proposed. PROVENANCE, not the outcome.
                  monitor_terminal is the existing ``committed`` latch, which
                  is set for COMMIT, ABSTAIN and SWARM_CALL alike.
    route_*     — TwoStageGate routing (backend + reason), if a gate ran.
    backend     — threshold / QUBO results, if a gate ran.
    echo_*      — CorrectionEcho match, injection and contradiction counts.
    final_*     — what the system actually EMITTED. The canonical
                  behavioral outcome; the only answer to "what did I do".
    stores      — what each store recorded. These currently DISAGREE when an
                  override happens (SplitMemory: emitted verdict;
                  ReceiptGraph: monitor direction). Preserved, not flattened.
    evaluation  — benchmark-only ground-truth comparisons.
    e10_*       — observables preregistered as behaviorally dead.

Canonical hash: SHA256 over canonical JSON of the semantic payload.
No timestamps, PIDs, hostnames or file paths are part of the payload.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from morphsat.receipt_chain import canonical_hash

SCHEMA_VERSION = "decision_event_v1"

# Preregistered negative-control observables (Phase 2.5, F/E10).
# Computed by graph_routing_signal; expected to have NO behavioral consumer.
E10_OBSERVABLES = (
    "drift_like",
    "stale_memory_like",
    "poisoned_memory_like",
    "sensor_graph_conflict",
    "routing_triggered",
)

SEVERITY = {"benign": 0, "suspicious": 1, "escalate": 2}

FLOAT_DIGITS = 4


def _norm(obj: Any) -> Any:
    """Normalize a value for deterministic hashing (round floats, tuples→lists)."""
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, float):
        return round(obj, FLOAT_DIGITS)
    if isinstance(obj, dict):
        return {str(k): _norm(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_norm(v) for v in obj]
    return obj


def severity_change(monitor_direction: Optional[str],
                    final_direction: Optional[str]) -> str:
    """'up' / 'down' / 'none' / 'n/a' on the ordinal benign<suspicious<escalate."""
    a = SEVERITY.get(monitor_direction or "")
    b = SEVERITY.get(final_direction or "")
    if a is None or b is None:
        return "n/a"
    return "up" if b > a else "down" if b < a else "none"


@dataclass
class DecisionEvent:
    """One episode's full causal decision chain. See module docstring."""
    episode_id: str
    mode: str
    family: str
    episode_index: int
    scenario_id: str
    evidence_signature: List[List[str]]

    # --- Stage 1: monitor proposal (provenance) ---
    monitor_action: str
    monitor_direction: Optional[str]
    monitor_terminal: bool                 # existing `committed` latch
    monitor_forced_at_bench_end: bool
    posture_initial: str
    posture_final: str
    posture_transitions: List[List[str]]   # [from, to, trigger]
    monitor_abstain_due_to_uncertainty: bool
    monitor_boundary_crossed: Optional[str]
    threat_score: float
    safety_score: float
    contradiction: float

    # --- Stage 2: routing ---
    route_backend: Optional[str] = None
    route_reason: Optional[str] = None
    routing_scores: Dict[str, float] = field(default_factory=dict)
    history_refs: Dict[str, Any] = field(default_factory=dict)
    graph_prediction: Optional[Dict[str, Any]] = None  # recorded only (E8 inert)

    # --- Stage 3: backend ---
    threshold_result: Optional[Dict[str, Any]] = None
    qubo_result: Optional[Dict[str, Any]] = None

    # --- Stage 4: CorrectionEcho ---
    echo_enabled: bool = False
    echo_match: bool = False
    echo_outcome: Optional[str] = None
    echo_contradiction_count_pre: Optional[int] = None
    echo_contradiction_count_post: Optional[int] = None
    echo_injected_memory: bool = False

    # --- Stage 5: canonical emitted outcome ---
    override_source: str = "none"          # none | gate_qubo | two_stage_qubo | echo_tiebreak
    final_action: str = ""
    final_direction: Optional[str] = None
    final_direction_defaulted: bool = False  # bench substitutes "suspicious" for None
    final_changed_from_monitor: bool = False
    final_action_direction_incoherent: bool = False  # ended on CONTINUE, or non-COMMIT with a non-default direction
    severity_change: str = "n/a"

    # --- What each store recorded (discrepancies preserved) ---
    stores: Dict[str, Any] = field(default_factory=dict)

    # --- Benchmark-only evaluation ---
    evaluation: Dict[str, Any] = field(default_factory=dict)

    # --- Preregistered dead observables (E10) ---
    e10_observed: Optional[Dict[str, bool]] = None
    e10_expected_dead: bool = True

    # --- Integrity ---
    monitor_receipt_hash: Optional[str] = None
    receipt_block: Optional[int] = None
    schema_version: str = SCHEMA_VERSION

    def payload(self) -> Dict[str, Any]:
        """Semantic payload used for the canonical hash."""
        return _norm(asdict(self))

    @property
    def event_hash(self) -> str:
        return canonical_hash(self.payload())

    def to_dict(self) -> Dict[str, Any]:
        d = self.payload()
        d["event_hash"] = self.event_hash
        return d


def events_digest(events: List[DecisionEvent]) -> str:
    """Order-sensitive digest over a sequence of event hashes."""
    return canonical_hash([e.event_hash for e in events])
