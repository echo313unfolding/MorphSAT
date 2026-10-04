"""
Canonical self-history projection (P2C).
=========================================

Every persistent history store must be a projection of ONE canonical
decision outcome. Stores may keep different projections but may not
disagree about the emitted outcome, and may not invent one.

Canonical outcome core (built before any store is written):

    episode_id, final_action, final_direction, monitor_action,
    monitor_direction, posture_final, override_source,
    attempted_override_source, override_blocked_by_terminal

outcome_ref = canonical_hash(core). Every store write carries outcome_ref.

Projections:

    final_action / posture        SplitMemory store      ReceiptGraph outcome
    ---------------------------   --------------------   --------------------
    COMMIT benign                 tolerance ("benign")   "benign"
    COMMIT suspicious|escalate    threat (same label)    same label
    ABSTAIN                       abstain ("abstain")    "abstain"
    ABSTAIN via SWARM_CALL        no verdict memory      "handoff"
    CONTINUE / other              no verdict memory      "unknown"

Uncertainty ("abstain"), handoff and "unknown" are NON-DIRECTIONAL: they
are history, but never votes for a threat/benign direction.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from morphsat.receipt_chain import canonical_hash
from morphsat.receipt_graph import NON_DIRECTIONAL_OUTCOMES  # noqa: F401 (re-export)

THREAT_DIRECTIONS = frozenset({"suspicious", "escalate"})


def canonical_outcome_core(
    episode_id: str,
    final_action: str,
    final_direction: Optional[str],
    monitor_action: str,
    monitor_direction: Optional[str],
    posture_final: str,
    override_source: str = "none",
    attempted_override_source: str = "none",
    override_blocked_by_terminal: bool = False,
) -> Dict[str, Any]:
    core = {
        "episode_id": episode_id,
        "final_action": final_action,
        "final_direction": final_direction,
        "monitor_action": monitor_action,
        "monitor_direction": monitor_direction,
        "posture_final": posture_final,
        "override_source": override_source,
        "attempted_override_source": attempted_override_source,
        "override_blocked_by_terminal": bool(override_blocked_by_terminal),
    }
    core["outcome_ref"] = canonical_hash(core)
    return core


def memory_projection(final_action: str, final_direction: Optional[str],
                      posture_final: str = "") -> Optional[str]:
    """SplitMemory resolution label, or None for 'write no verdict memory'."""
    if final_action == "COMMIT":
        if final_direction == "benign":
            return "benign"
        if final_direction in THREAT_DIRECTIONS:
            return final_direction
        raise ValueError(f"COMMIT without a valid direction: {final_direction!r}")
    if final_action == "ABSTAIN":
        return None if posture_final == "swarm_call" else "abstain"
    return None


def graph_projection(final_action: str, final_direction: Optional[str],
                     posture_final: str = "") -> str:
    """ReceiptGraph node outcome label."""
    if final_action == "COMMIT":
        if final_direction in THREAT_DIRECTIONS or final_direction == "benign":
            return final_direction
        raise ValueError(f"COMMIT without a valid direction: {final_direction!r}")
    if final_action == "ABSTAIN":
        return "handoff" if posture_final == "swarm_call" else "abstain"
    return "unknown"
