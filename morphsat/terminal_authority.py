"""
Terminal authority (P2B, decision D1 = A2).
============================================

Invariant:

    If the monitor has reached a terminal COMMIT or terminal ABSTAIN,
    downstream stages (QUBO, CorrectionEcho, ...) may be evaluated and
    recorded for provenance, but MUST NOT replace the emitted terminal
    result.

    monitor_terminal and monitor_action in {COMMIT, ABSTAIN}
        => final_action == monitor_action
           and final_direction == monitor_direction

For ABSTAIN the monitor direction is None and stays None: no substantive
direction is fabricated to satisfy a schema.

A downstream proposal that agrees with the monitor is not an override
attempt. A disagreeing proposal is an attempt; if the monitor is terminal
it is blocked and preserved as provenance (attempted_*), never erased.

SWARM_CALL resolves as action ABSTAIN in ShadowMonitor and is therefore
covered by the ABSTAIN rule; its semantics are not redesigned here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TERMINAL_AUTHORITY_ACTIONS = frozenset({"COMMIT", "ABSTAIN"})


@dataclass(frozen=True)
class AuthorityResult:
    final_action: str
    final_direction: Optional[str]
    applied_source: str               # stage whose output became final ("none" = monitor)
    attempted: bool                   # a downstream stage proposed something different
    attempted_source: str             # "none" if no attempt
    attempted_action: Optional[str]
    attempted_direction: Optional[str]
    blocked_by_terminal: bool


def resolve_terminal_authority(
    monitor_action: str,
    monitor_direction: Optional[str],
    monitor_terminal: bool,
    proposed_action: Optional[str] = None,
    proposed_direction: Optional[str] = None,
    proposed_source: str = "none",
) -> AuthorityResult:
    """Decide the emitted result given the monitor result and one proposal."""
    monitor_result = (monitor_action, monitor_direction)

    if proposed_source == "none":
        return AuthorityResult(monitor_action, monitor_direction, "none",
                               False, "none", None, None, False)

    if (proposed_action, proposed_direction) == monitor_result:
        # Agreement: the downstream stage assigned the same result.
        return AuthorityResult(monitor_action, monitor_direction,
                               proposed_source, False, "none", None, None,
                               False)

    if monitor_terminal and monitor_action in TERMINAL_AUTHORITY_ACTIONS:
        return AuthorityResult(monitor_action, monitor_direction, "none",
                               True, proposed_source, proposed_action,
                               proposed_direction, True)

    return AuthorityResult(proposed_action, proposed_direction,
                           proposed_source, True, proposed_source,
                           proposed_action, proposed_direction, False)
