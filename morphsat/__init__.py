"""
MorphSAT -- Constraint-control testbed for local LLM agents.

Public API:
    MorphSATGate       Hard FSA enforcement gate with optional guardian vows.
    CandidateTransition  Ranked alternative when a transition is blocked.
    TaskState          Enum of lifecycle states (IDLE, PLANNING, WRITING, TESTING, DONE).
    TaskEvent          Enum of lifecycle events (NEW_TASK, PLAN_COMPLETE, ...).
    classify_event     Grounding layer: map text output + role to TaskEvent.
    MorphSATScorer     Token adjacency scorer with lane-based soft constraints.
    score_token_sequence  Score a complete token sequence in one call.
    load_morph_table   Load a morph table from JSON.
    create_default_morph_table  Create the default 4-lane adjacency table.
    wrap_receipt       Wrap a payload dict into a timestamped receipt.
"""

__version__ = "0.4.0"

from morphsat.core import (
    MorphSATGate,
    CandidateTransition,
    TaskState,
    TaskEvent,
    classify_event,
    TRANSITION_TABLE,
    GUARDIAN_BLOCKED,
    STATE_NAMES,
    EVENT_NAMES,
)

from morphsat.token import (
    MorphSATScorer,
    score_token_sequence,
    load_morph_table,
    create_default_morph_table,
    DEFAULT_LANE_ADJACENCY,
    LANE_NAMES,
)

from morphsat.commit_gate import (
    CommitGate,
    CommitAction,
    SplitMemoryStore,
)

from morphsat.shadow_monitor import (
    ShadowMonitor,
    ShadowState,
)

from morphsat.receipt import wrap_receipt

__all__ = [
    # core
    "MorphSATGate",
    "CandidateTransition",
    "TaskState",
    "TaskEvent",
    "classify_event",
    "TRANSITION_TABLE",
    "GUARDIAN_BLOCKED",
    "STATE_NAMES",
    "EVENT_NAMES",
    # token
    "MorphSATScorer",
    "score_token_sequence",
    "load_morph_table",
    "create_default_morph_table",
    "DEFAULT_LANE_ADJACENCY",
    "LANE_NAMES",
    # commit gate v6
    "CommitGate",
    "CommitAction",
    "SplitMemoryStore",
    # shadow monitor v7
    "ShadowMonitor",
    "ShadowState",
    # receipt
    "wrap_receipt",
]
